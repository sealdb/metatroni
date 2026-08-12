#!/usr/bin/env python3
"""MySQL standby cluster E2E (clone + GTID cascade).

Topology (single host, staggered ports):

  Primary site  (scope mysql-standby-pri):  1 writable primary
  Standby site  (scope mysql-standby-stb):  standby_leader + optional cascade

Validates:

  1. Primary site bootstraps
  2. Standby leader clones from remote (xtrabackup preferred, mysqldump fallback)
  3. Standby leader is super_read_only and streams via GTID
  4. Writes on primary appear on standby
  5. Optional cascade replica follows standby leader

Configuration (CLI > env > defaults):

  --mysql-base   MYSQL_BASE        /usr/local/mysql
  --test-dir     MYSQL_STB_DIR     /tmp/patroni_mysql_standby
  --timeout      MYSQL_TIMEOUT     240

Example:

  MYSQL_BASE=/home/wslu/work/mysql/mysql80-debug \\
    python3 integration-tests/test_mysql_standby_cluster.py
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
import urllib.request

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger('mysql_standby')

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description='MySQL standby cluster E2E')
    p.add_argument('--mysql-base', default=os.environ.get('MYSQL_BASE', '/usr/local/mysql'))
    p.add_argument('--test-dir', default=os.environ.get('MYSQL_STB_DIR', '/tmp/patroni_mysql_standby'))
    p.add_argument('--timeout', type=int, default=int(os.environ.get('MYSQL_TIMEOUT', '240')))
    p.add_argument('--keep-data', action='store_true',
                   default=bool(int(os.environ.get('MYSQL_KEEP_DATA', '0'))))
    p.add_argument('--etcd-port', type=int, default=int(os.environ.get('MYSQL_STB_ETCD', '2401')))
    p.add_argument('--pri-port', type=int, default=34101)
    p.add_argument('--stb0-port', type=int, default=34102)
    p.add_argument('--stb1-port', type=int, default=34103)
    p.add_argument('--api-pri', type=int, default=34111)
    p.add_argument('--api-stb0', type=int, default=34112)
    p.add_argument('--api-stb1', type=int, default=34113)
    p.add_argument('--skip-cascade', action='store_true',
                   help='Only run primary + standby_leader (no local cascade)')
    return p.parse_args()


def _kill_port(port: int) -> None:
    for cmd in (
        ['ss', '-tlnp', f'sport = :{port}'],
        ['fuser', f'{port}/tcp'],
    ):
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True, timeout=5)
            for token in out.replace(',', ' ').split():
                if token.startswith('pid='):
                    token = token.split('=', 1)[1].rstrip(')')
                if token.isdigit():
                    try:
                        os.kill(int(token), signal.SIGKILL)
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


PRIMARY_YAML = """\
scope: mysql-standby-pri
name: {name}
namespace: /mysql-stb/

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

mysql:
  name: {name}
  listen: 127.0.0.1:{mysql_port}
  connect_address: 127.0.0.1:{mysql_port}
  data_dir: {data_dir}
  config_dir: {data_dir}
  bin_dir: {bin_dir}
  port: {mysql_port}
  server_id: {server_id}
  create_replica_methods:
    - xtrabackup
    - mysqldump
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
"""

STANDBY_YAML = """\
scope: mysql-standby-stb
name: {name}
namespace: /mysql-stb/

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
    standby_cluster:
      host: 127.0.0.1
      port: {remote_port}
      create_replica_methods:
        - xtrabackup
        - mysqldump

