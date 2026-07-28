#!/usr/bin/env python3
"""Patroni + etcd3 + 3-node MySQL Group Replication HA E2E.

Starts local etcd and three Patroni processes with shared MGR config, then
validates recovery driven by real HA loops (not direct run_mgr_cycle):

  1. Primary bootstraps MGR via Patroni
  2. Two joiners enter the group
  3. Write replicates across ONLINE members
  4. STOP GROUP_REPLICATION on all (majority loss; Patroni stays up)
  5. Advance GTID only on mysql2
  6. Behind lock-holder yields; mysql2 bootstraps; others rejoin
  7. Catch-up + post-recovery write

Example:

  MYSQL_BASE=/home/wslu/work/mysql/mysql80-debug PYTHONPATH=. \\
    python3 -u integration-tests/test_mysql_mgr_patroni_ha.py
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
import uuid

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger('mysql_mgr_patroni_ha')

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description='Patroni+etcd3+MGR 3-node HA E2E')
    p.add_argument('--mysql-base', default=os.environ.get('MYSQL_BASE', '/usr/local/mysql'))
    p.add_argument('--test-dir', default=os.environ.get(
        'MYSQL_MGR_PATRONI_DIR', '/tmp/patroni_mysql_mgr_patroni_ha'))
    p.add_argument('--timeout', type=int, default=int(os.environ.get('MYSQL_TIMEOUT', '240')))
    p.add_argument('--keep-data', action='store_true',
                   default=bool(int(os.environ.get('MYSQL_KEEP_DATA', '0'))))
    p.add_argument('--etcd-port', type=int, default=int(os.environ.get('MYSQL_ETCD_PORT', '2499')))
    # MySQL client ports; MGR uses port+10. REST API uses a separate range.
    p.add_argument('--base-port', type=int, default=int(os.environ.get('MYSQL_MGR_BASE_PORT', '34107')))
    p.add_argument('--api-base-port', type=int,
                   default=int(os.environ.get('MYSQL_MGR_API_BASE', '34207')))
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
        out = subprocess.check_output(
            ['fuser', f'{port}/tcp'], stderr=subprocess.DEVNULL, text=True, timeout=5)
        for pid in out.split():
            try:
                os.kill(int(pid), signal.SIGKILL)
            except Exception:
                pass
    except Exception:
        pass


def http_get_json(url: str, timeout: float = 3.0) -> dict | None:
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


NODE_YAML = """\
scope: mysql-mgr-patroni-ha
name: {name}
namespace: /mysql-mgr-ha/

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
    plugin_dir: "{plugin_dir}"
    group_replication_group_name: "{group_name}"
    loose-group_replication_start_on_boot: "OFF"
    loose-group_replication_bootstrap_group: "OFF"
    loose-group_replication_single_primary_mode: "ON"
    loose-group_replication_local_address: "127.0.0.1:{mgr_port}"
    loose-group_replication_group_seeds: "{seeds}"
    loose-group_replication_ip_allowlist: "127.0.0.1/32,::1/128"
    loose-group_replication_recovery_use_ssl: "OFF"
    loose-binlog_transaction_dependency_tracking: "WRITESET"
    report_host: "127.0.0.1"
    report_port: "{mysql_port}"
    cluster_size: "3"

tags:
  noloadbalance: false
  clonefrom: false
  nostream: false
