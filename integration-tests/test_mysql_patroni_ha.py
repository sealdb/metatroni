#!/usr/bin/env python3
"""Patroni + etcd MySQL HA integration test.

Starts a local etcd and two Patroni processes managing MySQL nodes, then
validates:

  1. Primary bootstrap via Patroni
  2. Replica joins (clone + GTID replication)
  3. Data replicates
  4. Kill primary Patroni → automatic failover
  5. Restart old primary → rejoin as replica

Configuration (CLI > env > defaults):

  --mysql-base   MYSQL_BASE        /usr/local/mysql
  --test-dir     MYSQL_TEST_DIR    /tmp/patroni_mysql_patroni_ha
  --timeout      MYSQL_TIMEOUT     180
  --keep-data    MYSQL_KEEP_DATA   0

Example:

  MYSQL_BASE=/home/wslu/work/mysql/mysql80-debug \\
    python3 integration-tests/test_mysql_patroni_ha.py
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger('mysql_patroni_ha')

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description='Patroni+etcd MySQL HA Integration Test')
    p.add_argument('--mysql-base', default=os.environ.get('MYSQL_BASE', '/usr/local/mysql'))
    p.add_argument('--test-dir', default=os.environ.get('MYSQL_TEST_DIR', '/tmp/patroni_mysql_patroni_ha'))
    p.add_argument('--timeout', type=int, default=int(os.environ.get('MYSQL_TIMEOUT', '180')))
    p.add_argument('--keep-data', action='store_true',
                   default=bool(int(os.environ.get('MYSQL_KEEP_DATA', '0'))))
    p.add_argument('--etcd-port', type=int, default=int(os.environ.get('MYSQL_ETCD_PORT', '2399')))
    p.add_argument('--p0-port', type=int, default=int(os.environ.get('MYSQL_P0_PORT', '34007')))
    p.add_argument('--p1-port', type=int, default=int(os.environ.get('MYSQL_P1_PORT', '34008')))
    # Use 34xxx API ports — some 8xxx ports hang on connect_ex in this environment.
    p.add_argument('--api0-port', type=int, default=int(os.environ.get('MYSQL_API0_PORT', '34017')))
    p.add_argument('--api1-port', type=int, default=int(os.environ.get('MYSQL_API1_PORT', '34018')))
    return p.parse_args()


def _kill_port(port: int) -> None:
    try:
        out = subprocess.check_output(
            ['ss', '-tlnp', f'sport = :{port}'], stderr=subprocess.DEVNULL, text=True, timeout=5)
        for line in out.splitlines():
            if 'pid=' in line:
                pid = line.split('pid=')[1].split(',')[0].split(')')[0]
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except Exception:
                    pass
    except Exception:
        pass
    try:
        out = subprocess.check_output(['fuser', f'{port}/tcp'], stderr=subprocess.DEVNULL, text=True, timeout=5)
        for pid in out.split():
            try:
                os.kill(int(pid), signal.SIGKILL)
            except Exception:
                pass
    except Exception:
        pass


def http_get_json(url: str, timeout: float = 3.0) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def http_get_status(url: str, timeout: float = 3.0) -> int | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return None


NODE_YAML = """\
scope: mysql-patroni-ha
name: {name}
namespace: /mysql-ha/

database:
  type: mysql

restapi:
  listen: 127.0.0.1:{api_port}
  connect_address: 127.0.0.1:{api_port}

etcd3:
  host: 127.0.0.1:{etcd_port}

bootstrap:
  dcs:
    ttl: 20
    loop_wait: 5
    retry_timeout: 10
    maximum_lag_on_failover: 1048576

mysql:
  name: {name}
  listen: 127.0.0.1:{mysql_port}
  connect_address: 127.0.0.1:{mysql_port}
  data_dir: {data_dir}
  config_dir: {data_dir}
  bin_dir: {bin_dir}
  port: {mysql_port}
  server_id: {server_id}
  authentication:
    superuser:
      username: root
      password: ""
    replication:
      username: replicator
      password: rep-pass
  parameters:
    server_id: "{server_id}"
    gtid_mode: "ON"
    enforce_gtid_consistency: "ON"
    log-bin: "mysql-bin"
    log_slave_updates: "ON"
    mysqlx: "OFF"
    binlog_format: "ROW"