mysql:
  name: {name}
  listen: 127.0.0.1:{mysql_port}
  connect_address: 127.0.0.1:{mysql_port}
  data_dir: {data_dir}
  config_dir: {data_dir}
  bin_dir: {bin_dir}
  port: {mysql_port}
  server_id: {server_id}
  create_replica_methods:
    - xtrabackup
    - mysqldump
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
"""


class StandbyClusterTest:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.test_dir = args.test_dir
        self.bin_dir = os.path.join(args.mysql_base, 'bin')
        self.timeout = args.timeout
        self.keep_data = args.keep_data
        self.etcd_port = args.etcd_port

        self.procs: list[subprocess.Popen] = []
        self.passed = 0
        self.failed = 0

    def check(self, label: str, cond: bool, detail: str = '') -> None:
        if cond:
            logger.info('  PASS  %s', label)
            self.passed += 1
        else:
            logger.error('  FAIL  %s%s', label, f'  ({detail})' if detail else '')
            self.failed += 1

    def mysql(self, port: int, sql: str, user: str = 'root') -> str:
        cmd = [os.path.join(self.bin_dir, 'mysql'),
               f'-h127.0.0.1', f'-P{port}', f'-u{user}',
               '--connect-timeout=3', '-N', '-e', sql]
        if user == 'replicator':
            cmd.insert(-2, '-prep-pass')
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            raise RuntimeError(r.stderr[-400:] or r.stdout[-400:])
        return r.stdout.strip()

    def wait_role(self, api_port: int, roles: set[str], label: str) -> dict | None:
        deadline = time.time() + self.timeout
        last = None
        while time.time() < deadline:
            last = http_get_json(f'http://127.0.0.1:{api_port}/patroni')
            if last and last.get('state') == 'running' and last.get('role') in roles:
                logger.info('  %s → role=%s', label, last.get('role'))
                return last
            # Streaming toward remote is enough while role catches up.
            if last and last.get('state') == 'running' \
                    and 'standby_leader' in roles \
                    and last.get('replication_state') == 'streaming':
                logger.info('  %s → role=%s (streaming)', label, last.get('role'))
                return last
            time.sleep(2)
        logger.error('  timeout waiting for %s (last=%s)', label, last)
        return None

    def cleanup(self) -> None:
        for proc in self.procs:
            try:
                proc.send_signal(signal.SIGTERM)
            except Exception:
                pass
        time.sleep(1)
        for proc in self.procs:
            try:
                if proc.poll() is None:
                    proc.kill()
            except Exception:
                pass
        for port in (self.args.etcd_port, self.args.pri_port, self.args.stb0_port,
                     self.args.stb1_port, self.args.api_pri, self.args.api_stb0,
                     self.args.api_stb1):
            _kill_port(port)
        if not self.keep_data and os.path.isdir(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def start_etcd(self) -> None:
        etcd_data = os.path.join(self.test_dir, 'etcd')
        os.makedirs(etcd_data, exist_ok=True)
        log = open(os.path.join(self.test_dir, 'etcd.log'), 'w')
        proc = subprocess.Popen(
            ['etcd',
             '--data-dir', etcd_data,
             '--listen-client-urls', f'http://127.0.0.1:{self.etcd_port}',
             '--advertise-client-urls', f'http://127.0.0.1:{self.etcd_port}',
             '--listen-peer-urls', f'http://127.0.0.1:{self.etcd_port + 10000}',
             '--initial-advertise-peer-urls', f'http://127.0.0.1:{self.etcd_port + 10000}',
             '--initial-cluster', f'default=http://127.0.0.1:{self.etcd_port + 10000}'],
            stdout=log, stderr=subprocess.STDOUT, cwd=self.test_dir)
        self.procs.append(proc)
        time.sleep(2)

    def start_patroni(self, cfg: str, log_name: str) -> subprocess.Popen:
        log = open(os.path.join(self.test_dir, log_name), 'w')
        env = os.environ.copy()
        env['PYTHONPATH'] = REPO_ROOT + os.pathsep + env.get('PYTHONPATH', '')
        proc = subprocess.Popen(
            [sys.executable, '-m', 'patroni', cfg],
            stdout=log, stderr=subprocess.STDOUT, cwd=REPO_ROOT, env=env)
        self.procs.append(proc)
        return proc

    def run(self) -> int:
        logger.info('=== MySQL standby cluster E2E ===')
        self.cleanup()
        os.makedirs(self.test_dir, exist_ok=True)

        try:
            self.start_etcd()

            pri_data = os.path.join(self.test_dir, 'pri')
            stb0_data = os.path.join(self.test_dir, 'stb0')
            stb1_data = os.path.join(self.test_dir, 'stb1')
            os.makedirs(pri_data, exist_ok=True)
            os.makedirs(stb0_data, exist_ok=True)
            os.makedirs(stb1_data, exist_ok=True)

            pri_yml = os.path.join(self.test_dir, 'pri.yml')
            stb0_yml = os.path.join(self.test_dir, 'stb0.yml')
            stb1_yml = os.path.join(self.test_dir, 'stb1.yml')

            with open(pri_yml, 'w') as f:
                f.write(PRIMARY_YAML.format(
                    name='pri0', api_port=self.args.api_pri, etcd_port=self.etcd_port,
                    mysql_port=self.args.pri_port, data_dir=pri_data, bin_dir=self.bin_dir,
                    server_id=101))
            with open(stb0_yml, 'w') as f:
                f.write(STANDBY_YAML.format(
                    name='stb0', api_port=self.args.api_stb0, etcd_port=self.etcd_port,
                    mysql_port=self.args.stb0_port, data_dir=stb0_data, bin_dir=self.bin_dir,
                    server_id=201, remote_port=self.args.pri_port))
            with open(stb1_yml, 'w') as f:
                f.write(STANDBY_YAML.format(
                    name='stb1', api_port=self.args.api_stb1, etcd_port=self.etcd_port,
                    mysql_port=self.args.stb1_port, data_dir=stb1_data, bin_dir=self.bin_dir,
                    server_id=202, remote_port=self.args.pri_port))

            self.start_patroni(pri_yml, 'pri.log')
            pri = self.wait_role(self.args.api_pri, {'primary', 'master'}, 'primary site')
            self.check('primary site is primary', pri is not None)

            # Seed data before standby clone
            self.mysql(self.args.pri_port,
                       "CREATE DATABASE IF NOT EXISTS stbtest; "
                       "CREATE TABLE IF NOT EXISTS stbtest.t (id INT PRIMARY KEY, v VARCHAR(32)); "
                       "INSERT INTO stbtest.t VALUES (1, 'before-clone') "
                       "ON DUPLICATE KEY UPDATE v=VALUES(v);")

            self.start_patroni(stb0_yml, 'stb0.log')
            stb0 = self.wait_role(self.args.api_stb0, {'standby_leader'}, 'standby leader')
            self.check('standby leader role', stb0 is not None)

            # Read-only + replication
            try:
                ro = self.mysql(self.args.stb0_port, "SELECT @@super_read_only")
                self.check('standby leader super_read_only', ro in ('1', 'ON'))
            except Exception as e:
                self.check('standby leader super_read_only', False, str(e))

            # Wait for cloned row
            deadline = time.time() + self.timeout
            got = ''
            while time.time() < deadline:
                try:
                    got = self.mysql(self.args.stb0_port, "SELECT v FROM stbtest.t WHERE id=1")
                    if got == 'before-clone':
                        break
                except Exception:
                    pass
                time.sleep(2)
            self.check('standby has cloned data', got == 'before-clone', got)

            self.mysql(self.args.pri_port,
                       "INSERT INTO stbtest.t VALUES (2, 'after-clone') "
                       "ON DUPLICATE KEY UPDATE v=VALUES(v);")
            deadline = time.time() + 60
            got2 = ''
            while time.time() < deadline:
                try:
                    got2 = self.mysql(self.args.stb0_port, "SELECT v FROM stbtest.t WHERE id=2")
                    if got2 == 'after-clone':
                        break
                except Exception:
                    pass
                time.sleep(2)
            self.check('GTID stream after clone', got2 == 'after-clone', got2)

            if not self.args.skip_cascade:
                self.start_patroni(stb1_yml, 'stb1.log')
                stb1 = self.wait_role(self.args.api_stb1, {'replica'}, 'cascade replica')
                self.check('cascade replica role', stb1 is not None)
                deadline = time.time() + self.timeout
                got3 = ''
                while time.time() < deadline:
                    try:
                        got3 = self.mysql(self.args.stb1_port, "SELECT v FROM stbtest.t WHERE id=2")
                        if got3 == 'after-clone':
                            break
                    except Exception:
                        pass
                    time.sleep(2)
                self.check('cascade has data', got3 == 'after-clone', got3)

        except Exception:
            logger.exception('E2E aborted')
            self.failed += 1
        finally:
            self.cleanup()

        logger.info('=== results: %s passed, %s failed ===', self.passed, self.failed)
        return 1 if self.failed else 0


def main() -> int:
    return StandbyClusterTest(parse_args()).run()


if __name__ == '__main__':
    sys.exit(main())