"""


PRIMARY_ROLES = {'primary', 'master', 'mgr_primary'}
SECONDARY_ROLES = {'replica', 'secondary', 'mgr_secondary'}


class MgrPatroniHATest:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.test_dir = args.test_dir
        self.mysql_base = args.mysql_base
        self.bin_dir = os.path.join(args.mysql_base, 'bin')
        self.plugin_dir = os.path.join(args.mysql_base, 'lib/plugin')
        self.timeout = args.timeout
        self.keep_data = args.keep_data
        self.etcd_port = args.etcd_port
        self.group_name = str(uuid.uuid4())

        self.names = ['mysql0', 'mysql1', 'mysql2']
        self.ports = [args.base_port + i for i in range(3)]
        self.mgr_ports = [p + 10 for p in self.ports]
        self.api_ports = [args.api_base_port + i for i in range(3)]
        self.seeds = ','.join(f'127.0.0.1:{p}' for p in self.mgr_ports)

        self.data_dirs = [os.path.join(self.test_dir, n) for n in self.names]
        self.cfgs = [os.path.join(self.test_dir, f'{n}.yml') for n in self.names]
        self.logs = [os.path.join(self.test_dir, f'patroni_{n}.log') for n in self.names]
        self.etcd_data = os.path.join(self.test_dir, 'etcd')
        self.etcd_log = os.path.join(self.test_dir, 'etcd.log')

        self.etcd_proc: subprocess.Popen | None = None
        self.procs: list[subprocess.Popen | None] = [None, None, None]

        self.passed = 0
        self.failed = 0

    def check(self, label: str, cond: bool, detail: str = '') -> None:
        if cond:
            logger.info('  PASS  %s', label)
            self.passed += 1
        else:
            logger.error('  FAIL  %s%s', label, f'  ({detail})' if detail else '')
            self.failed += 1
            if self.failed >= 4 and not self.keep_data:
                self._dump_logs()
                raise SystemExit(1)

    def _dump_logs(self) -> None:
        for path in list(self.logs) + [self.etcd_log]:
            if not os.path.isfile(path):
                continue
            logger.info('--- %s (last 50) ---', path)
            try:
                with open(path) as f:
                    for line in f.readlines()[-50:]:
                        sys.stderr.write(line)
            except Exception:
                pass
        for name, data in zip(self.names, self.data_dirs):
            if not os.path.isdir(data):
                continue
            for fn in os.listdir(data):
                if fn.endswith('.err'):
                    path = os.path.join(data, fn)
                    logger.info('--- %s (last 30) ---', path)
                    try:
                        with open(path) as f:
                            for line in f.readlines()[-30:]:
                                sys.stderr.write(line)
                    except Exception:
                        pass

    def setup(self) -> bool:
        if not os.path.isfile(os.path.join(self.bin_dir, 'mysqld')):
            logger.error('mysqld not found in %s', self.bin_dir)
            return False
        if not os.path.isfile(os.path.join(self.plugin_dir, 'group_replication.so')):
            logger.error('group_replication.so not found in %s', self.plugin_dir)
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
        os.environ['PYTHONPATH'] = REPO_ROOT + os.pathsep + os.environ.get('PYTHONPATH', '')

        self.cleanup(kill_only=True)
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)
        os.makedirs(self.test_dir, exist_ok=True)
        os.makedirs(self.etcd_data, exist_ok=True)
        for d in self.data_dirs:
            os.makedirs(d, exist_ok=True)

        for i, name in enumerate(self.names):
            self._write_config(i)

        logger.info('=== Configuration ===')
        logger.info('  group_name: %s', self.group_name)
        logger.info('  test_dir:   %s', self.test_dir)
        logger.info('  etcd:       127.0.0.1:%d', self.etcd_port)
        for i, name in enumerate(self.names):
            logger.info('  %s: mysql=%d mgr=%d api=%d',
                        name, self.ports[i], self.mgr_ports[i], self.api_ports[i])
        return True

    def _write_config(self, idx: int) -> None:
        with open(self.cfgs[idx], 'w') as f:
            f.write(NODE_YAML.format(
                name=self.names[idx],
                data_dir=self.data_dirs[idx],
                bin_dir=self.bin_dir,
                plugin_dir=self.plugin_dir,
                mysql_port=self.ports[idx],
                mgr_port=self.mgr_ports[idx],
                api_port=self.api_ports[idx],
                server_id=idx + 1,
                etcd_port=self.etcd_port,
                group_name=self.group_name,
                seeds=self.seeds,
            ))

    def cleanup(self, kill_only: bool = False) -> None:
        for proc in list(self.procs) + [self.etcd_proc]:
            if proc and proc.poll() is None:
                try:
                    proc.send_signal(signal.SIGTERM)
                except Exception:
                    pass
        time.sleep(1)
        for proc in list(self.procs) + [self.etcd_proc]:
            if proc and proc.poll() is None:
                try:
                    proc.kill()
                except Exception:
                    pass

        ports = list(self.ports) + list(self.mgr_ports) + list(self.api_ports)
        ports += [self.etcd_port, self.etcd_port + 1]
        for port in ports:
            _kill_port(port)

        for pattern in (f'mysqld.*{os.path.basename(self.test_dir)}',
                        f'patroni.*{os.path.basename(self.test_dir)}'):
            try:
                out = subprocess.check_output(
                    ['pgrep', '-f', pattern], text=True, stderr=subprocess.DEVNULL)
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
            '--name', 'mysql-mgr-ha-etcd',
            '--data-dir', self.etcd_data,
            '--listen-client-urls', f'http://127.0.0.1:{self.etcd_port}',
            '--advertise-client-urls', f'http://127.0.0.1:{self.etcd_port}',
            '--listen-peer-urls', f'http://127.0.0.1:{self.etcd_port + 1}',
            '--initial-advertise-peer-urls', f'http://127.0.0.1:{self.etcd_port + 1}',
            '--initial-cluster', f'mysql-mgr-ha-etcd=http://127.0.0.1:{self.etcd_port + 1}',
            '--initial-cluster-token', 'mysql-mgr-patroni-ha',
            '--initial-cluster-state', 'new',
        ]
        logf = open(self.etcd_log, 'w')
        self.etcd_proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT)
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                subprocess.check_call(
                    ['etcdctl', f'--endpoints=http://127.0.0.1:{self.etcd_port}',
                     'endpoint', 'health'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
                logger.info('  etcd healthy on :%d', self.etcd_port)
                return
            except Exception:
                time.sleep(0.5)
        raise RuntimeError('etcd failed to become healthy')

    def start_patroni(self, idx: int) -> subprocess.Popen:
        logf = open(self.logs[idx], 'w')
        proc = subprocess.Popen(
            [sys.executable, '-m', 'patroni', self.cfgs[idx]],
            stdout=logf, stderr=subprocess.STDOUT,
            cwd=REPO_ROOT,
            env=os.environ.copy(),
        )
        self.procs[idx] = proc
        return proc

    def wait_role(self, api_port: int, roles: set[str],
                  timeout: float | None = None) -> dict | None:
        url = f'http://127.0.0.1:{api_port}/patroni'
        deadline = time.time() + (timeout or self.timeout)
        last = None
        while time.time() < deadline:
            last = http_get_json(url)
            if last and last.get('state') == 'running' and last.get('role') in roles:
                return last
            time.sleep(1)
        return last

    def mysql_query(self, port: int, sql: str) -> str:
        cmd = [
            os.path.join(self.bin_dir, 'mysql'),
            '-h127.0.0.1', f'-P{port}', '-uroot', '-N', '-B', '-e', sql,
        ]
        return subprocess.check_output(cmd, text=True, timeout=30).strip()

    def wait_mysql(self, port: int, timeout: float = 60) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self.mysql_query(port, 'SELECT 1')
                return True
            except Exception:
                time.sleep(1)
        return False

    def mgr_online_count(self, port: int) -> int:
        try:
            out = self.mysql_query(
                port,
                "SELECT COUNT(*) FROM performance_schema.replication_group_members "
                "WHERE MEMBER_STATE='ONLINE'")
            return int(out or 0)
        except Exception:
            return 0

    def mgr_role_state(self, port: int) -> tuple[str, str]:
        try:
            out = self.mysql_query(
                port,
                "SELECT MEMBER_ROLE, MEMBER_STATE "
                "FROM performance_schema.replication_group_members "
                "WHERE MEMBER_ID = @@server_uuid "
                "  AND MEMBER_STATE NOT IN ('OFFLINE','ERROR')")
            if not out:
                return '', ''
            parts = out.split('\t')
            return (parts[0] if parts else ''), (parts[1] if len(parts) > 1 else '')
        except Exception:
            return '', ''

    def wait_mgr_online(self, port: int, count: int, timeout: float | None = None) -> bool:
        deadline = time.time() + (timeout or self.timeout)
        while time.time() < deadline:
            if self.mgr_online_count(port) >= count:
                return True
            time.sleep(2)
        return False

    def wait_mgr_primary(self, port: int, timeout: float | None = None) -> bool:
        deadline = time.time() + (timeout or self.timeout)
        while time.time() < deadline:
            role, state = self.mgr_role_state(port)
            if role == 'PRIMARY' and state == 'ONLINE':
                return True
            time.sleep(1)
        return False

    def gtid_executed(self, port: int) -> str:
        try:
            return self.mysql_query(port, 'SELECT @@GLOBAL.gtid_executed')
        except Exception:
            return ''

    def log_contains(self, idx: int, needle: str) -> bool:
        path = self.logs[idx]
        if not os.path.isfile(path):
            return False
        try:
            with open(path) as f:
                return needle in f.read()
        except Exception:
            return False

    def wait_log(self, idx: int, needle: str, timeout: float | None = None) -> bool:
        deadline = time.time() + (timeout or self.timeout)
        while time.time() < deadline:
            if self.log_contains(idx, needle):
                return True
            time.sleep(1)
        return False

    def run(self) -> int:
        logger.info('=' * 60)
        logger.info('Patroni + etcd3 + 3-node MGR HA E2E')
        logger.info('=' * 60)
        if not self.setup():
            return 1

        try:
            self.start_etcd()

            # --- Phase 1: primary ---
            logger.info('\n=== Phase 1: Start mysql0 (Patroni bootstrap + MGR) ===')
            self.start_patroni(0)
            info0 = self.wait_role(self.api_ports[0], PRIMARY_ROLES)
            self.check('mysql0 REST primary/mgr_primary',
                       bool(info0 and info0.get('role') in PRIMARY_ROLES), f'got={info0}')
            self.check('mysql0 MySQL ready', self.wait_mysql(self.ports[0]))
            # Patroni HA loop should bootstrap MGR on the lock holder.
            self.check('mysql0 becomes MGR PRIMARY ONLINE',
                       self.wait_mgr_primary(self.ports[0]),
                       f'state={self.mgr_role_state(self.ports[0])}')
            self.check('patroni0 log: bootstrapped MGR',
                       self.wait_log(0, 'bootstrapped MGR group', timeout=30)
                       or self.log_contains(0, 'MGR group bootstrapped'),
                       'bootstrap message not found (may still be OK if ONLINE)')

            # --- Phase 2: joiners ---
            logger.info('\n=== Phase 2: Start mysql1/mysql2 joiners ===')
            # Stagger joiners slightly so they don't stampede clone/rejoin.
            self.start_patroni(1)
            time.sleep(5)
            self.start_patroni(2)
            self.check('group reaches 3 ONLINE',
                       self.wait_mgr_online(self.ports[0], 3, timeout=max(self.timeout, 300)),
                       f'count={self.mgr_online_count(self.ports[0])}')
            for i in (1, 2):
                role, state = self.mgr_role_state(self.ports[i])
                self.check(f'{self.names[i]} SECONDARY ONLINE',
                           role == 'SECONDARY' and state == 'ONLINE',
                           f'role={role} state={state}')
                info = self.wait_role(self.api_ports[i], SECONDARY_ROLES | PRIMARY_ROLES,
                                      timeout=60)
                # Joiner REST role may lag; MGR membership is the source of truth.
                logger.info('  %s REST: %s', self.names[i],
                            {k: (info or {}).get(k) for k in ('state', 'role')})

            # --- Phase 3: write + replicate ---
            logger.info('\n=== Phase 3: Write on primary, verify replicas ===')
            self.mysql_query(
                self.ports[0],
                "CREATE DATABASE IF NOT EXISTS mgr_ha; "
                "CREATE TABLE IF NOT EXISTS mgr_ha.t1 (id INT PRIMARY KEY, v VARCHAR(64)); "
                "INSERT INTO mgr_ha.t1 VALUES (1,'a'),(2,'b') "
                "ON DUPLICATE KEY UPDATE v=VALUES(v)")
            deadline = time.time() + 60
            ok = False
            while time.time() < deadline:
                try:
                    c1 = self.mysql_query(self.ports[1], 'SELECT COUNT(*) FROM mgr_ha.t1')
                    c2 = self.mysql_query(self.ports[2], 'SELECT COUNT(*) FROM mgr_ha.t1')
                    if c1 == '2' and c2 == '2':
                        ok = True
                        break
                except Exception:
                    pass
                time.sleep(1)
            self.check('replicas have 2 rows', ok)

            # --- Phase 4: majority loss (freeze Patroni HA loops) ---
            logger.info('\n=== Phase 4: STOP GR on all (majority loss) ===')
            # Freeze Patroni so it cannot immediately re-bootstrap/rejoin before
            # we advance GTID on mysql2 (the scenario under test).
            for proc in self.procs:
                if proc and proc.poll() is None:
                    proc.send_signal(signal.SIGSTOP)
            time.sleep(1)
            for port in self.ports:
                try:
                    self.mysql_query(port, 'STOP GROUP_REPLICATION')
                except Exception as e:
                    logger.warning('STOP GR on %s: %r', port, e)
            time.sleep(2)
            for i, port in enumerate(self.ports):
                role, state = self.mgr_role_state(port)
                self.check(f'{self.names[i]} MGR inactive after STOP',
                           not role, f'role={role} state={state}')
            for i, proc in enumerate(self.procs):
                alive = bool(proc and proc.poll() is None)
                self.check(f'{self.names[i]} Patroni still alive (stopped)', alive)

            # --- Phase 5: advance GTID only on mysql2 ---
            logger.info('\n=== Phase 5: Advance GTID only on mysql2 ===')
            self.mysql_query(self.ports[2],
                             'SET GLOBAL super_read_only=0; SET GLOBAL read_only=0')
            self.mysql_query(self.ports[2],
                             "INSERT INTO mgr_ha.t1 VALUES (3,'only_on_mysql2'),"
                             "(4,'only_on_mysql2_b')")
            g0 = self.gtid_executed(self.ports[0])
            g1 = self.gtid_executed(self.ports[1])
            g2 = self.gtid_executed(self.ports[2])
            logger.info('GTID mysql0=%s', g0)
            logger.info('GTID mysql1=%s', g1)
            logger.info('GTID mysql2=%s', g2)
            # Prefer GTID_SUBSET when available.
            ahead0 = ahead1 = False
            try:
                ahead0 = self.mysql_query(
                    self.ports[2],
                    f"SELECT GTID_SUBSET('{g0}', @@GLOBAL.gtid_executed) "
                    f"AND NOT GTID_SUBSET(@@GLOBAL.gtid_executed, '{g0}')") == '1'
                ahead1 = self.mysql_query(
                    self.ports[2],
                    f"SELECT GTID_SUBSET('{g1}', @@GLOBAL.gtid_executed) "
                    f"AND NOT GTID_SUBSET(@@GLOBAL.gtid_executed, '{g1}')") == '1'
            except Exception:
                ahead0 = len(g2) > len(g0)
                ahead1 = len(g2) > len(g1)
            self.check('mysql2 GTID ahead of mysql0', ahead0, f'g2={g2} g0={g0}')
            self.check('mysql2 GTID ahead of mysql1', ahead1, f'g2={g2} g1={g1}')

            # --- Phase 6: unfreeze Patroni → GTID election + rejoin ---
            logger.info('\n=== Phase 6: Resume Patroni for GTID election + rejoin ===')
            # Resume mysql2 first and wait until its ahead GTID is in etcd
            # (REST can show live GTID before touch_member updates DCS).
            if self.procs[2] and self.procs[2].poll() is None:
                self.procs[2].send_signal(signal.SIGCONT)
            ahead_uuid = g2.split(',')[0].split(':')[0].strip()
            member_key = (f'/mysql-mgr-ha/mysql-mgr-patroni-ha/members/{self.names[2]}')
            deadline = time.time() + 90
            published = False
            while time.time() < deadline:
                try:
                    out = subprocess.check_output(
                        ['etcdctl', f'--endpoints=http://127.0.0.1:{self.etcd_port}',
                         'get', member_key, '--print-value-only'],
                        text=True, timeout=5)
                    if ahead_uuid and ahead_uuid in out:
                        published = True
                        logger.info('  mysql2 published ahead GTID in etcd')
                        break
                except Exception:
                    pass
                time.sleep(1)
            self.check('mysql2 published ahead GTID to DCS', published,
                       f'want uuid {ahead_uuid!r} in {member_key}')
            # Drop the stale leader lease so mysql2 (still the only running
            # Patroni) can acquire the lock and bootstrap alone.
            try:
                subprocess.check_call(
                    ['etcdctl', f'--endpoints=http://127.0.0.1:{self.etcd_port}',
                     'del', '/mysql-mgr-ha/mysql-mgr-patroni-ha/leader'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
                logger.info('  deleted stale leader key')
            except Exception as e:
                logger.warning('  failed to delete leader key: %r', e)

            # Keep mysql0/mysql1 frozen until mysql2 has the lock + MGR primary
            # advertised in DCS (so peers rejoin instead of bootstrapping).
            bootstrapped = self.wait_log(
                2, 'bootstrapped MGR group after majority loss', timeout=120)
            primary_ok = self.wait_mgr_primary(self.ports[2], timeout=60)
            advertised = False
            deadline = time.time() + 60
            while time.time() < deadline:
                try:
                    leader = subprocess.check_output(
                        ['etcdctl', f'--endpoints=http://127.0.0.1:{self.etcd_port}',
                         'get', '/mysql-mgr-ha/mysql-mgr-patroni-ha/leader',
                         '--print-value-only'],
                        text=True, timeout=5).strip()
                    member = subprocess.check_output(
                        ['etcdctl', f'--endpoints=http://127.0.0.1:{self.etcd_port}',
                         'get', member_key, '--print-value-only'],
                        text=True, timeout=5)
                    if leader == 'mysql2' and 'mgr_primary' in member:
                        advertised = True
                        break
                except Exception:
                    pass
                time.sleep(1)
            self.check('mysql2 bootstrapped alone before peers resume',
                       bootstrapped and primary_ok and advertised,
                       f'log={bootstrapped} primary={primary_ok} dcs={advertised}')

            for idx in (0, 1):
                if self.procs[idx] and self.procs[idx].poll() is None:
                    self.procs[idx].send_signal(signal.SIGCONT)
            time.sleep(2)

            # Peers should rejoin the already-formed group (no second bootstrap).
            rejoined = False
            deadline = time.time() + 120
            while time.time() < deadline:
                if (self.log_contains(0, 'rejoining MGR group')
                        or self.log_contains(1, 'rejoining MGR group')
                        or self.mgr_online_count(self.ports[2]) >= 2):
                    rejoined = True
                    break
                time.sleep(1)
            self.check('peers begin rejoining mysql2 group', rejoined)
            self.check('mysql2 remains MGR PRIMARY ONLINE',
                       self.wait_mgr_primary(self.ports[2], timeout=30),
                       f'state={self.mgr_role_state(self.ports[2])}')
            self.check('group back to 3 ONLINE',
                       self.wait_mgr_online(self.ports[2], 3),
                       f'count={self.mgr_online_count(self.ports[2])}')

            info2 = http_get_json(f'http://127.0.0.1:{self.api_ports[2]}/patroni')
            self.check('mysql2 REST primary/mgr_primary after recovery',
                       bool(info2 and info2.get('role') in PRIMARY_ROLES), f'got={info2}')

            # --- Phase 7: catch-up ---
            logger.info('\n=== Phase 7: Verify catch-up + post-recovery write ===')
            deadline = time.time() + 90
            ok = False
            while time.time() < deadline:
                try:
                    counts = [
                        self.mysql_query(p, 'SELECT COUNT(*) FROM mgr_ha.t1')
                        for p in self.ports
                    ]
                    if counts == ['4', '4', '4']:
                        ok = True
                        break
                except Exception:
                    pass
                time.sleep(2)
            self.check('all nodes have 4 rows after rejoin', ok)

            self.mysql_query(self.ports[2],
                             "INSERT INTO mgr_ha.t1 VALUES (5,'after_rejoin')")
            deadline = time.time() + 60
            ok = False
            while time.time() < deadline:
                try:
                    if (self.mysql_query(self.ports[0],
                                         'SELECT v FROM mgr_ha.t1 WHERE id=5')
                            == 'after_rejoin'):
                        ok = True
                        break
                except Exception:
                    pass
                time.sleep(1)
            self.check('post-rejoin write replicates to mysql0', ok)

        except SystemExit:
            pass
        except Exception:
            logger.exception('Unexpected error')
            self.failed += 1
            self._dump_logs()
        finally:
            if self.failed and self.keep_data:
                self._dump_logs()
            self.cleanup(kill_only=self.keep_data)
            if self.keep_data:
                logger.info('Preserved data at %s', self.test_dir)

        total = self.passed + self.failed
        logger.info('\n' + '=' * 60)
        logger.info('=== Results: %d/%d passed, %d failed ===',
                    self.passed, total, self.failed)
        logger.info('=' * 60)
        return 0 if self.failed == 0 else 1


if __name__ == '__main__':
    sys.exit(MgrPatroniHATest(parse_args()).run())