tags:
  noloadbalance: false
  clonefrom: false
  nostream: false
"""


class PatroniMySQLHATest:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.test_dir = args.test_dir
        self.mysql_base = args.mysql_base
        self.bin_dir = os.path.join(args.mysql_base, 'bin')
        self.timeout = args.timeout
        self.keep_data = args.keep_data

        self.etcd_port = args.etcd_port
        self.p0_port = args.p0_port
        self.p1_port = args.p1_port
        self.api0_port = args.api0_port
        self.api1_port = args.api1_port

        self.p0_data = os.path.join(self.test_dir, 'mysql0')
        self.p1_data = os.path.join(self.test_dir, 'mysql1')
        self.etcd_data = os.path.join(self.test_dir, 'etcd')
        self.cfg0 = os.path.join(self.test_dir, 'mysql0.yml')
        self.cfg1 = os.path.join(self.test_dir, 'mysql1.yml')
        self.log0 = os.path.join(self.test_dir, 'patroni0.log')
        self.log1 = os.path.join(self.test_dir, 'patroni1.log')
        self.etcd_log = os.path.join(self.test_dir, 'etcd.log')

        self.etcd_proc: subprocess.Popen | None = None
        self.p0_proc: subprocess.Popen | None = None
        self.p1_proc: subprocess.Popen | None = None

        self.passed = 0
        self.failed = 0

    def check(self, label: str, cond: bool, detail: str = '') -> None:
        if cond:
            logger.info('  PASS  %s', label)
            self.passed += 1
        else:
            logger.error('  FAIL  %s%s', label, f'  ({detail})' if detail else '')
            self.failed += 1
            if self.failed >= 3 and not self.keep_data:
                self._dump_logs()
                raise SystemExit(1)

    def _dump_logs(self) -> None:
        for path in (self.log0, self.log1, self.etcd_log):
            if os.path.isfile(path):
                logger.info('--- %s (last 40 lines) ---', path)
                try:
                    with open(path) as f:
                        for line in f.readlines()[-40:]:
                            sys.stderr.write(line)
                except Exception:
                    pass

    def setup(self) -> bool:
        if not os.path.isfile(os.path.join(self.bin_dir, 'mysqld')):
            logger.error('mysqld not found in %s', self.bin_dir)
            return False
        try:
            import pymysql  # noqa: F401
        except ImportError:
            logger.error('pymysql not installed')
            return False
        if not shutil.which('etcd'):
            logger.error('etcd not found in PATH')
            return False

        os.environ['PATH'] = f"{self.bin_dir}:{os.environ.get('PATH', '')}"
        # Prefer the repo's patroni package
        os.environ['PYTHONPATH'] = REPO_ROOT + os.pathsep + os.environ.get('PYTHONPATH', '')

        # Always wipe leftover state from prior runs. MYSQL_KEEP_DATA only
        # preserves data at the *end* for post-mortem debugging.
        self.cleanup(kill_only=True)
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)
        os.makedirs(self.test_dir, exist_ok=True)
        os.makedirs(self.p0_data, exist_ok=True)
        os.makedirs(self.p1_data, exist_ok=True)
        os.makedirs(self.etcd_data, exist_ok=True)

        self._write_config(self.cfg0, 'mysql0', self.p0_data, self.p0_port, self.api0_port, 1)
        self._write_config(self.cfg1, 'mysql1', self.p1_data, self.p1_port, self.api1_port, 2)

        logger.info('=== Configuration ===')
        logger.info('  mysql_base: %s', self.mysql_base)
        logger.info('  test_dir:   %s', self.test_dir)
        logger.info('  etcd:       127.0.0.1:%d', self.etcd_port)
        logger.info('  mysql0:     port=%d api=%d', self.p0_port, self.api0_port)
        logger.info('  mysql1:     port=%d api=%d', self.p1_port, self.api1_port)
        return True

    def _write_config(self, path: str, name: str, data_dir: str,
                      mysql_port: int, api_port: int, server_id: int) -> None:
        with open(path, 'w') as f:
            f.write(NODE_YAML.format(
                name=name,
                data_dir=data_dir,
                bin_dir=self.bin_dir,
                mysql_port=mysql_port,
                api_port=api_port,
                server_id=server_id,
                etcd_port=self.etcd_port,
            ))

    def cleanup(self, kill_only: bool = False) -> None:
        for proc in (self.p0_proc, self.p1_proc, self.etcd_proc):
            if proc and proc.poll() is None:
                try:
                    proc.send_signal(signal.SIGTERM)
                except Exception:
                    pass
        time.sleep(1)
        for proc in (self.p0_proc, self.p1_proc, self.etcd_proc):
            if proc and proc.poll() is None:
                try:
                    proc.kill()
                except Exception:
                    pass

        for port in (self.p0_port, self.p1_port, self.api0_port, self.api1_port, self.etcd_port):
            _kill_port(port)
        try:
            out = subprocess.check_output(
                ['pgrep', '-f', f'mysqld.*{self.test_dir}'], text=True, stderr=subprocess.DEVNULL)
            for pid in out.split():
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            out = subprocess.check_output(
                ['pgrep', '-f', f'patroni.*{self.test_dir}'], text=True, stderr=subprocess.DEVNULL)
            for pid in out.split():
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except Exception:
                    pass
        except Exception:
            pass

        if not kill_only and os.path.exists(self.test_dir) and not self.keep_data:
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def start_etcd(self) -> None:
        logger.info('\n=== Start etcd ===')
        cmd = [
            'etcd',
            '--name', 'mysql-ha-etcd',
            '--data-dir', self.etcd_data,
            '--listen-client-urls', f'http://127.0.0.1:{self.etcd_port}',
            '--advertise-client-urls', f'http://127.0.0.1:{self.etcd_port}',
            '--listen-peer-urls', f'http://127.0.0.1:{self.etcd_port + 1}',
            '--initial-advertise-peer-urls', f'http://127.0.0.1:{self.etcd_port + 1}',
            '--initial-cluster', f'mysql-ha-etcd=http://127.0.0.1:{self.etcd_port + 1}',
            '--initial-cluster-token', 'mysql-patroni-ha',
            '--initial-cluster-state', 'new',
        ]
        logf = open(self.etcd_log, 'w')
        self.etcd_proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT)
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                subprocess.check_call(
                    ['etcdctl', f'--endpoints=http://127.0.0.1:{self.etcd_port}', 'endpoint', 'health'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
                logger.info('  etcd healthy on :%d', self.etcd_port)
                return
            except Exception:
                time.sleep(0.5)
        raise RuntimeError('etcd failed to become healthy')

    def start_patroni(self, cfg: str, log_path: str) -> subprocess.Popen:
        logf = open(log_path, 'w')
        # Use python -m patroni so PYTHONPATH from this repo is honored
        proc = subprocess.Popen(
            [sys.executable, '-m', 'patroni', cfg],
            stdout=logf, stderr=subprocess.STDOUT,
            cwd=REPO_ROOT,
            env=os.environ.copy(),
        )
        return proc

    def wait_role(self, api_port: int, role: str, timeout: float | None = None) -> dict | None:
        """Wait until /patroni reports the expected role (primary/replica)."""
        url = f'http://127.0.0.1:{api_port}/patroni'
        deadline = time.time() + (timeout or self.timeout)
        last = None
        while time.time() < deadline:
            last = http_get_json(url)
            if last and last.get('state') == 'running':
                if last.get('role') == role:
                    return last
                # Replica may briefly report primary before follow(); streaming is enough.
                if role == 'replica' and last.get('replication_state') == 'streaming':
                    return last
            time.sleep(1)
        return last

    def wait_http_ok(self, api_port: int, path: str = '/patroni',
                     timeout: float | None = None) -> dict | None:
        url = f'http://127.0.0.1:{api_port}{path}'
        deadline = time.time() + (timeout or self.timeout)
        last = None
        while time.time() < deadline:
            last = http_get_json(url)
            if last:
                return last
            time.sleep(1)
        return last

    def mysql_query(self, port: int, sql: str) -> str:
        cmd = [
            os.path.join(self.bin_dir, 'mysql'),
            '-h127.0.0.1', f'-P{port}', '-uroot', '-N', '-B', '-e', sql,
        ]
        return subprocess.check_output(cmd, text=True, timeout=30).strip()

    def run(self) -> int:
        logger.info('=' * 60)
        logger.info('Patroni + etcd MySQL HA Integration Test')
        logger.info('=' * 60)

        if not self.setup():
            return 1

        try:
            self.start_etcd()

            # --- Phase 1: bootstrap primary ---
            logger.info('\n=== Phase 1: Start primary Patroni (mysql0) ===')
            self.p0_proc = self.start_patroni(self.cfg0, self.log0)
            info = self.wait_role(self.api0_port, 'primary')
            self.check('mysql0 becomes primary', bool(info and info.get('role') == 'primary'),
                       f'got={info}')
            if not info:
                self._dump_logs()
                return 1
            logger.info('  mysql0: %s', json.dumps({k: info.get(k) for k in
                        ('state', 'role', 'server_version', 'replication_state')}, default=str))

            # Create test data on primary
            logger.info('\n=== Phase 2: Create test data on primary ===')
            # Wait until MySQL accepts connections
            deadline = time.time() + 60
            while time.time() < deadline:
                try:
                    self.mysql_query(self.p0_port, 'SELECT 1')
                    break
                except Exception:
                    time.sleep(1)
            self.mysql_query(self.p0_port,
                             "CREATE DATABASE IF NOT EXISTS ha_test; "
                             "CREATE TABLE IF NOT EXISTS ha_test.t1 (id INT PRIMARY KEY, v VARCHAR(64)); "
                             "INSERT INTO ha_test.t1 VALUES (1,'hello'),(2,'world') "
                             "ON DUPLICATE KEY UPDATE v=VALUES(v)")
            cnt = self.mysql_query(self.p0_port, 'SELECT COUNT(*) FROM ha_test.t1')
            self.check('primary has 2 rows', cnt == '2', f'cnt={cnt}')

            # --- Phase 3: start replica ---
            logger.info('\n=== Phase 3: Start replica Patroni (mysql1) ===')
            self.p1_proc = self.start_patroni(self.cfg1, self.log1)
            info1 = self.wait_role(self.api1_port, 'replica')
            self.check('mysql1 becomes replica', bool(info1 and info1.get('role') == 'replica'),
                       f'got={info1}')
            if info1:
                logger.info('  mysql1: %s', json.dumps({k: info1.get(k) for k in
                            ('state', 'role', 'replication_state')}, default=str))

            # Wait for clone+replication to catch up
            deadline = time.time() + self.timeout
            caught = False
            while time.time() < deadline:
                try:
                    c = self.mysql_query(self.p1_port, 'SELECT COUNT(*) FROM ha_test.t1')
                    if c == '2':
                        caught = True
                        break
                except Exception:
                    pass
                time.sleep(2)
            self.check('replica has cloned/replicated 2 rows', caught)

            # --- Phase 4: verify live replication ---
            logger.info('\n=== Phase 4: Verify live replication ===')
            self.mysql_query(self.p0_port, "INSERT INTO ha_test.t1 VALUES (3,'replicated')")
            deadline = time.time() + 60
            ok = False
            while time.time() < deadline:
                try:
                    if self.mysql_query(self.p1_port, 'SELECT COUNT(*) FROM ha_test.t1') == '3':
                        ok = True
                        break
                except Exception:
                    pass
                time.sleep(1)
            self.check('row id=3 visible on replica', ok)

            # --- Phase 5: kill primary → failover ---
            logger.info('\n=== Phase 5: Kill primary Patroni (mysql0) → failover ===')
            assert self.p0_proc is not None
            self.p0_proc.send_signal(signal.SIGKILL)
            try:
                self.p0_proc.wait(timeout=5)
            except Exception:
                pass

            info1 = self.wait_role(self.api1_port, 'primary', timeout=self.timeout)
            self.check('mysql1 promoted to primary after failover',
                       bool(info1 and info1.get('role') == 'primary'), f'got={info1}')

            # Stop orphaned mysqld on the old primary cleanly (avoid long crash recovery)
            try:
                subprocess.run(
                    [os.path.join(self.bin_dir, 'mysqladmin'),
                     '-h127.0.0.1', f'-P{self.p0_port}', '-uroot', 'shutdown'],
                    timeout=30, capture_output=True)
            except Exception:
                _kill_port(self.p0_port)
            time.sleep(2)

            # Write on new primary
            deadline = time.time() + 30
            while time.time() < deadline:
                try:
                    self.mysql_query(self.p1_port, "INSERT INTO ha_test.t1 VALUES (4,'after_failover')")
                    break
                except Exception:
                    time.sleep(1)
            cnt = self.mysql_query(self.p1_port, 'SELECT COUNT(*) FROM ha_test.t1')
            self.check('new primary accepts writes (4 rows)', cnt == '4', f'cnt={cnt}')

            # --- Phase 6: restart old primary → rejoin ---
            logger.info('\n=== Phase 6: Restart old primary (mysql0) → rejoin ===')
            _kill_port(self.p0_port)
            time.sleep(1)
            self.p0_proc = self.start_patroni(self.cfg0, self.log0)

            info0 = self.wait_role(self.api0_port, 'replica', timeout=self.timeout)
            self.check('mysql0 rejoins as replica',
                       bool(info0 and (info0.get('role') == 'replica'
                                       or info0.get('replication_state') == 'streaming')),
                       f'got={info0}')
            # Regression: former primary must not stay as writable "primary" replication_state
            # (that was the broken demote path that hit PG rewind / get_guc_value).
            self.check('mysql0 replication_state is not primary after rejoin',
                       not info0 or info0.get('replication_state') != 'primary',
                       f'got={info0}')
            if info0 and info0.get('replication_state'):
                self.check('mysql0 replication_state is streaming',
                           info0.get('replication_state') == 'streaming',
                           f'got={info0}')

            # Catch-up of failover write
            deadline = time.time() + self.timeout
            caught = False
            while time.time() < deadline:
                try:
                    rows = self.mysql_query(self.p0_port,
                                            "SELECT v FROM ha_test.t1 WHERE id=4")
                    if rows == 'after_failover':
                        caught = True
                        break
                except Exception:
                    pass
                time.sleep(1)
            self.check('mysql0 caught up failover write (id=4)', caught)

            # Continuous replication after rejoin
            self.mysql_query(self.p1_port, "INSERT INTO ha_test.t1 VALUES (5,'after_rejoin')")
            deadline = time.time() + 60
            ok = False
            while time.time() < deadline:
                try:
                    if self.mysql_query(self.p0_port, "SELECT v FROM ha_test.t1 WHERE id=5") == 'after_rejoin':
                        ok = True
                        break
                except Exception:
                    pass
                time.sleep(1)
            self.check('mysql0 receives post-rejoin write (id=5)', ok)

            c0 = self.mysql_query(self.p0_port, 'SELECT COUNT(*) FROM ha_test.t1')
            c1 = self.mysql_query(self.p1_port, 'SELECT COUNT(*) FROM ha_test.t1')
            self.check('both nodes have 5 rows', c0 == '5' and c1 == '5', f'p0={c0} p1={c1}')

            # Final cluster snapshot
            logger.info('\n=== Final cluster status ===')
            for name, port in (('mysql0', self.api0_port), ('mysql1', self.api1_port)):
                info = http_get_json(f'http://127.0.0.1:{port}/patroni') or {}
                logger.info('  %s: role=%s state=%s repl=%s',
                            name, info.get('role'), info.get('state'), info.get('replication_state'))

        except SystemExit:
            pass
        except Exception:
            logger.exception('Unexpected error')
            self.failed += 1
            self._dump_logs()
        finally:
            if self.keep_data:
                logger.info('Preserving test data at %s (stopping processes only)', self.test_dir)
                for proc in (self.p0_proc, self.p1_proc, self.etcd_proc):
                    if proc and proc.poll() is None:
                        proc.send_signal(signal.SIGTERM)
                time.sleep(2)
                for proc in (self.p0_proc, self.p1_proc, self.etcd_proc):
                    if proc and proc.poll() is None:
                        proc.kill()
                for port in (self.p0_port, self.p1_port, self.api0_port, self.api1_port, self.etcd_port):
                    _kill_port(port)
            else:
                self.cleanup()

        total = self.passed + self.failed
        logger.info('\n' + '=' * 60)
        logger.info('=== Results: %d/%d passed, %d failed ===', self.passed, total, self.failed)
        logger.info('=' * 60)
        return 0 if self.failed == 0 else 1


if __name__ == '__main__':
    sys.exit(PatroniMySQLHATest(parse_args()).run())
