import logging
import os
import shutil

from typing import Any, Dict, List, Optional, Tuple, Union

from ..dcs import Leader, Member, RemoteMember
from ..utils import parse_int, split_host_port, uri

logger = logging.getLogger(__name__)


class ConfigHandler:
    """Manages MySQL configuration files."""

    def __init__(self, config: Dict[str, Any]):
        self._config = config
        self._data_dir: str = config['data_dir']
        self._config_dir: str = config.get('config_dir', self._data_dir)
        self._my_cnf: str = os.path.join(self._config_dir, 'my.cnf')
        self._bin_dir: str = config.get('bin_dir') or ''
        self._listen: str = config.get('listen', '127.0.0.1:3306')
        self._connect_address: str = config.get('connect_address', self._listen)
        self._server_id: int = config.get('server_id', 1)
        self._port: int = config.get('port', 3306)
        self._parameters: Dict[str, Any] = config.get('parameters', {})
        self._authentication: Dict[str, Any] = config.get('authentication', {})

    def get(self, key: str, default: Any = None) -> Any:
        """Dict-like access for Rewind/HA helpers that expect Postgresql.config.get."""
        if key in self._config:
            return self._config[key]
        return self._parameters.get(key, default)

    @property
    def data_dir(self) -> str:
        return self._data_dir

    @property
    def bin_dir(self) -> str:
        return self._bin_dir

    @property
    def config_dir(self) -> str:
        return self._config_dir

    @property
    def config_file_path(self) -> str:
        return self._my_cnf

    @property
    def listen(self) -> str:
        return self._listen

    @property
    def connect_address(self) -> str:
        return self._connect_address

    @property
    def port(self) -> int:
        return self._port

    @property
    def server_id(self) -> int:
        return self._server_id

    @property
    def parameters(self) -> Dict[str, Any]:
        return self._parameters

    @property
    def replication(self) -> Dict[str, str]:
        return self._authentication.get('replication', {})

    @property
    def superuser(self) -> Dict[str, str]:
        return self._authentication.get('superuser', {})

    @property
    def create_replica_methods(self) -> List[str]:
        return self._config.get('create_replica_methods', ['mysqldump'])

    @property
    def synchronous_standby_names(self) -> str:
        """MySQL has no PostgreSQL-style synchronous_standby_names."""
        return ''

    def set_synchronous_standby_names(self, value: Optional[str]) -> Optional[bool]:
        """No-op for MySQL (no synchronous_standby_names GUC)."""
        return None

    def get_mysqld_path(self) -> str:
        return os.path.join(self._bin_dir, 'mysqld') if self._bin_dir else 'mysqld'

    def get_mysqladmin_path(self) -> str:
        return os.path.join(self._bin_dir, 'mysqladmin') if self._bin_dir else 'mysqladmin'

    def get_mysql_path(self) -> str:
        return os.path.join(self._bin_dir, 'mysql') if self._bin_dir else 'mysql'

    def get_mysqldump_path(self) -> str:
        return os.path.join(self._bin_dir, 'mysqldump') if self._bin_dir else 'mysqldump'

    def get_xtrabackup_path(self) -> str:
        """Resolve xtrabackup binary (often outside MySQL ``bin_dir``)."""
        if self._bin_dir:
            candidate = os.path.join(self._bin_dir, 'xtrabackup')
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        found = shutil.which('xtrabackup')
        return found or '/usr/bin/xtrabackup'

    def get_xbstream_path(self) -> str:
        if self._bin_dir:
            candidate = os.path.join(self._bin_dir, 'xbstream')
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        found = shutil.which('xbstream')
        return found or '/usr/bin/xbstream'

    def write_my_cnf(self, config_override: Optional[Dict[str, Any]] = None) -> None:
        """Write my.cnf configuration file."""
        params = dict(self._parameters)
        if config_override:
            params.update(config_override)

        params.setdefault('server_id', str(self._server_id))
        params.setdefault('port', str(self._port))
        params.setdefault('mysqlx', 'OFF')  # disable X Plugin (port 33060) for multi-instance
        params.setdefault('datadir', self._data_dir)
        params.setdefault('socket', self._socket_path())
        params.setdefault('log-error', os.path.join(self._data_dir, f'{self._hostname()}.err'))
        params.setdefault('pid-file', os.path.join(self._data_dir, 'mysqld.pid'))

        # Collect plugins to load (merged into one plugin-load-add line)
        plugins: List[str] = []
        existing_plugins = str(params.get('plugin-load-add') or '')
        if existing_plugins:
            plugins.extend(p for p in existing_plugins.replace(',', ';').split(';') if p)

        # MGR defaults — ensure required parameters are set when MGR is configured
        if params.get('group_replication_group_name'):
            gr_host = self._listen.split(':')[0] if ':' in self._listen else self._listen
            if 'group_replication.so' not in plugins:
                plugins.append('group_replication.so')
            params.setdefault('loose-group_replication_start_on_boot', 'OFF')
            params.setdefault('loose-group_replication_bootstrap_group', 'OFF')
            params.setdefault('loose-group_replication_single_primary_mode', 'ON')
            params.setdefault('loose-group_replication_local_address',
                              f'{gr_host}:{self._get_mgr_port()}')
            params.setdefault('loose-group_replication_group_seeds',
                              params.get('loose-group_replication_group_seeds',
                                         f'{gr_host}:{self._get_mgr_port()}'))
            # Loopback-only allowlist for local multi-instance tests / single host.
            params.setdefault('loose-group_replication_ip_allowlist',
                              '127.0.0.1/32,::1/128')
            params.setdefault('loose-binlog_transaction_dependency_tracking', 'WRITESET')
            params.setdefault('loose-group_replication_recovery_use_ssl', 'OFF')
            params.setdefault('report_host', gr_host)
            params.setdefault('report_port', str(self._port))

        # Semi-sync plugins — name depends on MySQL version (5.7 master/slave vs 8.0.26+ source/replica)
        if any(params.get(k) for k in (
                'rpl_semi_sync_source_enabled', 'rpl_semi_sync_replica_enabled',
                'rpl_semi_sync_master_enabled', 'rpl_semi_sync_slave_enabled')):
            if (params.get('rpl_semi_sync_source_enabled') is not None
                    or params.get('rpl_semi_sync_replica_enabled') is not None):
                plugin_pair = ('semisync_source.so', 'semisync_replica.so')
            else:
                plugin_pair = ('semisync_master.so', 'semisync_slave.so')
            for p in plugin_pair:
                if p not in plugins:
                    plugins.append(p)

        if plugins:
            params['plugin-load-add'] = ';'.join(plugins)

        # plugin-load* MUST appear before plugin-owned variables, otherwise
        # mysqld treats them as unknown (e.g. rpl_semi_sync_*) and aborts.
        lines = ['[mysqld]']
        skip_keys = {'cluster_size', 'mgr_pause_on_gtid_fork'}
        if 'plugin-load-add' in params:
            lines.append(f"plugin-load-add = {params['plugin-load-add']}")
            skip_keys.add('plugin-load-add')
        if 'plugin-load' in params:
            lines.append(f"plugin-load = {params['plugin-load']}")
            skip_keys.add('plugin-load')

        for key, value in params.items():
            # Patroni-only hints — never write into my.cnf
            if key in skip_keys:
                continue
            lines.append(f'{key} = {value}')
        lines.append('')

        os.makedirs(self._config_dir, exist_ok=True)
        with open(self._my_cnf, 'w') as f:
            f.write('\n'.join(lines))

    def recovery_conf_exists(self) -> bool:
        """Check if replication config exists (relay-log, master info)."""
        relay_log = self._parameters.get('relay-log',
                                         os.path.join(self._data_dir, 'relay-bin'))
        relay_log_index = relay_log + '.index' if not relay_log.endswith('.index') else relay_log
        master_info = os.path.join(self._data_dir, 'master.info')
        return os.path.exists(relay_log_index) or os.path.exists(master_info)

    def check_recovery_conf(self, node_to_follow: Union[Leader, Member, RemoteMember, None]) \
            -> Tuple[bool, bool]:
        """Return ``(change_required, restart_required)`` for replication config.

        MySQL replication is reconfigured via ``CHANGE MASTER TO`` without a
        server restart. ``MySQL.follow()`` is idempotent, so we always request a
        soft reconfigure (no restart) and let follow decide whether work is needed.
        """
        return True, False

    def _socket_path(self) -> str:
        return os.path.join(self._data_dir, 'mysql.sock')

    def _get_mgr_port(self) -> int:
        """Get the MGR communication port (default: mysql_port + 10).

        Older formula ``port * 10 + 1`` overflows TCP port range for
        5-digit mysql ports (e.g. 34407 → 344071).
        """
        base_port = self._port or 3306
        return base_port + 10

    @staticmethod
    def _hostname() -> str:
        import socket
        return socket.gethostname()

    def write_replication_config(self, primary_conn_info: Dict[str, Any]) -> None:
        """Write replication configuration (CHANGE MASTER TO)."""
        change_master = (
            f"CHANGE MASTER TO\n"
            f"  MASTER_HOST='{primary_conn_info['host']}',\n"
            f"  MASTER_PORT={primary_conn_info['port']},\n"
            f"  MASTER_USER='{primary_conn_info.get('user', 'replicator')}',\n"
            f"  MASTER_PASSWORD='{primary_conn_info.get('password', '')}',\n"
            f"  MASTER_AUTO_POSITION=1"
        )
        log_file = primary_conn_info.get('log_file')
        log_pos = primary_conn_info.get('log_pos')
        if log_file and log_pos is not None:
            change_master += f",\n  MASTER_LOG_FILE='{log_file}',\n  MASTER_LOG_POS={log_pos}"
        logger.info("Replication config: %s", change_master)
