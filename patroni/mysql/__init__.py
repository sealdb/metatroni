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
from .misc import MySQLState, MySQLRole, CreateReplicaMethod, mysql_version_to_int
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
        # Publish executed GTID for MGR majority-loss bootstrap election.
        gtid = self.get_executed_gtid()
        if gtid:
            data['gtid_executed'] = gtid
        fork = getattr(self, '_mgr_gtid_fork', None)
        if fork:
            data['mgr_gtid_fork'] = fork
        elif 'mgr_gtid_fork' in data:
            data.pop('mgr_gtid_fork', None)

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
        last_exc: Optional[Exception] = None
        for attempt in range(2):
            connection = self.connection_pool.get('heartbeat')
            try:
                connection.get()
                return connection.query(sql, *params)
            except (PostgresConnectionException, AttributeError, TypeError) as e:
                last_exc = e
                # GR start/stop flips super_read_only and can drop the pooled conn.
                self.connection_pool.close()
                if attempt == 0:
                    continue
                raise
        if last_exc:
            raise last_exc
        return []

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
            self.set_read_write()
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
            if role not in (MySQLRole.REPLICA, MySQLRole.STANDBY_LEADER,
                            'replica', 'standby_leader'):
                self.set_role(MySQLRole.PRIMARY)
            return True

        conn_url = node_to_follow.conn_url
        if not conn_url:
            return False

        host, port = self._parse_conn_url(conn_url)
        # Multi-host standby_cluster.host (PG style): take the first address.
        if host and ',' in host:
            host = host.split(',')[0].strip()
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
                    try:
                        self.set_read_only()
                    except Exception:
                        pass
                    if role in (MySQLRole.STANDBY_LEADER, 'standby_leader'):
                        self.set_role(MySQLRole.STANDBY_LEADER)
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
            self.set_read_only()
            if role in (MySQLRole.STANDBY_LEADER, 'standby_leader'):
                self.set_role(MySQLRole.STANDBY_LEADER)
            # Semi-sync as replica is fine for cascade; never enable source mode
            # while we are (standby) replica.
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
                # Financial-grade: AFTER_SYNC so the commit waits until the event
                # is durable on the source and ACKed by enough replicas (xenon).
                try:
                    self._query("SET GLOBAL rpl_semi_sync_source_wait_point = 'AFTER_SYNC'")
                except Exception:
                    # MySQL 5.7 legacy name
                    try:
                        self._query("SET GLOBAL rpl_semi_sync_master_wait_point = 'AFTER_SYNC'")
                    except Exception as e:
                        logger.warning("Failed to set semi-sync wait_point=AFTER_SYNC: %r", e)
                try:
                    self._query("SET GLOBAL rpl_semi_sync_source_wait_no_replica = 1")
                except Exception:
                    try:
                        self._query("SET GLOBAL rpl_semi_sync_source_wait_no_slave = 1")
                    except Exception:
                        try:
                            self._query("SET GLOBAL rpl_semi_sync_master_wait_no_slave = 1")
                        except Exception:
                            pass
                self._query("SET GLOBAL rpl_semi_sync_source_enabled = 1")
                logger.info("Semi-sync replication enabled as source (wait_point=AFTER_SYNC)")
                self._configure_semi_sync_timeout()
                self._configure_semi_sync_wait_count()
            else:
                self._query("SET GLOBAL rpl_semi_sync_replica_enabled = 1")
                logger.info("Semi-sync replication enabled as replica")
        except Exception as e:
            logger.warning("Failed to enable semi-sync replication: %r", e)

    def _configure_semi_sync_timeout(self) -> None:
        """Set rpl_semi_sync_source_timeout to prevent degrading to async.

        Matches xenon: 3+ nodes use an effectively infinite timeout; 2-node
        clusters keep a short timeout (default 10s).
        """
        try:
            node_count = int(self.config.parameters.get('cluster_size', 3))
            # 10**18 ms — same magnitude as xenon's semisyncTimeout.
            timeout_ms = 10 ** 18 if node_count >= 3 else 10000
            try:
                self._query("SET GLOBAL rpl_semi_sync_source_timeout = %s", timeout_ms)
            except Exception:
                self._query("SET GLOBAL rpl_semi_sync_master_timeout = %s", timeout_ms)
            logger.info("Semi-sync source timeout set to %s ms (node_count=%s)", timeout_ms, node_count)
        except Exception as e:
            logger.warning("Failed to set semi-sync timeout: %r", e)

    def _configure_semi_sync_wait_count(self) -> None:
        """Set wait_for_replica_count to (N-1)//2 (xenon majority of peers)."""
        try:
            node_count = int(self.config.parameters.get('cluster_size', 3))
            wait_count = max(1, (node_count - 1) // 2)
            try:
                self._query("SET GLOBAL rpl_semi_sync_source_wait_for_replica_count = %s", wait_count)
            except Exception:
                self._query("SET GLOBAL rpl_semi_sync_master_wait_for_slave_count = %s", wait_count)
            logger.info("Semi-sync wait count set to %s (node_count=%s)", wait_count, node_count)
        except Exception as e:
            logger.warning("Failed to set semi-sync wait count: %r", e)

    def _disable_semi_sync(self) -> None:
        try:
            self._query("SET GLOBAL rpl_semi_sync_source_enabled = 0")
            self._query("SET GLOBAL rpl_semi_sync_replica_enabled = 0")
            logger.info("Semi-sync replication disabled")
        except Exception:
            pass

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

    def is_mgr_configured(self) -> bool:
        return self._is_mgr_configured()

    def get_executed_gtid(self) -> str:
        """Get the executed GTID set of this node.

        Returns ``@@gtid_executed`` which represents all committed transactions.
        """
        try:
            row = self._query_one("SELECT @@gtid_executed")
            if row:
                # Collapse whitespace/newlines MySQL may include in the set.
                return ' '.join(str(row[0] or '').split())
        except Exception:
            pass
        return ''

    def gtid_relation(self, gtid_a: str, gtid_b: str) -> str:
        """Compare two GTID sets using MySQL ``GTID_SUBSET``.

        :returns: ``'equal'``, ``'a_ahead'``, ``'b_ahead'``, or ``'incomparable'``.
        """
        gtid_a = ' '.join(str(gtid_a or '').split())
        gtid_b = ' '.join(str(gtid_b or '').split())
        if not gtid_a or not gtid_b:
            return 'incomparable'
        try:
            row = self._query_one(
                "SELECT GTID_SUBSET(%s, %s), GTID_SUBSET(%s, %s)",
                gtid_a, gtid_b, gtid_b, gtid_a
            )
            if not row:
                return 'incomparable'
            a_sub_b = int(row[0] or 0)
            b_sub_a = int(row[1] or 0)
            if a_sub_b and b_sub_a:
                return 'equal'
            if a_sub_b:
                return 'b_ahead'  # a ⊂ b
            if b_sub_a:
                return 'a_ahead'  # b ⊂ a
            return 'incomparable'
        except Exception as e:
            logger.warning("GTID comparison failed: %r", e)
            return 'incomparable'

    def compare_gtid(self, other_gtid: str) -> int:
        """Compare this node's GTID against another.

        :returns: 1 if local GTID is a strict superset of other,
                 -1 if other is a strict superset of local,
                  0 if equal or incomparable.
        """
        local = self.get_executed_gtid()
        rel = self.gtid_relation(local, other_gtid)
        if rel == 'a_ahead':
            return 1
        if rel == 'b_ahead':
            return -1
        return 0

    def get_mgr_status(self) -> Dict[str, str]:
        """Query MGR status from ``performance_schema.replication_group_members``.

        :returns: dict with keys role (PRIMARY/SECONDARY), state (ONLINE/RECOVERING/...),
                  member_id, member_host, member_port, primary_uuid.
                  Returns empty dict if MGR is not active or query fails.
        """
        try:
            # Avoid joining member_stats — it can lag right after START GR and
            # make a healthy ONLINE member look absent.
            # group_replication_primary_member is a STATUS variable, not @@sysvar.
            row = self._query_one_dict(
                "SELECT MEMBER_ROLE AS role, MEMBER_STATE AS state, "
                "       MEMBER_ID AS member_id, MEMBER_HOST AS member_host, "
                "       MEMBER_PORT AS member_port, "
                "       (SELECT MEMBER_ID FROM performance_schema.replication_group_members "
                "         WHERE MEMBER_ROLE = 'PRIMARY' LIMIT 1) AS primary_uuid "
                "FROM performance_schema.replication_group_members "
                "WHERE MEMBER_ID = @@server_uuid "
                "  AND MEMBER_STATE NOT IN ('OFFLINE', 'ERROR')"
            )
            if row:
                return {k: (v if v is not None else '') for k, v in row.items()}
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

    def rejoin_mgr_group(self, primary_host: str, primary_port: int,
                         timeout: float = 60.0) -> bool:
        """Rejoin the MGR group after bootstrap.

        Configures group_replication_recovery channel and starts GR as a joiner.
        Returns True only after local member reaches ONLINE or RECOVERING — a bare
        ``START GROUP_REPLICATION`` success is not enough (joining a stale/dead
        ``mgr_primary`` from DCS would otherwise look like success and block the
        GTID winner from bootstrapping).
        """
        try:
            repl = self.config.replication
            user = repl.get('username', 'replicator')
            password = repl.get('password', '')
            logger.info("Rejoining MGR group via %s:%s", primary_host, primary_port)
            try:
                self._query("STOP GROUP_REPLICATION")
            except Exception:
                pass
            # Single-primary MGR refuses START while async channels are running.
            try:
                self._query("STOP SLAVE")
            except Exception:
                pass
            try:
                self._query("RESET SLAVE ALL")
            except Exception:
                pass
            # GET_MASTER_PUBLIC_KEY is rejected on group_replication_recovery (ER 3139).
            self._query(
                "CHANGE MASTER TO "
                "MASTER_USER = %s, MASTER_PASSWORD = %s "
                "FOR CHANNEL 'group_replication_recovery'",
                user, password
            )
            self._query("SET GLOBAL group_replication_bootstrap_group = OFF")
            self._query("START GROUP_REPLICATION")
            self.connection_pool.close()

            deadline = time.time() + max(5.0, float(timeout))
            while time.time() < deadline:
                st = self.get_mgr_status()
                if st.get('state') in ('ONLINE', 'RECOVERING'):
                    logger.info("MGR group rejoin succeeded (state=%s)", st.get('state'))
                    return True
                time.sleep(1)

            logger.error(
                "MGR rejoin timed out waiting for ONLINE/RECOVERING via %s:%s",
                primary_host, primary_port
            )
            try:
                self._query("STOP GROUP_REPLICATION")
            except Exception:
                pass
            self.connection_pool.close()
            return False
        except Exception as e:
            logger.error("Failed to rejoin MGR group: %r", e)
            self.connection_pool.close()
            return False

    def bootstrap_mgr_group(self) -> bool:
        """Bootstrap the MGR group when majority is lost.

        This must be called on the node with the highest GTID.
        Executes: STOP GR → bootstrap_group=ON → START GR → bootstrap_group=OFF.
        """
        try:
            logger.info("Bootstrapping MGR group")
            try:
                self._query("STOP GROUP_REPLICATION")
            except Exception:
                pass
            # Recovery credentials are required even for the bootstrapper on MySQL 8.
            # GET_MASTER_PUBLIC_KEY is rejected on group_replication_recovery (ER 3139).
            repl = self.config.replication
            user = repl.get('username', 'replicator')
            password = repl.get('password', '')
            try:
                self._query(
                    "CHANGE MASTER TO "
                    "MASTER_USER = %s, MASTER_PASSWORD = %s "
                    "FOR CHANNEL 'group_replication_recovery'",
                    user, password
                )
            except Exception as e:
                logger.warning("Could not set group_replication_recovery channel: %r", e)
            self._query("SET GLOBAL group_replication_bootstrap_group = ON")
            self._query("START GROUP_REPLICATION")
            self._query("SET GLOBAL group_replication_bootstrap_group = OFF")
            self.connection_pool.close()
            logger.info("MGR group bootstrapped successfully")
            return True
        except Exception as e:
            logger.error("Failed to bootstrap MGR group: %r", e)
            self.connection_pool.close()
            return False

    def run_mgr_cycle(self, has_lock: bool, cluster_nodes: int,
                      members: Optional[List[Any]] = None) -> Optional[str]:
        """Run one MGR maintenance cycle.

        Called from ``ha.py`` during ``process_healthy_cluster()``.

        :param has_lock: whether this node holds the DCS leader lock.
        :param cluster_nodes: total number of cluster nodes (for quorum calc).
        :param members: current DCS members (used for GTID election / rejoin).
        :returns: action message if action was taken, None otherwise.
        """
        if not self._is_mgr_configured():
            return None

        mgr_status = self.get_mgr_status()
        if not mgr_status:
            # MGR not active — majority lost or never started; elect bootstrapper.
            return self._handle_mgr_majority_loss(has_lock, cluster_nodes, members)

        # MGR is active — follow its primary
        mgr_role = mgr_status.get('role', '')

        if mgr_role == 'PRIMARY' and self.role != MySQLRole.MGR_PRIMARY:
            self.set_role(MySQLRole.MGR_PRIMARY)
            if self.is_read_only():
                self.set_read_write()
            self._clear_mgr_gtid_fork()
            return 'recognized as MGR primary'

        if mgr_role == 'SECONDARY' and self.role != MySQLRole.MGR_SECONDARY:
            self.set_role(MySQLRole.MGR_SECONDARY)
            self.set_read_only()
            self._clear_mgr_gtid_fork()
            return 'demoted to MGR secondary'

        if mgr_status:
            self._clear_mgr_gtid_fork()
        return None

    def _member_gtid(self, member: Any) -> str:
        data = getattr(member, 'data', None) or {}
        binlog = data.get('binlog') or {}
        gtid = (data.get('gtid_executed')
                or binlog.get('gtid_set')
                or binlog.get('gtid_executed')
                or '')
        return ' '.join(str(gtid).split())

    def _mgr_gtid_candidates(self, local_gtid: str,
                             members: Optional[List[Any]] = None) -> List[Tuple[str, str]]:
        local_gtid = ' '.join(str(local_gtid or '').split())
        candidates: List[Tuple[str, str]] = []
        if local_gtid:
            candidates.append((self.name, local_gtid))
        for m in members or []:
            name = getattr(m, 'name', None)
            if not name or name == self.name:
                continue
            gtid = self._member_gtid(m)
            if gtid:
                candidates.append((name, gtid))
        return candidates

    def _mgr_maximal_candidates(self, candidates: List[Tuple[str, str]]
                                ) -> List[Tuple[str, str]]:
        maximal: List[Tuple[str, str]] = []
        for name_a, gtid_a in candidates:
            dominated = False
            for name_b, gtid_b in candidates:
                if name_a == name_b:
                    continue
                if self.gtid_relation(gtid_a, gtid_b) == 'b_ahead':
                    dominated = True
                    break
            if not dominated:
                maximal.append((name_a, gtid_a))
        return maximal

    def describe_mgr_gtid_fork(self, local_gtid: str,
                               members: Optional[List[Any]] = None
                               ) -> List[Dict[str, str]]:
        """Return maximal incomparable GTID candidates, or ``[]`` if no fork.

        A fork means two or more members each hold transactions the others lack
        (``GTID_SUBSET`` both ways false). Automatic MGR bootstrap is unsafe.
        """
        candidates = self._mgr_gtid_candidates(local_gtid, members)
        if len(candidates) < 2:
            return []
        maximal = self._mgr_maximal_candidates(candidates)
        if len(maximal) < 2:
            return []
        base_name, base_gtid = maximal[0]
        for name, gtid in maximal[1:]:
            if self.gtid_relation(base_gtid, gtid) != 'equal':
                return [{'name': n, 'gtid_executed': g} for n, g in maximal]
        return []

    def _clear_mgr_gtid_fork(self) -> None:
        if getattr(self, '_mgr_gtid_fork', None):
            self._mgr_gtid_fork = None

    def _record_mgr_gtid_fork(self, fork: List[Dict[str, str]]) -> None:
        self._mgr_gtid_fork = {
            'reason': 'incomparable_gtid_sets',
            'members': fork,
        }

    def mgr_pause_on_gtid_fork_enabled(self) -> bool:
        """Whether detecting a GTID fork should write ``pause: true`` to DCS.

        Controlled by Patroni-only ``parameters.mgr_pause_on_gtid_fork``
        (default ``True``). Not written to ``my.cnf``.
        """
        raw = self.config.parameters.get('mgr_pause_on_gtid_fork', True)
        if raw in (False, 0, '0', 'false', 'False', 'off', 'OFF', 'no', 'NO'):
            return False
        return True

    def select_mgr_bootstrap_winner(self, local_gtid: str,
                                    members: Optional[List[Any]] = None) -> Optional[str]:
        """Choose which member should bootstrap MGR after majority loss.

        Uses GTID_SUBSET over DCS-published ``gtid_executed`` values plus the
        local GTID. Among equal maximal sets, the lexicographically smallest
        member name wins. Returns ``None`` when sets are incomparable.
        """
        candidates = self._mgr_gtid_candidates(local_gtid, members)
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0][0]

        maximal = self._mgr_maximal_candidates(candidates)
        if not maximal:
            return None
        if len(maximal) == 1:
            return maximal[0][0]

        # Multiple maximal: require all equal; then name tie-break.
        base_name, base_gtid = maximal[0]
        for name, gtid in maximal[1:]:
            rel = self.gtid_relation(base_gtid, gtid)
            if rel != 'equal':
                logger.error(
                    "MGR bootstrap election stalled: incomparable GTID sets "
                    "among %s (e.g. %s vs %s)",
                    [n for n, _ in maximal], base_name, name
                )
                return None
        return min(n for n, _ in maximal)

    def _find_mgr_primary_member(self, members: Optional[List[Any]]) -> Optional[Any]:
        """Return a DCS member that already claims a live MGR primary role.

        Only ``mgr_primary`` counts. Generic Patroni ``primary`` is often left
        over after majority loss (async/semi-sync style role) and must not
        block the GTID-elected winner from bootstrapping a new group.
        """
        for m in members or []:
            if getattr(m, 'name', None) == self.name:
                continue
            data = getattr(m, 'data', None) or {}
            role = str(data.get('role') or '')
            if role in (MySQLRole.MGR_PRIMARY, 'mgr_primary'):
                if data.get('conn_url') or getattr(m, 'conn_url', None):
                    return m
        return None

    def _try_rejoin_mgr(self, members: Optional[List[Any]]) -> Optional[str]:
        """Attempt to rejoin via an existing primary advertised in DCS."""
        primary = self._find_mgr_primary_member(members)
        if not primary:
            return None
        conn_url = getattr(primary, 'conn_url', None) or (primary.data or {}).get('conn_url')
        if not conn_url:
            return None
        host, port = self._parse_conn_url(conn_url)
        if self.rejoin_mgr_group(host, port):
            self.set_role(MySQLRole.MGR_SECONDARY)
            self.set_read_only()
            return 'rejoining MGR group after majority loss'
        return None

    def _handle_mgr_majority_loss(self, has_lock: bool, cluster_nodes: int,
                                  members: Optional[List[Any]] = None) -> Optional[str]:
        """Elect a bootstrapper from DCS GTIDs after MGR majority loss.

        Strategy:
        1. Every node publishes ``gtid_executed`` via ``enrich_dcs_data``.
        2. All nodes compute the same winner (max GTID, name tie-break).
        3. Winner bootstraps only while holding the DCS lock.
        4. Lock holder that is *not* the winner yields the lock so the winner
           can acquire it.
        5. Non-winners rejoin once a primary is advertised.
        """
        local_gtid = self.get_executed_gtid() or ''
        peer_gtids = []
        for m in members or []:
            if getattr(m, 'name', None) == self.name:
                continue
            g = self._member_gtid(m)
            if g:
                peer_gtids.append(g)

        # Fresh initialize often has empty gtid_executed (post_bootstrap DDL
        # runs with sql_log_bin=0). Allow lock-holder to form the first group.
        if not local_gtid:
            if has_lock and not peer_gtids:
                logger.warning("MGR initial bootstrap with empty local GTID")
                if self.bootstrap_mgr_group():
                    self.set_role(MySQLRole.MGR_PRIMARY)
                    self.set_read_write()
                    self._clear_mgr_gtid_fork()
                    return 'bootstrapped MGR group after majority loss'
                return None
            # Joiners may also have empty GTID before any local writes — still
            # rejoin if a primary is already advertised in DCS.
            rejoined = self._try_rejoin_mgr(members)
            if rejoined:
                return rejoined
            logger.warning("MGR majority loss: no local GTID available yet")
            return None

        winner = self.select_mgr_bootstrap_winner(local_gtid, members)
        logger.warning(
            "MGR majority lost (cluster_nodes=%s): local=%s winner=%s has_lock=%s",
            cluster_nodes, self.name, winner, has_lock
        )

        if winner is None:
            fork = self.describe_mgr_gtid_fork(local_gtid, members)
            if fork:
                logger.error(
                    "CRITICAL: MGR GTID fork (incomparable sets) among %s — "
                    "refusing automatic bootstrap; manual recovery required",
                    [m['name'] for m in fork]
                )
                for entry in fork:
                    logger.error("  fork member %s gtid_executed=%s",
                                 entry['name'], entry['gtid_executed'])
                self._record_mgr_gtid_fork(fork)
                try:
                    self.set_read_only()
                except Exception:
                    pass
                return 'mgr_gtid_fork'
            return None

        self._clear_mgr_gtid_fork()

        if winner != self.name:
            if has_lock:
                # Let the GTID-ahead peer take the lock and bootstrap.
                return 'mgr_yield_lock'
            rejoined = self._try_rejoin_mgr(members)
            if rejoined:
                return rejoined
            return 'waiting for MGR bootstrap winner ({0})'.format(winner)

        # We are the elected winner.
        if not has_lock:
            # Peers may have already formed a group (or our election used a
            # partial DCS member list after leases expired). Prefer joining a
            # live mgr_primary over waiting forever for the lock.
            rejoined = self._try_rejoin_mgr(members)
            if rejoined:
                return rejoined
            return 'elected MGR bootstrap winner; waiting for leader lock'

        # Guard against split-brain: if another member already advertises a
        # live MGR primary, rejoin that group and yield the lock. Stale
        # Patroni ``primary`` roles are ignored (see ``_find_mgr_primary_member``).
        existing = self._find_mgr_primary_member(members)
        if existing:
            rejoined = self._try_rejoin_mgr(members)
            if rejoined:
                logger.warning(
                    "MGR primary already advertised as %s; rejoined and yielding lock",
                    getattr(existing, 'name', existing)
                )
                return 'mgr_yield_lock'
            logger.warning(
                "Ignoring unreachable MGR primary advertisement from %s "
                "(rejoin failed); bootstrapping as GTID winner",
                getattr(existing, 'name', existing)
            )

        logger.warning("MGR majority lost — bootstrapping group as GTID winner")
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
        # Empty / None → default physical-then-logical path is always available
        # (mysqldump at minimum).
        if not create_replica_methods:
            return True
        return any(m in CreateReplicaMethod.known()
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

    def copy_logical_slots(self, cluster: Cluster, *args: Any, **kwargs: Any) -> None:
        pass

    def sync_replication_slots(self, cluster: Cluster, tags: Any = None) -> List[str]:
        # MySQL has no PG-style replication slots; match SlotsHandler signature.
        return []

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
