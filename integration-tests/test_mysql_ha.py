#!/usr/bin/env python3
"""Patroni MySQL HA Integration Test.

End-to-end validation of MySQL high-availability managed by Patroni's MySQL backend.

Phases:
  1. Bootstrap a primary node
  2. Create replication user and test data
  3. Clone a replica from the primary (mysqldump)
  4. Configure GTID-based replication
  5. Verify data replication
  6. Promote replica to primary
  7. Demote and re-follow

Configuration (priority: CLI args > env vars > defaults):

  --mysql-base    Path to MySQL installation          MYSQL_BASE           /usr/local/mysql
  --test-dir      Working directory for test data     MYSQL_TEST_DIR       /tmp/patroni_mysql_ha_test
  --p0-port       Primary node TCP port               MYSQL_P0_PORT        33907
  --p1-port       Replica node TCP port               MYSQL_P1_PORT        33908
  --timeout       Operation timeout in seconds        MYSQL_TIMEOUT        60
  --keep-data     Keep test data on failure           MYSQL_KEEP_DATA      0

Examples:

  MYSQL_BASE=/usr/local/mysql python integration-tests/test_mysql_ha.py
  python integration-tests/test_mysql_ha.py --mysql-base /opt/mysql --p0-port 33061
  MYSQL_KEEP_DATA=1 python integration-tests/test_mysql_ha.py  # preserve data on failure
"""

