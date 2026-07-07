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
        try:
            row = self._query("SELECT @@server_uuid")
            return row[0][0] if row else None
        except Exception:
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
        mysqld_path = self.config.get_mysqld_path()
        proc = MySQLProcess.start(mysqld_path, self.config.config_file_path,
                                  self._data_dir)
        if proc:
            self._postmaster_process = proc
            self.set_state(MySQLState.RUNNING)
            logger.info("MySQL started successfully")
            return True
        self.set_state(MySQLState.START_FAILED)
        return False

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
               do_reload: bool = False) -> Optional[bool]:
        if node_to_follow is None:
            self._query("STOP SLAVE")
            self._query("RESET SLAVE ALL")
            return True

        conn_url = node_to_follow.conn_url
        if not conn_url:
            return False

        if role:
            self.set_role(role)

        host, port = self._parse_conn_url(conn_url)
        repl = self.config.replication
        user = repl.get('username', 'replicator')
        password = repl.get('password', '')

        try:
            self._query("STOP SLAVE")
            self._query("RESET SLAVE ALL")
            self._query(
                "CHANGE MASTER TO "
                "MASTER_HOST=%s, MASTER_PORT=%s, "
                "MASTER_USER=%s, MASTER_PASSWORD=%s, "
                "MASTER_AUTO_POSITION=1",
                host, port, user, password
            )
            self._query("START SLAVE")
            logger.info("Started replication from %s:%s", host, port)
            self._enable_semi_sync()
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
            else:
                self._query("SET GLOBAL rpl_semi_sync_replica_enabled = 1")
                logger.info("Semi-sync replication enabled as replica")
        except Exception as e:
            logger.warning("Failed to enable semi-sync replication: %r", e)

    def _disable_semi_sync(self) -> None:
        try:
            self._query("SET GLOBAL rpl_semi_sync_source_enabled = 0")
            logger.info("Semi-sync replication disabled")
        except Exception:
            pass

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
        return None

    def replica_cached_timeline(self, leader_timeline: Optional[int]) -> Optional[int]:
        return None

    def pg_control_timeline(self) -> Optional[int]:
        return None

    def get_primary_timeline(self) -> Optional[int]:
        return None

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

    def reset_cluster_info_state(self, state: Optional[str]) -> None:
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
