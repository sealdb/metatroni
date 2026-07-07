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

    def get_mysqld_path(self) -> str:
        return os.path.join(self._bin_dir, 'mysqld') if self._bin_dir else 'mysqld'

    def get_mysqladmin_path(self) -> str:
        return os.path.join(self._bin_dir, 'mysqladmin') if self._bin_dir else 'mysqladmin'

    def get_mysql_path(self) -> str:
        return os.path.join(self._bin_dir, 'mysql') if self._bin_dir else 'mysql'

    def get_mysqldump_path(self) -> str:
        return os.path.join(self._bin_dir, 'mysqldump') if self._bin_dir else 'mysqldump'

    def get_xtrabackup_path(self) -> str:
        return os.path.join(self._bin_dir, 'xtrabackup') if self._bin_dir else '/usr/bin/xtrabackup'

    def get_xbstream_path(self) -> str:
        return os.path.join(self._bin_dir, 'xbstream') if self._bin_dir else '/usr/bin/xbstream'

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

        lines = ['[mysqld]']
        for key, value in params.items():
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
        if node_to_follow is None:
            return True, True
        return True, True

    def _socket_path(self) -> str:
        return os.path.join(self._data_dir, 'mysql.sock')

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
