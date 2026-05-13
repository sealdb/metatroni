import logging
import os
import subprocess

from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from ..dcs import Leader, Member, RemoteMember

logger = logging.getLogger(__name__)


class Bootstrap:

    def __init__(self, config_handler: 'ConfigHandler',  # noqa: F821
                 postmaster: Callable[[], Any],
                 query_func: Callable):
        self._config_handler = config_handler
        self._postmaster = postmaster
        self._query = query_func

    def initialize(self) -> bool:
        mysqld_path = self._config_handler.get_mysqld_path()
        data_dir = self._config_handler.data_dir

        if os.path.exists(data_dir) and os.listdir(data_dir):
            logger.info("Data directory %s already exists", data_dir)
            return True

        logger.info("Initializing MySQL data directory: %s", data_dir)
        cmdline = [mysqld_path, f'--datadir={data_dir}',
                   '--initialize-insecure',
                   f'--user={os.getenv("USER", "root")}']
        try:
            result = subprocess.run(cmdline, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                logger.error("MySQL init failed: %s", result.stderr)
                return False
            logger.info("MySQL data directory initialized")
            return True
        except subprocess.TimeoutExpired:
            logger.error("MySQL init timed out")
            return False
        except OSError as e:
            logger.error("Failed to run mysqld --initialize: %r", e)
            return False

    def _start_mysql(self) -> bool:
        from .postmaster import MySQLProcess
        mysqld_path = self._config_handler.get_mysqld_path()
        data_dir = self._config_handler.data_dir
        self._config_handler.write_my_cnf()
        proc = MySQLProcess.start(mysqld_path, self._config_handler.config_file_path, data_dir)
        if not proc:
            return False
        sock = os.path.join(data_dir, 'mysql.sock')
        if not proc.wait_for_ready(sock, 30):
            logger.error("MySQL started but not ready after 30s")
            proc.signal_kill()
            return False
        return True

    def bootstrap(self, config: Dict[str, Any]) -> bool:
        if not self.initialize():
            return False
        return self._start_mysql()

    def clone(self, clone_member: Union[Leader, Member, None],
              clone_from_leader: bool = False) -> bool:
        return self.create_replica(clone_member)

    def create_replica(self, clone_member: Any) -> bool:
        import shutil
        from .postmaster import MySQLProcess

        conn_url = None
        if isinstance(clone_member, (Leader, Member, RemoteMember)):
            conn_url = clone_member.conn_url
        if not conn_url:
            logger.error("No connection URL for clone source")
            return False

        logger.info("Creating replica from %s", conn_url)
        data_dir = self._config_handler.data_dir

        if os.path.exists(data_dir):
            shutil.rmtree(data_dir)

        if not self.initialize():
            return False

        self._config_handler.write_my_cnf()
        mysqld_path = self._config_handler.get_mysqld_path()
        proc = MySQLProcess.start(mysqld_path, self._config_handler.config_file_path, data_dir)
        if not proc:
            logger.error("Failed to start MySQL for cloning")
            return False

        host, port = self._parse_conn_url(conn_url)
        repl = self._config_handler.replication
        user = repl.get('username', 'replicator')
        password = repl.get('password', '')

        dump_args = [f'-h{host}', f'-P{port}', f'-u{user}']
        if password:
            dump_args.append(f'-p{password}')

        dump_file = os.path.join(data_dir, 'clone.sql')
        mysql_path = self._config_handler.get_mysql_path()
        mysqldump_path = self._config_handler.get_mysqldump_path()
        user_dbs_cmd = [mysql_path] + dump_args + [
            '-Ns', '-e',
            "SELECT GROUP_CONCAT(schema_name SEPARATOR ' ') FROM information_schema.schemata "
            "WHERE schema_name NOT IN ('mysql','sys','performance_schema','information_schema','tmp')"
        ]
        try:
            user_dbs = subprocess.run(user_dbs_cmd, capture_output=True, text=True,
                                      timeout=30, check=True).stdout.strip()
        except Exception as e:
            logger.error("Failed to get user databases: %r", e)
            proc.signal_kill()
            return False

        if not user_dbs:
            logger.info("No user databases to clone, skipping dump")
            proc.signal_kill()
            return True
        else:
            logger.info("Cloning databases: %s", user_dbs)
            dump_cmd = [mysqldump_path] + dump_args + [
                '--source-data=2', '--databases'
            ] + user_dbs.split() + [
                '--triggers', '--routines', '--skip-events',
                '--set-gtid-purged=ON', '--no-tablespaces',
            ]

        logger.info("Dumping data from source...")
        try:
            with open(dump_file, 'wb') as f:
                result = subprocess.run(dump_cmd, stdout=f, stderr=subprocess.PIPE,
                                        timeout=3600)
                if result.returncode != 0:
                    dump_err = result.stderr.decode() if result.stderr else ''
                    logger.error("Dump failed (rc=%s): %s", result.returncode, dump_err)
                    proc.signal_kill()
                    return False
                if result.stderr:
                    stderr_text = result.stderr.decode().strip()
                    for line in stderr_text.split('\n'):
                        logger.warning("Dump: %s", line)
        except subprocess.TimeoutExpired:
            logger.error("Dump timed out")
            proc.signal_kill()
            return False
        except OSError as e:
            logger.error("Dump failed: %r", e)
            proc.signal_kill()
            return False

        if os.path.getsize(dump_file) == 0:
            logger.error("Dump file is empty")
            proc.signal_kill()
            return False

        logger.info("Restoring data locally...")
        sock = os.path.join(data_dir, 'mysql.sock')
        if not proc.wait_for_ready(sock, 30):
            logger.error("MySQL not ready after 30s")
            proc.signal_kill()
            return False

        restore_cmd = [mysql_path, '-S', sock, '-u', 'root']
        try:
            with open(dump_file, 'rb') as f:
                result = subprocess.run(restore_cmd, stdin=f, stderr=subprocess.PIPE,
                                        timeout=3600)
                if result.returncode != 0:
                    logger.error("Restore failed (rc=%s): %s",
                                 result.returncode, result.stderr.decode() if result.stderr else '')
                    proc.signal_kill()
                    return False
        except subprocess.TimeoutExpired:
            logger.error("Restore timed out")
            proc.signal_kill()
            return False
        except OSError as e:
            logger.error("Restore failed: %r", e)
            proc.signal_kill()
            return False

        os.remove(dump_file)
        logger.info("Replica created successfully from %s", conn_url)
        return True

    def post_bootstrap(self, config: Dict[str, Any] = None,
                       task: Any = None) -> Optional[bool]:
        try:
            repl_user = (config or {}).get('replication_user', {}) if config else {}
            user = repl_user.get('username', 'replicator')
            password = repl_user.get('password', '')
            ident = f" IDENTIFIED BY '{password}'" if password else " IDENTIFIED BY ''"
            self._query(f"CREATE USER IF NOT EXISTS '{user}'@'%%'{ident}")
            self._query(f"GRANT REPLICATION SLAVE, REPLICATION CLIENT ON *.* TO '{user}'@'%%'")
            self._query("FLUSH PRIVILEGES")
            logger.info("Post-bootstrap tasks completed")
            if task:
                task.complete(True)
            return True
        except Exception as e:
            logger.error("Post-bootstrap failed: %r", e)
            if task:
                task.complete(False)
            return False

    @staticmethod
    def _parse_conn_url(conn_url: str) -> Tuple[str, int]:
        from urllib.parse import urlparse
        r = urlparse(conn_url)
        host = r.hostname or '127.0.0.1'
        port = r.port or 3306
        return host, port
