#!/usr/bin/env python3
"""Handler-level xtrabackup clone integration test.

Requires Percona XtraBackup matching the MySQL major.minor version
(this environment: xtrabackup 8.0.35 + MySQL 8.0.35).

Usage:
  MYSQL_BASE=/home/wslu/work/mysql/mysql80-debug python3 integration-tests/test_mysql_xtrabackup.py
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import signal
import subprocess
import sys
import time

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger('mysql_xtrabackup_test')

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description='MySQL xtrabackup clone integration test')
    p.add_argument('--mysql-base', default=os.environ.get('MYSQL_BASE', '/usr/local/mysql'))
    p.add_argument('--test-dir', default=os.environ.get('MYSQL_XB_TEST_DIR',
                                                         '/tmp/patroni_mysql_xtrabackup'))
    p.add_argument('--p0-port', type=int, default=int(os.environ.get('MYSQL_XB_P0_PORT', 34207)))
    p.add_argument('--p1-port', type=int, default=int(os.environ.get('MYSQL_XB_P1_PORT', 34208)))
    p.add_argument('--keep-data', action='store_true',
                   default=bool(int(os.environ.get('MYSQL_KEEP_DATA', '0'))))
    return p.parse_args()


def _kill_port(port: int) -> None:
    try:
        out = subprocess.check_output(['fuser', f'{port}/tcp'], stderr=subprocess.DEVNULL, timeout=5)
        for pid in out.decode().split():
            try:
                os.kill(int(pid), signal.SIGKILL)
            except Exception:
                pass
    except Exception:
        pass


def make_config(name: str, data_dir: str, port: int, server_id: int, mysql_base: str) -> dict:
    return {
        'name': name,
        'scope': 'mysql-xb-test',
        'data_dir': data_dir,
        'config_dir': data_dir,
        'listen': f'127.0.0.1:{port}',
        'connect_address': f'127.0.0.1:{port}',
        'port': port,
        'server_id': server_id,
        'bin_dir': f'{mysql_base}/bin',
        'create_replica_methods': ['xtrabackup'],
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


class XtraBackupTest:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.mysql_base = args.mysql_base
        self.test_dir = args.test_dir
        self.p0_port = args.p0_port
        self.p1_port = args.p1_port
        self.keep_data = args.keep_data
        self.p0_data = os.path.join(self.test_dir, 'p0')
        self.p1_data = os.path.join(self.test_dir, 'p1')
        self.passed = 0
        self.failed = 0
        self.MySQL = None
        self.Member = None

    def check(self, label: str, cond: bool, detail: str = '') -> None:
        if cond:
            logger.info('  PASS  %s', label)
            self.passed += 1
        else:
            logger.error('  FAIL  %s%s', label, f'  ({detail})' if detail else '')
            self.failed += 1

    def clean(self) -> None:
        for port in (self.p0_port, self.p1_port):
            _kill_port(port)
        time.sleep(0.5)
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)
        # Also wipe leftover xtrabackup temp dirs next to data dirs
        self._rm_quiet(self.p1_data + '.xtrabackup_tmp')

    @staticmethod
    def _rm_quiet(path: str) -> None:
        if os.path.exists(path):
            shutil.rmtree(path, ignore_errors=True)

    def setup(self) -> bool:
        if not os.path.isfile(os.path.join(self.mysql_base, 'bin', 'mysqld')):
            logger.error('mysqld not found under %s', self.mysql_base)
            return False
        xb = shutil.which('xtrabackup') or '/usr/bin/xtrabackup'
        if not os.path.isfile(xb):
            logger.error('xtrabackup not found in PATH')
            return False
        ver = subprocess.run([xb, '--version'], capture_output=True, text=True)
        logger.info('xtrabackup: %s', (ver.stderr or ver.stdout).strip().split('\n')[0])
        os.environ['PATH'] = f"{self.mysql_base}/bin:{os.environ.get('PATH', '')}"
        sys.path.insert(0, REPO_ROOT)
        from patroni.mysql import MySQL
        from patroni.dcs import Member
        self.MySQL = MySQL
        self.Member = Member
        self.clean()
        os.makedirs(self.p0_data, exist_ok=True)
        os.makedirs(self.p1_data, exist_ok=True)
        return True

    def run(self) -> int:
        logger.info('=' * 60)
        logger.info('MySQL xtrabackup Clone Integration Test')
        logger.info('=' * 60)
        if not self.setup():
            return 1
        p0 = p1 = None
        try:
            logger.info('\n=== Bootstrap primary ===')
            p0 = self.MySQL(make_config('p0', self.p0_data, self.p0_port, 1, self.mysql_base))
            self.check('bootstrap primary', p0.bootstrap.bootstrap({}))
            self.check('post_bootstrap (grants BACKUP_ADMIN)',
                       bool(p0.bootstrap.post_bootstrap({})))
            p0.set_role('primary')
            p0.set_state('running')

            p0._query("CREATE DATABASE IF NOT EXISTS xb_test")
            p0._query("CREATE TABLE xb_test.t1 (id INT PRIMARY KEY, v VARCHAR(32))")
            p0._query("INSERT INTO xb_test.t1 VALUES (1, 'hello'), (2, 'world')")
            cnt = p0._query_one("SELECT COUNT(*) FROM xb_test.t1")
            self.check('primary has 2 rows', bool(cnt and cnt[0] == 2), f'cnt={cnt}')

            logger.info('\n=== Clone via xtrabackup ===')
            p1 = self.MySQL(make_config('p1', self.p1_data, self.p1_port, 2, self.mysql_base))
            xb_path = p1.config.get_xtrabackup_path()
            self.check('xtrabackup path resolves', os.path.isfile(xb_path), xb_path)

            leader = self.Member(0, 'p0', 0, {'conn_url': f'mysql://127.0.0.1:{self.p0_port}'})
            ok = p1.bootstrap.clone(leader)
            self.check('xtrabackup clone() returns True', ok)
            if not ok:
                return 1 if self.failed else 0

            self.check('replica is_running after clone', p1.is_running())
            self.check('no leftover xtrabackup_tmp',
                       not os.path.exists(self.p1_data + '.xtrabackup_tmp'))
            self.check('auto.cnf present after start',
                       os.path.isfile(os.path.join(self.p1_data, 'auto.cnf')))

            rows = p1._query("SELECT id, v FROM xb_test.t1 ORDER BY id")
            self.check('cloned data has 2 rows', bool(rows and len(rows) == 2),
                       f'got={rows}')
            if rows:
                self.check('cloned content', rows[0][1] == 'hello' and rows[1][1] == 'world')

            p0_uuid = p0.sysid
            p1_uuid = p1.sysid
            self.check('replica server_uuid differs from primary',
                       p0_uuid and p1_uuid and p0_uuid != p1_uuid,
                       f'p0={p0_uuid} p1={p1_uuid}')

            logger.info('\n=== Configure GTID replication after physical clone ===')
            p1.follow(leader)
            time.sleep(2)
            self.check('replica streaming', p1.replication_state() == 'streaming',
                       f'state={p1.replication_state()}')

            p0._query("INSERT INTO xb_test.t1 VALUES (3, 'replicated')")
            deadline = time.time() + 30
            ok_row = False
            while time.time() < deadline:
                try:
                    r = p1._query_one("SELECT v FROM xb_test.t1 WHERE id=3")
                    if r and r[0] == 'replicated':
                        ok_row = True
                        break
                except Exception:
                    pass
                time.sleep(1)
            self.check('live replication after xtrabackup clone', ok_row)

        except Exception:
            logger.exception('Unexpected error')
            self.failed += 1
        finally:
            for h in (p1, p0):
                if h is not None:
                    try:
                        h.stop()
                    except Exception:
                        pass
            if not self.keep_data:
                self.clean()
            else:
                for port in (self.p0_port, self.p1_port):
                    _kill_port(port)

        total = self.passed + self.failed
        logger.info('\n' + '=' * 60)
        logger.info('=== Results: %d/%d passed, %d failed ===', self.passed, total, self.failed)
        logger.info('=' * 60)
        return 0 if self.failed == 0 else 1


if __name__ == '__main__':
    sys.exit(XtraBackupTest(parse_args()).run())
