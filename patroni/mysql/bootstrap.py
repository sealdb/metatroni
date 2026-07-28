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
                   '--skip-networking',
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
        """Create a replica using the configured clone method.

        Checks ``create_replica_methods`` config; falls back to mysqldump
        if no methods are configured.
        """
        conn_url = None
        if isinstance(clone_member, (Leader, Member, RemoteMember)):
            conn_url = clone_member.conn_url
        if not conn_url:
            logger.error("No connection URL for clone source")
            return False

        # Determine which method(s) to use
        replica_methods = getattr(self._config_handler, 'create_replica_methods', None)
        if replica_methods is None:
            replica_methods = ['mysqldump']

        for method in replica_methods:
            logger.info("Creating replica from %s using method=%s", conn_url, method)
            if method == 'mysqldump':
                if self._create_replica_via_mysqldump(conn_url):
                    return True
            elif method == 'xtrabackup':
                if self._create_replica_via_xtrabackup(conn_url):
                    return True
            else:
                logger.warning("Unknown create_replica_method: %s", method)
            logger.error("Method %s failed, trying next if available", method)

        return False

    @staticmethod
    def _rmtree_quiet(path: Optional[str]) -> None:
        import shutil
        if path and os.path.exists(path):
            try:
                shutil.rmtree(path)
            except OSError as e:
                logger.warning("Failed to remove %s: %r", path, e)

    @staticmethod
    def _unlink_quiet(path: Optional[str]) -> None:
        if path and os.path.exists(path):
            try:
                os.remove(path)
            except OSError as e:
                logger.warning("Failed to remove %s: %r", path, e)

    def _create_replica_via_mysqldump(self, conn_url: str) -> bool:
        """Clone a replica using mysqldump (logical backup)."""
        from .postmaster import MySQLProcess

        logger.info("Creating replica from %s via mysqldump", conn_url)
        data_dir = self._config_handler.data_dir
        dump_file = os.path.join(data_dir, 'clone.sql')
        proc = None

        try:
            if os.path.exists(data_dir):
                self._rmtree_quiet(data_dir)

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
                return False

            # mysql -N prints the word NULL when GROUP_CONCAT has no rows.
            if not user_dbs or user_dbs.upper() == 'NULL':
                logger.info("No user databases to clone, skipping dump")
                if not self.ensure_replication_user():
                    return False
                # Leave mysqld running for the caller (empty clone still valid).
                proc = None
                return True

            logger.info("Cloning databases: %s", user_dbs)
            dump_cmd = [mysqldump_path] + dump_args + [
                '--single-transaction', '--source-data=2', '--databases'
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
                        return False
                    if result.stderr:
                        stderr_text = result.stderr.decode().strip()
                        for line in stderr_text.split('\n'):
                            logger.warning("Dump: %s", line)
            except subprocess.TimeoutExpired as e:
                logger.error("Dump timed out")
                # Ensure orphaned mysqldump is gone (Python kills the Popen, but be explicit).
                if e.process:
                    try:
                        e.process.kill()
                    except Exception:
                        pass
                return False
            except OSError as e:
                logger.error("Dump failed: %r", e)
                return False

            if not os.path.exists(dump_file) or os.path.getsize(dump_file) == 0:
                logger.error("Dump file is empty")
                return False

            logger.info("Restoring data locally...")
            sock = os.path.join(data_dir, 'mysql.sock')
            if not proc.wait_for_ready(sock, 30):
                logger.error("MySQL not ready after 30s")
                return False

            restore_cmd = [mysql_path, '-S', sock, '-u', 'root']
            try:
                with open(dump_file, 'rb') as f:
                    result = subprocess.run(restore_cmd, stdin=f, stderr=subprocess.PIPE,
                                            timeout=3600)
                    if result.returncode != 0:
                        logger.error("Restore failed (rc=%s): %s",
                                     result.returncode,
                                     result.stderr.decode() if result.stderr else '')
                        return False
            except subprocess.TimeoutExpired as e:
                logger.error("Restore timed out")
                if e.process:
                    try:
                        e.process.kill()
                    except Exception:
                        pass
                return False
            except OSError as e:
                logger.error("Restore failed: %r", e)
                return False

            self._unlink_quiet(dump_file)

            # mysqldump only restores user databases — system accounts are not
            # copied. Ensure the replication user exists so this node can later
            # become primary and accept replicas.
            if not self.ensure_replication_user():
                return False

            logger.info("Replica created successfully from %s via mysqldump", conn_url)
            proc = None  # success: leave mysqld running
            return True
        finally:
            self._unlink_quiet(dump_file if os.path.isdir(data_dir) else None)
            if proc is not None:
                try:
                    proc.signal_kill()
                except Exception:
                    pass
                # Failed clone: drop half-baked datadir so the next method starts clean.
                self._rmtree_quiet(data_dir)

    def _create_replica_via_xtrabackup(self, conn_url: str) -> bool:
        """Clone a replica using xtrabackup (physical backup).

        Uses ``xtrabackup --backup`` to create a physical snapshot,
        ``xtrabackup --prepare`` to make it consistent, then copies
        the prepared data into the data directory.
        """
        import shutil

        logger.info("Creating replica from %s via xtrabackup", conn_url)
        data_dir = self._config_handler.data_dir
        host, port = self._parse_conn_url(conn_url)

        repl = self._config_handler.replication
        user = repl.get('username', 'replicator')
        password = repl.get('password', '')

        xtrabackup_path = self._config_handler.get_xtrabackup_path()
        tmp_backup_dir = data_dir + '.xtrabackup_tmp'
        success = False

        try:
            # Clean up any stale temp / target data
            self._rmtree_quiet(tmp_backup_dir)
            self._rmtree_quiet(data_dir)
            os.makedirs(tmp_backup_dir)

            # Phase 1: xtrabackup --backup to temp directory
            backup_args = [
                xtrabackup_path, '--backup',
                '--host=' + host, '--port=' + str(port),
                '--user=' + user,
                '--target-dir=' + tmp_backup_dir,
            ]
            if password:
                backup_args.append('--password=' + password)

            logger.info("Running xtrabackup --backup to %s ...", tmp_backup_dir)
            try:
                result = subprocess.run(backup_args, capture_output=True, timeout=7200)
                if result.returncode != 0:
                    stderr_text = result.stderr.decode(errors='replace') if result.stderr else ''
                    logger.error("xtrabackup --backup failed (rc=%s): %s",
                                 result.returncode, stderr_text[:500])
                    return False
                if result.stderr:
                    for line in result.stderr.decode(errors='replace').strip().split('\n'):
                        logger.info("xtrabackup: %s", line)
            except subprocess.TimeoutExpired as e:
                logger.error("xtrabackup --backup timed out")
                if e.process:
                    try:
                        e.process.kill()
                    except Exception:
                        pass
                return False
            except OSError as e:
                logger.error("xtrabackup --backup failed: %r", e)
                return False

            # Phase 2: xtrabackup --prepare (apply redo logs)
            prepare_args = [
                xtrabackup_path, '--prepare',
                '--target-dir=' + tmp_backup_dir,
            ]
            logger.info("Running xtrabackup --prepare ...")
            try:
                result = subprocess.run(prepare_args, capture_output=True, timeout=3600)
                if result.returncode != 0:
                    stderr_text = result.stderr.decode(errors='replace') if result.stderr else ''
                    logger.error("xtrabackup --prepare failed (rc=%s): %s",
                                 result.returncode, stderr_text[:500])
                    return False
                if result.stderr:
                    for line in result.stderr.decode(errors='replace').strip().split('\n'):
                        logger.info("xtrabackup: %s", line)
            except subprocess.TimeoutExpired as e:
                logger.error("xtrabackup --prepare timed out")
                if e.process:
                    try:
                        e.process.kill()
                    except Exception:
                        pass
                return False
            except OSError as e:
                logger.error("xtrabackup --prepare failed: %r", e)
                return False

            # Phase 3: Move prepared data to data_dir; drop donor UUID
            logger.info("Moving prepared backup to %s", data_dir)
            os.makedirs(data_dir, exist_ok=True)
            try:
                for item in os.listdir(tmp_backup_dir):
                    src = os.path.join(tmp_backup_dir, item)
                    dst = os.path.join(data_dir, item)
                    shutil.move(src, dst)
            except OSError as e:
                logger.error("Failed to move backup data: %r", e)
                return False

            # Physical backup copies auto.cnf (server_uuid). Generate a fresh one.
            self._unlink_quiet(os.path.join(data_dir, 'auto.cnf'))

            # Phase 4: Write my.cnf and start MySQL
            self._config_handler.write_my_cnf()
            logger.info("Starting MySQL on restored data ...")
            if not self._start_mysql():
                logger.error("MySQL failed to start after xtrabackup restore")
                return False

            logger.info("Replica created successfully from %s via xtrabackup", conn_url)
            success = True
            return True
        finally:
            self._rmtree_quiet(tmp_backup_dir)
            if not success:
                self._rmtree_quiet(data_dir)

    def ensure_replication_user(self, repl_user: Optional[Dict[str, Any]] = None) -> bool:
        """Create the replication user from config if it does not exist.

        Runs with ``sql_log_bin=0`` so the account DDL stays local and does not
        pollute GTIDs / get re-applied on rejoining nodes.

        Grants include privileges needed both for streaming replication and for
        logical cloning via mysqldump from this node after it becomes primary.
        """
        try:
            if not repl_user:
                repl_user = self._config_handler.replication or {}
            user = repl_user.get('username', 'replicator')
            password = repl_user.get('password', '')
            # Keep account management off the binlog: it is node-local setup,
            # and replaying CREATE/ALTER USER on a rejoining primary is harmful.
            self._query("SET sql_log_bin=0")
            try:
                # Parameterized so '%' is a real host pattern (not literal '%%').
                # ALTER so a pre-existing account always gets the configured password.
                # Use mysql_native_password: group_replication_recovery rejects
                # GET_MASTER_PUBLIC_KEY (ER 3139), and caching_sha2_password then
                # requires TLS for donor auth during distributed recovery.
                self._query(
                    "CREATE USER IF NOT EXISTS %s@%s "
                    "IDENTIFIED WITH mysql_native_password BY %s",
                    user, '%', password
                )
                self._query(
                    "ALTER USER %s@%s "
                    "IDENTIFIED WITH mysql_native_password BY %s",
                    user, '%', password
                )
                self._query(
                    "GRANT REPLICATION SLAVE, REPLICATION CLIENT, "
                    "SELECT, RELOAD, LOCK TABLES, PROCESS, BACKUP_ADMIN "
                    "ON *.* TO %s@%s",
                    user, '%'
                )
                # Group Replication recovery / admin privileges (MySQL 8.0+).
                for extra in (
                    "GRANT CONNECTION_ADMIN ON *.* TO %s@%s",
                    "GRANT GROUP_REPLICATION_STREAM ON *.* TO %s@%s",
                    "GRANT GROUP_REPLICATION_ADMIN ON *.* TO %s@%s",
                ):
                    try:
                        self._query(extra, user, '%')
                    except Exception:
                        pass
                # Needed by xtrabackup for consistent backup coordinates.
                try:
                    self._query(
                        "GRANT SELECT ON performance_schema.log_status TO %s@%s",
                        user, '%'
                    )
                except Exception:
                    pass
                self._query("FLUSH PRIVILEGES")
            finally:
                self._query("SET sql_log_bin=1")
            logger.info("Replication user '%s' ensured", user)
            return True
        except Exception as e:
            logger.error("Failed to ensure replication user: %r", e)
            try:
                self._query("SET sql_log_bin=1")
            except Exception:
                pass
            return False

    def post_bootstrap(self, config: Dict[str, Any] = None,
                       task: Any = None) -> Optional[bool]:
        try:
            # Prefer bootstrap.replication_user when provided by ha.py; otherwise
            # fall back to mysql.authentication.replication from ConfigHandler.
            repl_user = None
            if config:
                repl_user = (config.get('replication_user')
                             or (config.get('users') or {}).get('replicator'))
            ok = self.ensure_replication_user(repl_user)
            if ok:
                logger.info("Post-bootstrap tasks completed")
            if task:
                task.complete(ok)
            return ok
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
