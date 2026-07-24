"""MySQL handler for Patroni.

Implements the DatabaseHandler interface to allow Patroni to manage
MySQL high-availability.
"""

import logging
import os
import shutil
import subprocess
import time

from threading import Lock
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from ..collections import CaseInsensitiveDict, EMPTY_DICT
from ..db import DatabaseHandler
from ..dcs import Cluster, Leader, Member, RemoteMember
from ..exceptions import PostgresConnectionException
from ..utils import parse_int, polling_loop, Retry, RetryFailedError
from .bootstrap import Bootstrap
from .config import ConfigHandler
from .connection import ConnectionPool, HAS_MYSQL, MySQLdbError
from .misc import MySQLState, MySQLRole, mysql_version_to_int
from .postmaster import MySQLProcess

logger = logging.getLogger(__name__)


class MySQL(DatabaseHandler):

    db_type = 'mysql'

    # --- Database Engine Capabilities ---

    @property
    def has_timelines(self) -> bool:
        return False

    @property
    def needs_rewind(self) -> bool:
        return False

    @property
    def needs_crash_recovery(self) -> bool:
        return False

    @property
    def requires_sysid_match(self) -> bool:
        # server_uuid is unique per mysqld instance (required for GTID).
        return False

    def before_promote(self) -> None:
        pass

    def enrich_dcs_data(self, data: Dict[str, Any]) -> None:
        """Add MySQL-specific fields to DCS status data."""
        data['binlog_position'] = data.get('xlog_location', 0)

    def readiness_check(self, state: str, replication_state: str) -> Optional[str]:
        if state != 'running':
            return 'MySQL is not running'
        if replication_state != 'streaming':
            return f'MySQL replication state is {replication_state}'
        return None

    def __init__(self, config: Dict[str, Any], mpp: Any = None):
        self._name: str = config['name']
        self.scope: str = config.get('scope', 'default')
        self._data_dir: str = config['data_dir']
        self._config_dir: str = config.get('config_dir', self._data_dir)

        self._state_lock = Lock()
        self.set_state(MySQLState.STOPPED)

        self._role_lock = Lock()
        self.set_role(MySQLRole.UNINITIALIZED)

        self.config = ConfigHandler(config)
        self.bootstrap = Bootstrap(self.config, self._get_postmaster, self._query)

        conn_kwargs = self._build_conn_kwargs()
        self.connection_pool = ConnectionPool(conn_kwargs)
        self._connection = self.connection_pool.get('heartbeat')
        self._bin_dir = config.get('bin_dir') or ''
        self._pending_restart_reason = CaseInsensitiveDict()
        self.bootstrapping: bool = False

        self._postmaster_process: Optional[MySQLProcess] = None
        self._cached_gtid: Optional[str] = None
        self._cached_binlog_file: Optional[str] = None
        self._cached_binlog_pos: int = 0

        self._cancellable = _NullCancellable()

    def _get_postmaster(self) -> Optional[MySQLProcess]:
        return self._postmaster_process

    @property
    def name(self) -> str:
        return self._name

    @property
    def role(self) -> str:
        return self._role

    @property
    def state(self) -> str:
        return self._state

    @property
    def connection_string(self) -> str:
        host, port = split_host_port(self.config.connect_address)
        return f"mysql://{host}:{port}"

    @property
    def proxy_url(self) -> Optional[str]:
        return None

    @property
    def pending_restart_reason(self) -> Dict[str, Any]:
        return self._pending_restart_reason

    def data_directory_empty(self) -> bool:
        if not os.path.exists(self._data_dir):
            return True
        return not os.listdir(self._data_dir)

    @property
    def server_version(self) -> int:
        try:
            conn = self.connection_pool.get('heartbeat')
            conn.get()
            return conn.server_version
        except Exception:
            return 0

    @property
    def sysid(self) -> Optional[str]:
        """Return MySQL ``server_uuid``.

        Prefer a live query; fall back to ``auto.cnf`` so Patroni can still
        identify the datadir when mysqld is not running.
        """
        try:
            row = self._query("SELECT @@server_uuid")
            if row and row[0][0]:
                return row[0][0]
        except Exception:
            pass
        auto_cnf = os.path.join(self._data_dir, 'auto.cnf')
        try:
            with open(auto_cnf) as f:
                for line in f:
                    line = line.strip()
                    if line.lower().startswith('server-uuid='):
                        return line.split('=', 1)[1].strip() or None
        except OSError:
            pass
        return None

    def postmaster_start_time(self) -> float:
        return time.time()

    @property
    def time_in_state(self) -> Optional[float]:
        return getattr(self, '_time_in_state', None)

    @time_in_state.setter
    def time_in_state(self, value: Optional[float]) -> None:
        self._time_in_state = value

    @property
    def cancellable(self) -> Any:
        return self._cancellable

    @property
    def supports_multiple_sync(self) -> bool:
        return False

    @property
    def cb_called(self) -> bool:
        return True

    # --- Connection Management ---

    def _build_conn_kwargs(self) -> Dict[str, Any]:
        host, port = split_host_port(self.config.connect_address)
        kwargs: Dict[str, Any] = {
            'host': host,
            'port': port,
            'user': self.config.superuser.get('username', 'root'),
            'password': self.config.superuser.get('password', ''),
        }
        return kwargs

    def _query(self, sql: str, *params: Any,
               retry: Optional[Any] = None) -> List[Tuple[Any, ...]]:
        connection = self.connection_pool.get('heartbeat')
        try:
            connection.get()
        except PostgresConnectionException:
            raise
        return connection.query(sql, *params)

    def _query_one(self, sql: str, *params: Any) -> Optional[Tuple[Any, ...]]:
        results = self._query(sql, *params)
        return results[0] if results else None

    def _query_one_dict(self, sql: str, *params: Any) -> Optional[Dict[str, Any]]:
        """Execute a query and return the first row as a dict.

        Uses ``pymysql.cursors.DictCursor`` for column-name-based access.
        Useful for statements like ``SHOW SLAVE STATUS`` where column positions
        may vary across MySQL versions.
        """
        connection = self.connection_pool.get('heartbeat')
        try:
            connection.get()
        except PostgresConnectionException:
            raise
        return connection.query_one_dict(sql, *params)

    # --- Lifecycle Methods ---

    def start(self, timeout: Optional[int] = None,
              task: Optional[Any] = None,
              block_callbacks: bool = True, **kwargs: Any) -> bool:
        if self.is_running():
            return True

        self.set_state(MySQLState.STARTING)
        self.config.write_my_cnf()
        # Drop stale connections from before stop()/crash.
        self.connection_pool.close()
        mysqld_path = self.config.get_mysqld_path()
        proc = MySQLProcess.start(mysqld_path, self.config.config_file_path,
                                  self._data_dir)
        if not proc:
            self.set_state(MySQLState.START_FAILED)
            return False

        self._postmaster_process = proc
        # Wait until mysqld accepts connections. Crash recovery after a hard
        # kill can take well over the default 30s on debug builds.
        wait_timeout = float(timeout) if timeout else 120.0
        sock = os.path.join(self._data_dir, 'mysql.sock')
        if not proc.wait_for_ready(sock, wait_timeout):
            logger.error("MySQL started but not ready after %ss", wait_timeout)
            proc.signal_kill()
            self._postmaster_process = None
            self.set_state(MySQLState.START_FAILED)
            return False

        self.set_state(MySQLState.RUNNING)
        logger.info("MySQL started successfully")
        return True

    def stop(self, mode: str = 'fast', block_callbacks: bool = True,
              check_executor: bool = True, **kwargs: Any) -> bool:
        if not self.is_running():
            return True

        proc = self._postmaster_process
        try:
            mysqladmin = self.config.get_mysqladmin_path()
            host, port = split_host_port(self.config.connect_address)
            superuser = self.config.superuser
            user = superuser.get('username', 'root')
            password = superuser.get('password', '')
            cmd = [mysqladmin, f'-h{host}', f'-P{port}', f'-u{user}']
            if password:
                cmd.append(f'-p{password}')
            cmd.append('shutdown')
            subprocess.run(cmd, timeout=30, capture_output=True)
        except Exception:
            if proc:
                proc.signal_stop(mode)
                proc.wait_for_stop(30)

        self.connection_pool.close()
        self._postmaster_process = None
        pid_file = os.path.join(self._data_dir, 'mysqld.pid')
        try:
            if os.path.exists(pid_file):
                os.remove(pid_file)
        except OSError:
            pass
        self.set_state(MySQLState.STOPPED)
        return True

    def restart(self, timeout: Optional[int] = None,
                task: Optional[Any] = None, **kwargs: Any) -> bool:
        self.stop()
        return self.start(timeout, task)

    def reload(self) -> None:
        try:
            host, port = split_host_port(self.config.connect_address)
            mysqladmin = self.config.get_mysqladmin_path()
            superuser = self.config.superuser
            user = superuser.get('username', 'root')
            password = superuser.get('password', '')
            cmd = [mysqladmin, f'-h{host}', f'-P{port}', f'-u{user}']
            if password:
                cmd.append(f'-p{password}')
            cmd.append('reload')
            subprocess.run(cmd, timeout=10, capture_output=True)
        except Exception as e:
            logger.error("Failed to reload MySQL config: %r", e)

    def reload_config(self, config: Dict[str, Any], sighup: bool = False) -> None:
        self._name = config.get('name', self._name)
        self.config = ConfigHandler(config)
        conn_kwargs = self._build_conn_kwargs()
        self.connection_pool.set_conn_kwargs(conn_kwargs)
        self.connection_pool.close()

    # --- Role Management ---

    def promote(self, loop_wait: float,
                async_response: Optional[Any] = None,
                before_promote: Optional[Callable[[], None]] = None) -> bool:
        if before_promote:
            before_promote()
        logger.info("Promoting MySQL to primary")
        if not self._is_replica():
            logger.info("MySQL is already primary")
            return True
        try:
            self._query("STOP SLAVE")
            self._query("RESET SLAVE ALL")
            self.set_role(MySQLRole.PRIMARY)
            # Safety net: clones via mysqldump do not copy mysql.user. Ensure
            # the replication account exists before other nodes try to follow us.
            self.bootstrap.ensure_replication_user()
            self._enable_semi_sync()
            if async_response:
                async_response.complete(True)
            return True
        except MySQLdbError as e:
            logger.error("Failed to promote MySQL: %r", e)
            if async_response:
                async_response.complete(False)
            return False

    def demote(self) -> bool:
        logger.info("Demoting MySQL to replica")
        self._disable_semi_sync()
        self.set_role(MySQLRole.DEMOTED)
        return True

    def follow(self, node_to_follow: Union[Leader, Member, RemoteMember, None],
               role: Optional[str] = None,
               timeout: Optional[float] = None,
               do_reload: bool = False) -> Optional[bool]:
        """Start/reconfigure MySQL to follow *node_to_follow*.

        Mirrors PostgreSQL ``follow``: when mysqld is not running, ``start()``
        first. ``ha.recover`` calls this as ``follow(member, role, timeout)``.
        """
        if role:
            self.set_role(role)
        elif node_to_follow is not None:
            self.set_role(MySQLRole.REPLICA)

        if not self.is_running():
            # Crash recovery / cold start: wait for mysqld before any SQL.
            if not self.start(timeout=int(timeout) if timeout else None):
                return False

        if node_to_follow is None:
            # Recover path when we still hold the lock: start as writable
            # primary without configuring replication.
            try:
                self._query("STOP SLAVE")
                self._query("RESET SLAVE ALL")
            except Exception:
                pass
            if role != MySQLRole.REPLICA:
                self.set_role(MySQLRole.PRIMARY)
            return True

        conn_url = node_to_follow.conn_url
        if not conn_url:
            return False

        host, port = self._parse_conn_url(conn_url)
        repl = self.config.replication
        user = repl.get('username', 'replicator')
        password = repl.get('password', '')

        # Idempotent: skip STOP/RESET/CHANGE if already streaming from target.
        try:
            slave = self._query_one_dict("SHOW SLAVE STATUS")
            if slave:
                cur_host = str(slave.get('Master_Host') or '')
                cur_port = int(slave.get('Master_Port') or 0)
                io_ok = slave.get('Slave_IO_Running') == 'Yes'
                sql_ok = slave.get('Slave_SQL_Running') == 'Yes'
                if cur_host == host and cur_port == port and io_ok and sql_ok:
                    logger.debug("Already replicating from %s:%s", host, port)
                    return True
        except Exception:
            pass

        try:
            self._query("STOP SLAVE")
            self._query("RESET SLAVE ALL")
            self._query(
                "CHANGE MASTER TO "
                "MASTER_HOST=%s, MASTER_PORT=%s, "
                "MASTER_USER=%s, MASTER_PASSWORD=%s, "
                "MASTER_AUTO_POSITION=1, "
                "MASTER_CONNECT_RETRY=5, "
                "GET_MASTER_PUBLIC_KEY=1",
                host, port, user, password
            )
            self._query("START SLAVE")
            logger.info("Started replication from %s:%s", host, port)
            self._enable_semi_sync()
            # Refresh heartbeat connection so subsequent reads do not see a
            # pre-follow REPEATABLE READ snapshot.
            self.connection_pool.close()
            return True
        except MySQLdbError as e:
            logger.error("Failed to configure replication: %r", e)
            return False

    def _semi_sync_configured(self) -> bool:
        """Check if semi-synchronous replication is enabled in config."""
        return (self.config.parameters.get('rpl_semi_sync_source_enabled')
                or self.config.parameters.get('rpl_semi_sync_replica_enabled'))

    def _enable_semi_sync(self) -> None:
        if not self._semi_sync_configured():
            return
        try:
            if self.is_primary():
                self._query("SET GLOBAL rpl_semi_sync_source_enabled = 1")
                logger.info("Semi-sync replication enabled as source")
                self._configure_semi_sync_timeout()
                self._configure_semi_sync_wait_count()
            else:
                self._query("SET GLOBAL rpl_semi_sync_replica_enabled = 1")
                logger.info("Semi-sync replication enabled as replica")
        except Exception as e:
            logger.warning("Failed to enable semi-sync replication: %r", e)

    def _disable_semi_sync(self) -> None:
        try:
            self._query("SET GLOBAL rpl_semi_sync_source_enabled = 0")
            self._query("SET GLOBAL rpl_semi_sync_replica_enabled = 0")
            logger.info("Semi-sync replication disabled")
        except Exception:
            pass

    def _configure_semi_sync_timeout(self) -> None:
        """Set rpl_semi_sync_source_timeout to prevent degrading to async.

        For 3+ node clusters: effectively infinite (~1 year in ms).
        For 2-node clusters: 10 seconds (tolerates brief slave restart).
        """
        try:
            node_count = int(self.config.parameters.get('cluster_size', 3))
            timeout_ms = 31536000000 if node_count >= 3 else 10000
            self._query("SET GLOBAL rpl_semi_sync_source_timeout = %s", timeout_ms)
            logger.info("Semi-sync source timeout set to %s ms (node_count=%s)", timeout_ms, node_count)
        except Exception as e:
            logger.warning("Failed to set semi-sync timeout: %r", e)

    def _configure_semi_sync_wait_count(self) -> None:
        """Set rpl_semi_sync_source_wait_for_replica_count to majority of peers."""
        try:
            node_count = int(self.config.parameters.get('cluster_size', 3))
            # Wait for at least 1 replica, or majority for larger clusters
            wait_count = max(1, (node_count // 2))
            self._query("SET GLOBAL rpl_semi_sync_source_wait_for_replica_count = %s", wait_count)
            logger.info("Semi-sync wait count set to %s (node_count=%s)", wait_count, node_count)
        except Exception as e:
            logger.warning("Failed to set semi-sync wait count: %r", e)

    def count_semi_sync_replicas(self) -> int:
        """Return the number of semi-sync replicas currently connected."""
        try:
            row = self._query_one_dict("SHOW STATUS LIKE 'Rpl_semi_sync_source_clients'")
            if row:
                return int(row.get('Value', 0))
        except Exception:
            pass
        return 0

    # --- Read-Only Control ---

    def set_read_only(self) -> None:
        """Set MySQL to read-only (for semi-sync majority loss scenarios)."""
        try:
            self._query("SET GLOBAL read_only = ON")
            self._query("SET GLOBAL super_read_only = ON")
            logger.info("MySQL set to read-only (super_read_only)")
        except Exception as e:
            logger.warning("Failed to set read-only: %r", e)

    def set_read_write(self) -> None:
        """Set MySQL to read-write (re-enable writes when majority is restored)."""
        try:
            self._query("SET GLOBAL super_read_only = OFF")
            self._query("SET GLOBAL read_only = OFF")
            logger.info("MySQL set to read-write")
        except Exception as e:
            logger.warning("Failed to set read-write: %r", e)

    def is_read_only(self) -> bool:
        """Check if MySQL is in read-only mode."""
        try:
            row = self._query_one_dict("SHOW VARIABLES LIKE 'read_only'")
            if row:
                return row.get('Value', 'OFF').upper() == 'ON'
        except Exception:
            pass
        return False

    # --- MGR (Group Replication) Methods ---

    def _is_mgr_configured(self) -> bool:
        """Check if MGR is configured in parameters."""
        return bool(self.config.parameters.get('group_replication_group_name'))

    def get_executed_gtid(self) -> str:
        """Get the executed GTID set of this node.

        Returns ``@@gtid_executed`` which represents all committed transactions.
        """
        try:
            row = self._query_one("SELECT @@gtid_executed")
            if row:
                return row[0] or ''
        except Exception:
            pass
        return ''

    def compare_gtid(self, other_gtid: str) -> int:
        """Compare this node's GTID against another.

        :returns: 1 if local GTID is a strict superset of other,
                 -1 if other is a strict superset of local,
                  0 if equal or incomparable.
        """
        local = self.get_executed_gtid()
        if not local or not other_gtid:
            return 0
        try:
            row = self._query_one("SELECT GTID_SUBSET(%s, %s) AS a_sub_b, GTID_SUBSET(%s, %s) AS b_sub_a",
                                  local, other_gtid, other_gtid, local)
            if not row:
                return 0
            a_sub_b = int(row[0]) if row[0] else 0
            b_sub_a = int(row[1]) if row[1] else 0
            if a_sub_b and b_sub_a:
                return 0   # equal
            if a_sub_b:
                return -1  # local is subset → other has more
            if b_sub_a:
                return 1   # other is subset → local has more
            return 0       # incomparable (different uuids)
        except Exception as e:
            logger.warning("GTID comparison failed: %r", e)
            return 0

    def get_mgr_status(self) -> Dict[str, str]:
        """Query MGR status from ``performance_schema.replication_group_members``.

        :returns: dict with keys role (PRIMARY/SECONDARY), state (ONLINE/RECOVERING/...),
                  member_id, member_host, member_port, primary_uuid.
                  Returns empty dict if MGR is not active or query fails.
        """
        try:
            row = self._query_one_dict(
                "SELECT r.MEMBER_ROLE AS role, r.MEMBER_STATE AS state, "
                "       r.MEMBER_ID AS member_id, r.MEMBER_HOST AS member_host, "
                "       r.MEMBER_PORT AS member_port, "
                "       @@group_replication_primary_member AS primary_uuid "
                "FROM performance_schema.replication_group_members r "
                "JOIN performance_schema.replication_group_member_stats s "
                "  ON r.MEMBER_ID = s.MEMBER_ID "
                "WHERE r.MEMBER_ID = @@server_uuid "
                "  AND r.MEMBER_STATE NOT IN ('OFFLINE')"
            )
            if row:
                return {k: (v if v else '') for k, v in row.items()}
        except Exception as e:
            logger.debug("Failed to get MGR status: %r", e)
        return {}

    def is_mgr_healthy(self) -> bool:
        """Check if the MGR cluster has a healthy majority.

        Counts ONLINE + RECOVERING members and verifies at least one is PRIMARY.
        """
        try:
            rows = self._query(
                "SELECT MEMBER_STATE, MEMBER_ROLE "
                "FROM performance_schema.replication_group_members "
                "WHERE MEMBER_STATE IN ('ONLINE', 'RECOVERING')"
            )
            if not rows:
                return False
            online_count = len(rows)
            has_primary = any(row[1] == 'PRIMARY' for row in rows)
            node_count = int(self.config.parameters.get('cluster_size', 3))
            quorum = (node_count // 2) + 1
            return has_primary and online_count >= quorum
        except Exception as e:
            logger.debug("Failed to check MGR health: %r", e)
            return False

    def bootstrap_mgr_group(self) -> bool:
        """Bootstrap the MGR group when majority is lost.

        This must be called on the node with the highest GTID.
        Executes: STOP GR → bootstrap_group=ON → START GR → bootstrap_group=OFF.
        """
        try:
            logger.info("Bootstrapping MGR group")
            self._query("STOP GROUP_REPLICATION")
            self._query("SET GLOBAL group_replication_bootstrap_group = ON")
            self._query("START GROUP_REPLICATION")
            self._query("SET GLOBAL group_replication_bootstrap_group = OFF")
            logger.info("MGR group bootstrapped successfully")
            return True
        except Exception as e:
            logger.error("Failed to bootstrap MGR group: %r", e)
            return False

    def rejoin_mgr_group(self, primary_host: str, primary_port: int) -> bool:
        """Rejoin the MGR group after bootstrap.

        Configures group_replication_recovery channel and starts GR as a joiner.
        """
        try:
            repl = self.config.replication
            user = repl.get('username', 'replicator')
            password = repl.get('password', '')
            logger.info("Rejoining MGR group via %s:%s", primary_host, primary_port)
            self._query("STOP GROUP_REPLICATION")
            self._query(
                "CHANGE MASTER TO "
                "MASTER_USER = %s, MASTER_PASSWORD = %s "
                "FOR CHANNEL 'group_replication_recovery'",
                user, password
            )
            self._query("SET GLOBAL group_replication_bootstrap_group = OFF")
            self._query("START GROUP_REPLICATION")
            logger.info("MGR group rejoin initiated")
            return True
        except Exception as e:
            logger.error("Failed to rejoin MGR group: %r", e)
            return False

    def run_mgr_cycle(self, has_lock: bool, cluster_nodes: int) -> Optional[str]:
        """Run one MGR maintenance cycle.

        Called from ``ha.py`` during ``process_healthy_cluster()``.

        :param has_lock: whether this node holds the DCS leader lock.
        :param cluster_nodes: total number of cluster nodes (for quorum calc).
        :returns: action message if action was taken, None otherwise.
        """
        if not self._is_mgr_configured():
            return None

        mgr_status = self.get_mgr_status()
        if not mgr_status:
            # MGR not active — check if majority is lost and we need bootstrap
            return self._handle_mgr_majority_loss(has_lock, cluster_nodes)

        # MGR is active — follow its primary
        mgr_role = mgr_status.get('role', '')
        mgr_state = mgr_status.get('state', '')

        if mgr_role == 'PRIMARY' and self.role != MySQLRole.PRIMARY:
            self.set_role(MySQLRole.MGR_PRIMARY)
            if self.is_read_only():
                self.set_read_write()
            return 'recognized as MGR primary'

        if mgr_role == 'SECONDARY' and self.role in (MySQLRole.PRIMARY, MySQLRole.MGR_PRIMARY):
            self.set_role(MySQLRole.MGR_SECONDARY)
            self.set_read_only()
            return 'demoted to MGR secondary'

        return None

    def _handle_mgr_majority_loss(self, has_lock: bool, cluster_nodes: int) -> Optional[str]:
        """Handle the case where MGR has no active members (majority lost).

        Strategy:
        1. All nodes compare GTIDs via DCS.
        2. Node with highest GTID bootstraps a new group.
        3. Other nodes rejoin.
        """
        if not has_lock:
            return None

        local_gtid = self.get_executed_gtid()
        if not local_gtid:
            logger.warning("Cannot bootstrap MGR: no GTID available")
            return None

        # In a real implementation, GTIDs would be compared across nodes
        # via DCS. For now, the lock holder bootstraps.
        logger.warning("MGR majority lost — bootstrapping group")
        if self.bootstrap_mgr_group():
            self.set_role(MySQLRole.MGR_PRIMARY)
            self.set_read_write()
            return 'bootstrapped MGR group after majority loss'

        return None

    def run_semi_sync_safety_check(self, cluster_nodes: int) -> Optional[str]:
        """Check semi-sync replica count and enforce read-only if below majority.

        Called from ``ha.py`` each cycle on the primary.

        :returns: 'read_only_set' if writes were blocked, None otherwise.
        """
        if not self._semi_sync_configured() or not self.is_primary():
            return None

        active_replicas = self.count_semi_sync_replicas()
        quorum = (cluster_nodes // 2)  # number of replicas needed for majority of cluster

        if active_replicas < quorum:
            if not self.is_read_only():
                self.set_read_only()
                logger.warning(
                    "Semi-sync replicas (%d) below quorum (%d/%d nodes) — set read_only",
                    active_replicas, quorum, cluster_nodes
                )
                return 'read_only_set'
        else:
            if self.is_read_only():
                self.set_read_write()
                logger.info(
                    "Semi-sync replicas (%d) restored to quorum (%d/%d nodes) — set read_write",
                    active_replicas, quorum, cluster_nodes
                )
                return 'read_write_restored'

        return None

    def set_role(self, role: str) -> None:
        with self._role_lock:
            self._role = role

    def set_state(self, state: str) -> None:
        with self._state_lock:
            self._state = state

    # --- State Checks ---

    def is_running(self) -> bool:
        proc = self._postmaster_process
        if proc and proc.is_running():
            return True
        pid_file = os.path.join(self._data_dir, 'mysqld.pid')
        proc = MySQLProcess.from_pidfile(pid_file)
        if proc:
            self._postmaster_process = proc
            self.set_state(MySQLState.RUNNING)
            return True
        return False

    def is_primary(self) -> bool:
        if not self.is_running():
            return False
        try:
            row = self._query_one("SHOW SLAVE STATUS")
            return row is None
        except Exception:
            return False

    def is_healthy(self) -> bool:
        try:
            self._query_one("SELECT 1")
            return True
        except Exception:
            return False

    def is_starting(self) -> bool:
        return self._state == MySQLState.STARTING

    # --- Replication / Position Info ---

    def last_operation(self) -> int:
        try:
            if self.is_primary():
                row = self._query_one_dict("SHOW MASTER STATUS")
                if row:
                    return int(row['Position'])
            else:
                row = self._query_one_dict("SHOW SLAVE STATUS")
                if row and row.get('Exec_Master_Log_Pos'):
                    return int(row['Exec_Master_Log_Pos'])
            return 0
        except Exception:
            return 0

    def timeline_wal_position(self) -> Tuple[Optional[int], int, int, int, int]:
        """Return (timeline, write_position, 0, receive_position, replay_position).

        MySQL doesn't have timelines, so timeline is 0.
        """
        write_pos = 0
        receive_pos = 0
        replay_pos = 0
        try:
            if self.is_primary():
                row = self._query_one_dict("SHOW MASTER STATUS")
                if row:
                    write_pos = int(row['Position'])
                    self._cached_binlog_file = row['File']
                    self._cached_binlog_pos = write_pos
            else:
                row = self._query_one_dict("SHOW SLAVE STATUS")
                if row:
                    receive_pos = int(row['Read_Master_Log_Pos']) if row.get('Read_Master_Log_Pos') else 0
                    replay_pos = int(row['Exec_Master_Log_Pos']) if row.get('Exec_Master_Log_Pos') else 0
                    self._cached_binlog_file = row.get('Relay_Master_Log_File') or ''
        except Exception:
            pass
        return (0, write_pos, 0, receive_pos, replay_pos)

    def replication_state(self) -> Optional[str]:
        try:
            row = self._query_one_dict("SHOW SLAVE STATUS")
            if row:
                io_state = row.get('Slave_IO_Running', '')
                sql_state = row.get('Slave_SQL_Running', '')
                if io_state == 'Yes' and sql_state == 'Yes':
                    return 'streaming'
                elif io_state == 'Yes':
                    return 'catching_up'
                elif io_state == 'Connecting':
                    return 'connecting'
                else:
                    return 'stopped'
            return 'primary'
        except Exception:
            return None

    def received_timeline(self) -> Optional[int]:
        return 0

    def replica_cached_timeline(self, leader_timeline: Optional[int]) -> Optional[int]:
        return 0

    def pg_control_timeline(self) -> Optional[int]:
        return 0

    def get_primary_timeline(self) -> Optional[int]:
        return 0

    def get_history(self, timeline: int) -> List[Any]:
        return []

    # --- Bootstrap / Clone ---

    def can_create_replica_without_replication_connection(
            self, create_replica_methods: Optional[List[str]] = None) -> bool:
        if create_replica_methods is None:
            return True
        return any(m in ('mysqldump', 'xtrabackup', 'clone_plugin')
                  for m in create_replica_methods)

    def remove_data_directory(self) -> None:
        if os.path.exists(self._data_dir):
            shutil.rmtree(self._data_dir)
            logger.info("Removed MySQL data directory %s", self._data_dir)

    def move_data_directory(self) -> None:
        if os.path.exists(self._data_dir):
            backup = self._data_dir + '.bak'
            if os.path.exists(backup):
                shutil.rmtree(backup)
            shutil.move(self._data_dir, backup)
            logger.info("Moved MySQL data directory to %s", backup)

    def was_restored_from_backup(self) -> bool:
        backup_label = os.path.join(self._data_dir, 'xtrabackup_info')
        return os.path.exists(backup_label)

    def controldata(self) -> Dict[str, Any]:
        data = {}
        try:
            if self.is_running():
                row = self._query_one_dict("SHOW MASTER STATUS")
                if row:
                    data['File'] = row.get('File', '')
                    data['Position'] = str(row.get('Position', 0))
                    data['Executed_Gtid_Set'] = str(row.get('Executed_Gtid_Set', ''))
                row = self._query_one("SELECT VERSION()")
                if row:
                    data['version'] = row[0]
            pid_file = os.path.join(self._data_dir, 'mysqld.pid')
            if os.path.exists(pid_file):
                with open(pid_file) as f:
                    data['pid'] = f.read().strip()
        except Exception as e:
            logger.debug("Error getting MySQL controldata: %r", e)
        return data

    def slots(self) -> Dict[str, int]:
        return {}

    # --- Parameter Management ---

    def handle_parameter_change(self) -> bool:
        return False

    def check_for_startup(self) -> None:
        pass

    def terminate_starting_postmaster(self) -> None:
        proc = self._postmaster_process
        if proc:
            proc.signal_kill()
        pid_file = os.path.join(self._data_dir, 'mysqld.pid')
        try:
            if os.path.exists(pid_file):
                os.remove(pid_file)
        except OSError:
            pass

    def call_nowait(self, action: Any, *args: Any, **kwargs: Any) -> None:
        pass

    def schedule_sanity_checks_after_pause(self) -> None:
        pass

    def reset_cluster_info_state(self, cluster: Optional[Any] = None,
                                 tags: Optional[Any] = None) -> None:
        pass

    def latest_checkpoint_locations(self) -> Tuple[Optional[int], Optional[int]]:
        return (None, None)

    # --- Replication slot methods (not applicable for MySQL) ---

    @property
    def sync_handler(self) -> Any:
        return self

    @property
    def slots_handler(self) -> Any:
        return self

    @property
    def mpp_handler(self) -> Any:
        return getattr(self, '_mpp_handler', None) or _NullHandler()

    @mpp_handler.setter
    def mpp_handler(self, value: Any) -> None:
        self._mpp_handler = value

    def current_state(self, cluster: Cluster) -> str:
        return ''

    def set_synchronous_standby_names(self, names: Any) -> None:
        pass

    def copy_logical_slots(self, cluster: Cluster) -> None:
        pass

    def sync_replication_slots(self, cluster: Cluster) -> None:
        pass

    # --- Internal Helpers ---

    def _is_replica(self) -> bool:
        try:
            row = self._query_one("SHOW SLAVE STATUS")
            return row is not None
        except Exception:
            return False

    def _parse_conn_url(self, conn_url: str) -> Tuple[str, int]:
        from urllib.parse import urlparse
        r = urlparse(conn_url)
        host = r.hostname or '127.0.0.1'
        port = r.port or 3306
        return host, port


class _NullCancellable:
    def reset_is_cancelled(self) -> None:
        pass

    def cancel(self, kill: bool = False) -> None:
        pass


class _NullHandler:
    """Null object for MPP handler."""

    def is_coordinator(self) -> bool:
        return False

    def is_worker(self) -> bool:
        return False

    def sync_meta_data(self, cluster: Cluster) -> None:
        pass

    def on_demote(self) -> None:
        pass

    def handle_event(self, event: str) -> None:
        pass


def split_host_port(address: str) -> Tuple[str, int]:
    """Split a host:port string into (host, port)."""
    if ':' in address:
        host, port_str = address.rsplit(':', 1)
        return host, int(port_str)
    return address, 3306