import argparse
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
import traceback

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger('mysql_ha_test')


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description='Patroni MySQL HA Integration Test')
    p.add_argument('--mysql-base', default=os.environ.get('MYSQL_BASE', '/usr/local/mysql'),
                   help='Path to MySQL installation (env: MYSQL_BASE)')
    p.add_argument('--test-dir', default=os.environ.get('MYSQL_TEST_DIR', '/tmp/patroni_mysql_ha_test'),
                   help='Working directory for test data (env: MYSQL_TEST_DIR)')
    p.add_argument('--p0-port', type=int, default=int(os.environ.get('MYSQL_P0_PORT', 33907)),
                   help='Primary TCP port (env: MYSQL_P0_PORT)')
    p.add_argument('--p1-port', type=int, default=int(os.environ.get('MYSQL_P1_PORT', 33908)),
                   help='Replica TCP port (env: MYSQL_P1_PORT)')
    p.add_argument('--timeout', type=int, default=int(os.environ.get('MYSQL_TIMEOUT', 60)),
                   help='Operation timeout in seconds (env: MYSQL_TIMEOUT)')
    p.add_argument('--keep-data', action='store_true', default=bool(int(os.environ.get('MYSQL_KEEP_DATA', '0'))),
                   help='Keep test data on failure (env: MYSQL_KEEP_DATA)')
    return p.parse_args()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _is_port_free(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False


def _kill_port(port: int) -> None:
    """Kill any process listening on *port*. Works on Linux (fuser/lsof/ss) and WSL."""
    pids: set = set()

    # Method 1: fuser
    try:
        out = subprocess.check_output(['fuser', f'{port}/tcp'], stderr=subprocess.STDOUT, timeout=5).decode()
        for pid_str in out.strip().split():
            pids.add(int(pid_str))
    except Exception:
        pass

    # Method 2: lsof
    if not pids:
        try:
            out = subprocess.check_output(['lsof', '-ti', f':{port}'], stderr=subprocess.STDOUT, timeout=5).decode()
            for pid_str in out.strip().split():
                pids.add(int(pid_str))
        except Exception:
            pass

    # Method 3: ss + awk (WSL fallback)
    if not pids:
        try:
            out = subprocess.check_output(
                f"ss -tlnp 'sport = :{port}' | awk '/pid=/{{match($0,/pid=([0-9]+)/,a); print a[1]}}'",
                shell=True, stderr=subprocess.STDOUT, timeout=5).decode()
            for pid_str in out.strip().split():
                pids.add(int(pid_str))
        except Exception:
            pass

    # Method 4: brute-force — kill any mysqld under the test data directory
    try:
        out = subprocess.check_output(
            ['pgrep', '-f', 'mysqld.*patroni_mysql_ha_test'], stderr=subprocess.STDOUT, timeout=5).decode()
        for pid_str in out.strip().split():
            pids.add(int(pid_str))
    except Exception:
        pass

    my_pid = os.getpid()
    for pid in pids:
        if pid == my_pid:
            continue  # don't kill ourselves
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            pass


def _kill_pidfile(pid_file: str) -> None:
    if os.path.exists(pid_file):
        try:
            with open(pid_file) as f:
                os.kill(int(f.read().strip()), signal.SIGKILL)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Config factory
# ---------------------------------------------------------------------------
def make_config(name: str, data_dir: str, port: int, server_id: int,
                mysql_base: str) -> dict:
    return {
        'name': name,
        'scope': 'mysql-ha-test',
        'data_dir': data_dir,
        'config_dir': data_dir,
        'listen': f'127.0.0.1:{port}',
        'connect_address': f'127.0.0.1:{port}',
        'port': port,
        'server_id': server_id,
        'bin_dir': f'{mysql_base}/bin',
        'authentication': {
            'superuser': {'username': 'root', 'password': ''},
            'replication': {'username': 'replicator', 'password': 'rep-pass'},
        },
        'parameters': {
            'server_id': str(server_id),
            'gtid_mode': 'ON',
            'enforce_gtid_consistency': 'ON',
            'log-bin': 'mysql-bin',
            'log_slave_updates': 'ON',
            'mysqlx': 'OFF',
            'binlog_format': 'ROW',
        },
    }


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------
class MySQLHATest:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.mysql_base = args.mysql_base
        self.test_dir = args.test_dir
        self.p0_port = args.p0_port
        self.p1_port = args.p1_port
        self.timeout = args.timeout
        self.keep_data = args.keep_data

        self.p0_data = os.path.join(self.test_dir, 'p0')
        self.p1_data = os.path.join(self.test_dir, 'p1')

        self.passed = 0
        self.failed = 0

        # Lazy imports after PATH is set
        self.MySQL = None
        self.Member = None

    # ---- lifecycle ----

    def setup(self) -> bool:
        """Validate environment and prepare test directories."""
        # Validate MySQL installation
        if not os.path.isdir(self.mysql_base):
            logger.error("MySQL base directory not found: %s", self.mysql_base)
            return False
        if not os.path.isfile(os.path.join(self.mysql_base, 'bin', 'mysqld')):
            logger.error("mysqld not found at %s/bin/mysqld", self.mysql_base)
            return False

        # Add to PATH
        os.environ['PATH'] = f"{self.mysql_base}/bin:{os.environ.get('PATH', '')}"

        # Lazy import after PATH setup
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
        from patroni.mysql import MySQL
        from patroni.dcs import Member
        self.MySQL = MySQL
        self.Member = Member

        # Check pymysql
        try:
            import pymysql  # noqa: F401
        except ImportError:
            logger.error("pymysql is not installed. Run: pip install pymysql")
            return False

        # Check ports
        for port, name in [(self.p0_port, 'p0'), (self.p1_port, 'p1')]:
            if not _is_port_free(port):
                logger.warning("Port %d (%s) is in use, attempting to free it...", port, name)
                _kill_port(port)
                time.sleep(1)
                if not _is_port_free(port):
                    logger.error("Port %d is still in use", port)
                    return False

        # Print config
        logger.info("=== Configuration ===")
        logger.info("  mysql_base: %s", self.mysql_base)
        logger.info("  test_dir:   %s", self.test_dir)
        logger.info("  p0_port:    %d", self.p0_port)
        logger.info("  p1_port:    %d", self.p1_port)
        logger.info("  timeout:    %ds", self.timeout)
        logger.info("  keep_data:  %s", self.keep_data)

        # Clean up old data
        self._clean()
        os.makedirs(self.p0_data, exist_ok=True)
        os.makedirs(self.p1_data, exist_ok=True)
        return True

    def teardown(self) -> None:
        self._clean()

    def _clean(self) -> None:
        for pid_file, data_dir in [
            (os.path.join(self.p0_data, 'mysqld.pid'), self.p0_data),
            (os.path.join(self.p1_data, 'mysqld.pid'), self.p1_data),
        ]:
            _kill_pidfile(pid_file)
        _kill_port(self.p0_port)
        _kill_port(self.p1_port)
        time.sleep(0.5)
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    # ---- assertion helper ----

    def check(self, label: str, condition: bool, detail: str = '') -> None:
        if condition:
            logger.info("  PASS  %s", label)
            self.passed += 1
        else:
            logger.error("  FAIL  %s%s", label, f'  ({detail})' if detail else '')
            self.failed += 1
            if self.failed >= 3 and not self.keep_data:
                logger.error("\nToo many failures, aborting. Use --keep-data to preserve test artifacts.")
                self._dump_logs()
                raise SystemExit(1)

    def _dump_logs(self) -> None:
        for name, data_dir in [('p0', self.p0_data), ('p1', self.p1_data)]:
            log_file = os.path.join(data_dir, f'{name}.err')
            if os.path.isfile(log_file):
                logger.info("\n--- %s error log (last 30 lines) ---", log_file)
                try:
                    with open(log_file) as f:
                        lines = f.readlines()
                        for line in lines[-30:]:
                            sys.stderr.write(line.rstrip() + '\n')
                except Exception:
                    pass

    # ---- cluster status snapshot (patronictl-list style) ----

    def _node_status(self, handler: 'MySQL') -> dict:
        """Gather status for one node, mimicking GET /patroni output."""
        try:
            if not handler.is_running():
                return {'name': handler.name, 'role': handler.role, 'state': handler.state}

            is_primary = handler.is_primary()
            info: dict = {
                'name': handler.name,
                'role': 'primary' if is_primary else 'replica',
                'state': handler.state,
                'conn': handler.connection_string,
                'server_uuid': handler.sysid,
            }

            master = handler._query_one_dict("SHOW MASTER STATUS")
            if master:
                info['binlog_file'] = master.get('File', '')
                info['binlog_pos'] = master.get('Position', 0)
                info['gtid_set'] = master.get('Executed_Gtid_Set', '')

            if not is_primary:
                info['replication_state'] = handler.replication_state() or 'unknown'
                slave = handler._query_one_dict("SHOW SLAVE STATUS")
                if slave:
                    info['master'] = f"{slave.get('Master_Host', '')}:{slave.get('Master_Port', '')}"
                    info['io_running'] = slave.get('Slave_IO_Running', 'No')
                    info['sql_running'] = slave.get('Slave_SQL_Running', 'No')
                    sbm = slave.get('Seconds_Behind_Master')
                    info['lag_s'] = int(sbm) if sbm is not None else None

            return info
        except Exception:
            return {'name': handler.name, 'role': handler.role, 'state': 'error'}

    def _print_cluster(self, p0: 'MySQL', p1: 'MySQL', title: str) -> None:
        """Print cluster status snapshot in patronictl-list style."""
        nodes = [p0] if p1 is None else [p0, p1]
        ss = [self._node_status(n) for n in nodes]

        sep = "+---------+----------+----------+--------------------------+---------------------+----------+"
        header = f"| {'Member':<7} | {'Role':<8} | {'State':<8} | {'Binlog':<24} | {'Replication':<19} | {'Lag':<8} |"

        def _row(s):
            name = (s.get('name') or '')[:7]
            role = (s.get('role') or '')[:8]
            state = (s.get('state') or '')[:8]

            if s.get('role') == 'primary':
                bf = s.get('binlog_file', '')
                bp = s.get('binlog_pos', 0)
                binlog = f"{bf}:{bp}" if bf else str(bp)
                if len(binlog) > 24:
                    binlog = binlog[-24:]
                repl = ''
                lag = ''
            else:
                binlog = ''
                repl = s.get('replication_state', '-')[:19]
                lag = str(s.get('lag_s') or '') if s.get('lag_s') is not None else ''

            return f"| {name:<7} | {role:<8} | {state:<8} | {binlog:<24} | {repl:<19} | {lag:<8} |"

        lines = [f"\n  {title}", sep, header, sep]
        for s in ss:
            lines.append(_row(s))
        lines.append(sep)

        # Append extra detail line for each node
        for s in ss:
            extras = []
            n = (s.get('name') or '')[:7]
            if s.get('role') == 'primary':
                if s.get('gtid_set'):
                    extras.append(f"GTID: {s['gtid_set']}")
            else:
                if s.get('master'):
                    extras.append(f"master={s['master']}")
                if s.get('io_running') and s.get('sql_running'):
                    extras.append(f"I/O={s['io_running']} SQL={s['sql_running']}")
            if extras:
                lines.append(f"  {n:<7}  {' | '.join(extras)}")

        for line in lines:
            logger.info(line)

    # ---- test phases ----

    def phase1_bootstrap_primary(self) -> 'MySQL':
        logger.info("\n=== Phase 1: Bootstrap primary node (p0) ===")
        p0_config = make_config('p0', self.p0_data, self.p0_port, 1, self.mysql_base)
        p0 = self.MySQL(p0_config)
        ok = p0.bootstrap.bootstrap({})
        self.check('bootstrap() returns True', ok, 'init or startup failed')
        time.sleep(2)

        running = p0.is_running()
        self.check('is_running()', running)
        if not running:
            self._dump_logs()
            return p0

        self.check('is_primary() (no slave configured)', p0.is_primary())
        self.check('is_healthy()', p0.is_healthy())
        self.check('state == running', p0.state == 'running',
                   f'actual state={p0.state}')
        self.check('db_type == mysql', p0.db_type == 'mysql')
        self.check('connection_string format', 'mysql://' in p0.connection_string)
        return p0

    def phase2_setup_data(self, p0: 'MySQL') -> None:
        logger.info("\n=== Phase 2: Create replication user and test data ===")
        p0._query("SET sql_log_bin=0")
        p0._query("CREATE USER IF NOT EXISTS 'replicator'@'%' IDENTIFIED BY 'rep-pass'")
        p0._query("GRANT REPLICATION SLAVE, REPLICATION CLIENT, "
                  "SELECT, RELOAD, LOCK TABLES, PROCESS ON *.* TO 'replicator'@'%'")
        p0._query("FLUSH PRIVILEGES")
        p0._query("SET sql_log_bin=1")

        p0._query("CREATE DATABASE IF NOT EXISTS ha_test")
        p0._query("CREATE TABLE ha_test.t1 (id INT PRIMARY KEY, v VARCHAR(64))")
        p0._query("INSERT INTO ha_test.t1 VALUES (1, 'hello'), (2, 'world')")

        cnt = p0._query_one("SELECT COUNT(*) FROM ha_test.t1")
        self.check('source has 2 rows', cnt and cnt[0] == 2, f'cnt={cnt}')

        ver = p0.server_version
        self.check('server_version > 0', ver > 0, str(ver))

        sid = p0.sysid
        self.check('sysid (server_uuid) is not None', sid is not None)

        row = p0._query_one("SHOW MASTER STATUS")
        self.check('SHOW MASTER STATUS returns binlog info', row is not None)

        # Also verify via dict cursor
        row_d = p0._query_one_dict("SHOW MASTER STATUS")
        self.check('SHOW MASTER STATUS via dict cursor', row_d is not None and 'File' in row_d)

    def phase3_clone_replica(self, p0: 'MySQL') -> 'MySQL':
        logger.info("\n=== Phase 3: Clone replica (p1) from primary (p0) ===")
        p1_config = make_config('p1', self.p1_data, self.p1_port, 2, self.mysql_base)
        p1 = self.MySQL(p1_config)
        leader = self.Member(0, 'p0', 0, {'conn_url': f'mysql://127.0.0.1:{self.p0_port}'})
        ok = p1.bootstrap.clone(leader)
        self.check('clone() returns True', ok)
        if not ok:
            self._dump_logs()
            return p1

        running = p1.is_running()
        self.check('replica is_running() after clone', running)
        if not running:
            self._dump_logs()
            return p1

        data = p1._query("SELECT * FROM ha_test.t1")
        self.check('cloned data matches source (2 rows)',
                   len(data) == 2, f'got {len(data)} rows')
        if data:
            self.check('cloned data content', data[0][1] == 'hello',
                       f'got {data[0][1]}')

        # Verify server_version and sysid
        p1_ver = p1.server_version
        self.check('replica server_version > 0', p1_ver > 0, str(p1_ver))

        p1_sid = p1.sysid
        self.check('replica sysid is not None', p1_sid is not None)
        self.check('replica has different server_uuid from primary',
                   p1_sid != p0.sysid, f'p0={p0.sysid} p1={p1_sid}')
        return p1

    def phase4_configure_replication(self, p1: 'MySQL') -> None:
        logger.info("\n=== Phase 4: Configure GTID-based replication ===")
        leader = self.Member(0, 'p0', 0, {'conn_url': f'mysql://127.0.0.1:{self.p0_port}'})
        p1.follow(leader)
        time.sleep(2)

        sl = p1._query_one("SHOW SLAVE STATUS")
        self.check('Slave_IO_Running == Yes', sl is not None and sl[10] == 'Yes')
        self.check('Slave_SQL_Running == Yes', sl is not None and sl[11] == 'Yes')

        rep_state = p1.replication_state()
        self.check('replication_state == streaming', rep_state == 'streaming',
                   f'actual={rep_state}')

        # Also check via dict cursor
        sl_d = p1._query_one_dict("SHOW SLAVE STATUS")
        if sl_d:
            self.check('Slave_IO_Running (dict)', sl_d.get('Slave_IO_Running') == 'Yes')
            self.check('Slave_SQL_Running (dict)', sl_d.get('Slave_SQL_Running') == 'Yes')

    def phase5_verify_replication(self, p0: 'MySQL', p1: 'MySQL') -> None:
        logger.info("\n=== Phase 5: Verify data replication ===")
        p0._query("INSERT INTO ha_test.t1 VALUES (3, 'replicated')")
        time.sleep(1)

        r = p1._query("SELECT COUNT(*) FROM ha_test.t1")
        self.check('replicated row visible on replica (3 rows)',
                   r and r[0][0] == 3, f'got {r}')

        # Verify content
        rows = p1._query("SELECT id, v FROM ha_test.t1 ORDER BY id")
        self.check('all 3 rows correct', rows is not None and len(rows) == 3)
        if rows and len(rows) == 3:
            self.check('row id=3 value correct', rows[2][1] == 'replicated',
                       f'got {rows[2][1]}')

    def phase6_promote(self, p1: 'MySQL') -> None:
        logger.info("\n=== Phase 6: Promote replica (p1) to primary ===")
        self.check('promote() returns True', p1.promote(10))
        self.check('p1.is_primary() after promote', p1.is_primary())
        self.check('p1 replication_state == primary',
                   p1.replication_state() == 'primary',
                   f'actual={p1.replication_state()}')

    def phase7_demote_and_refollow(self, p1: 'MySQL') -> None:
        logger.info("\n=== Phase 7: Demote and re-follow ===")
        p1.demote()
        self.check('role == demoted after demote()', p1.role == 'demoted',
                   f'actual={p1.role}')

        leader = self.Member(0, 'p0', 0, {'conn_url': f'mysql://127.0.0.1:{self.p0_port}'})
        p1.follow(leader)
        time.sleep(2)
        rep_state = p1.replication_state()
        self.check('replication resumes after re-follow', rep_state == 'streaming',
                   f'actual={rep_state}')

    def phase_cleanup(self, p0: 'MySQL', p1: 'MySQL') -> None:
        logger.info("\n=== Cleanup ===")
        p0.stop()
        p1.stop()
        time.sleep(1)
        self.check('p0 stopped', not p0.is_running())
        self.check('p1 stopped', not p1.is_running())

    # ---- main ----

    def run(self) -> int:
        logger.info("=" * 60)
        logger.info("Patroni MySQL HA Integration Test")
        logger.info("=" * 60)

        if not self.setup():
            return 1

        p0 = p1 = None
        try:
            # Phase 1
            p0 = self.phase1_bootstrap_primary()
            self._print_cluster(p0, None, "After bootstrap — p0 is standalone primary")

            # Phase 2
            self.phase2_setup_data(p0)

            # Phase 3
            p1 = self.phase3_clone_replica(p0)
            self._print_cluster(p0, p1, "After clone — p0=primary, p1=bare replica (not yet replicating)")

            # Phase 4
            self.phase4_configure_replication(p1)
            self._print_cluster(p0, p1, "After GTID replication configured — p1 is streaming")

            # Phase 5
            self.phase5_verify_replication(p0, p1)

            # Phase 6
            self.phase6_promote(p1)
            self._print_cluster(p0, p1, "After promote — p1 is now primary")

            # Phase 7
            self.phase7_demote_and_refollow(p1)
            self._print_cluster(p0, p1, "After demote + re-follow — p0 primary, p1 streaming again")

        except SystemExit:
            pass
        except Exception:
            logger.error("Unexpected error:\n%s", traceback.format_exc())
            self.failed += 1
        finally:
            # Close MySQL connections first so _kill_port won't see our own PID
            for handler in (p0, p1):
                if handler:
                    try:
                        handler.connection_pool.close()
                    except Exception:
                        pass

            # Stop MySQL
            try:
                if p0:
                    p0.stop()
                if p1:
                    p1.stop()
            except Exception:
                pass
            time.sleep(1)

            if self.keep_data:
                logger.info("\nTest data preserved at %s", self.test_dir)
            else:
                self._clean()

        # Summary
        total = self.passed + self.failed
        logger.info("\n" + "=" * 60)
        logger.info("=== Results: %d/%d passed, %d failed ===", self.passed, total, self.failed)
        logger.info("=" * 60)
        return 0 if self.failed == 0 else 1


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == '__main__':
    args = parse_args()
    test = MySQLHATest(args)
    sys.exit(test.run())
