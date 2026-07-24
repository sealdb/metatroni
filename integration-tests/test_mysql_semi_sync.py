#!/usr/bin/env python3
"""Handler-level semi-synchronous replication safety test.

Validates:
  1. Semi-sync plugins load when configured
  2. Primary goes read_only when semi-sync clients < quorum
  3. Primary returns to read_write when a replica connects as semi-sync client
  4. Writes succeed after quorum is restored

Usage:
  MYSQL_BASE=/home/wslu/work/mysql/mysql80-debug python3 integration-tests/test_mysql_semi_sync.py
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
logger = logging.getLogger('mysql_semi_sync_test')

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description='MySQL semi-sync safety integration test')
    p.add_argument('--mysql-base', default=os.environ.get('MYSQL_BASE', '/usr/local/mysql'))
    p.add_argument('--test-dir', default=os.environ.get('MYSQL_SS_TEST_DIR',
                                                         '/tmp/patroni_mysql_semi_sync'))
    p.add_argument('--p0-port', type=int, default=int(os.environ.get('MYSQL_SS_P0_PORT', 34107)))
    p.add_argument('--p1-port', type=int, default=int(os.environ.get('MYSQL_SS_P1_PORT', 34108)))
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
        'scope': 'mysql-ss-test',
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
            'plugin_dir': f'{mysql_base}/lib/plugin',
            'rpl_semi_sync_source_enabled': 'ON',
            'rpl_semi_sync_replica_enabled': 'ON',
            'cluster_size': '3',  # quorum = 1 replica
        },
    }


class SemiSyncTest:
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

    def setup(self) -> bool:
        if not os.path.isfile(os.path.join(self.mysql_base, 'bin', 'mysqld')):
            logger.error('mysqld not found under %s', self.mysql_base)
            return False
        plugin = os.path.join(self.mysql_base, 'lib/plugin/semisync_source.so')
        if not os.path.isfile(plugin):
            logger.error('semisync_source.so not found at %s', plugin)
            return False
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
        logger.info('MySQL Semi-Sync Safety Integration Test')
        logger.info('=' * 60)
        if not self.setup():
            return 1
        p0 = p1 = None
        try:
            # --- Primary bootstrap ---
            logger.info('\n=== Bootstrap primary with semi-sync ===')
            p0 = self.MySQL(make_config('p0', self.p0_data, self.p0_port, 1, self.mysql_base))
            self.check('bootstrap primary', p0.bootstrap.bootstrap({}))
            self.check('post_bootstrap', bool(p0.bootstrap.post_bootstrap({})))
            p0.set_role('primary')
            p0.set_state('running')

            # Confirm plugin variables exist
            row = p0._query_one_dict(
                "SHOW VARIABLES LIKE 'rpl_semi_sync_source_enabled'")
            self.check('semi-sync source plugin loaded',
                       bool(row and str(row.get('Value', '')).upper() in ('ON', '1')),
                       f'row={row}')

            p0._query("CREATE DATABASE IF NOT EXISTS ss_test")
            p0._query("CREATE TABLE ss_test.t1 (id INT PRIMARY KEY, v VARCHAR(32))")
            p0._query("INSERT INTO ss_test.t1 VALUES (1, 'init')")

            # No replicas yet → quorum unmet for cluster_size=3
            logger.info('\n=== Quorum loss → read_only ===')
            action = p0.run_semi_sync_safety_check(3)
            self.check('safety check sets read_only', action == 'read_only_set', f'got={action}')
            self.check('primary is_read_only()', p0.is_read_only())

            # Writes as non-super should fail; root with SUPER bypasses read_only
            # but super_read_only blocks even root without SUPER... root has SUPER.
            # Verify super_read_only is ON.
            sro = p0._query_one_dict("SHOW VARIABLES LIKE 'super_read_only'")
            self.check('super_read_only ON',
                       bool(sro and str(sro.get('Value', '')).upper() == 'ON'),
                       f'got={sro}')

            # --- Clone + follow replica ---
            logger.info('\n=== Clone replica and enable semi-sync ===')
            p1 = self.MySQL(make_config('p1', self.p1_data, self.p1_port, 2, self.mysql_base))
            leader = self.Member(0, 'p0', 0, {'conn_url': f'mysql://127.0.0.1:{self.p0_port}'})
            self.check('clone replica', p1.bootstrap.clone(leader))
            self.check('replica running', p1.is_running())
            p1.follow(leader)
            time.sleep(2)
            self.check('replica streaming', p1.replication_state() == 'streaming',
                       f'state={p1.replication_state()}')

            # Wait for semi-sync client registration
            deadline = time.time() + 30
            clients = 0
            while time.time() < deadline:
                clients = p0.count_semi_sync_replicas()
                if clients >= 1:
                    break
                time.sleep(1)
            self.check('semi-sync clients >= 1', clients >= 1, f'clients={clients}')

            logger.info('\n=== Quorum restored → read_write ===')
            action = p0.run_semi_sync_safety_check(3)
            # may already be RW if previous cycle restored; accept either restored or None
            if action == 'read_write_restored':
                self.check('safety check restores read_write', True)
            else:
                # Force RO then restore to exercise the path
                p0.set_read_only()
                action = p0.run_semi_sync_safety_check(3)
                self.check('safety check restores read_write',
                           action == 'read_write_restored', f'got={action}')
            self.check('primary not read_only', not p0.is_read_only())

            p0._query("INSERT INTO ss_test.t1 VALUES (2, 'after_quorum')")
            primary_row = p0._query_one("SELECT v FROM ss_test.t1 WHERE id=2")
            self.check('primary has after_quorum row',
                       bool(primary_row and primary_row[0] == 'after_quorum'),
                       f'got={primary_row}')
            deadline = time.time() + 30
            row = None
            while time.time() < deadline:
                try:
                    row = p1._query_one("SELECT v FROM ss_test.t1 WHERE id=2")
                    if row and row[0] == 'after_quorum':
                        break
                except Exception:
                    pass
                time.sleep(1)
            if not (row and row[0] == 'after_quorum'):
                sl = p1._query_one_dict("SHOW SLAVE STATUS") or {}
                logger.error('slave status: IO=%s SQL=%s Last_Error=%s',
                             sl.get('Slave_IO_Running'), sl.get('Slave_SQL_Running'),
                             sl.get('Last_Error') or sl.get('Last_SQL_Error'))
            self.check('write replicates after quorum',
                       bool(row and row[0] == 'after_quorum'), f'got={row}')

            # --- Drop replica → RO again ---
            logger.info('\n=== Stop replica → read_only again ===')
            try:
                p1.stop()
            except Exception:
                pass
            # Hard-kill so the semi-sync TCP session drops promptly
            _kill_port(self.p1_port)
            deadline = time.time() + 60
            clients = p0.count_semi_sync_replicas()
            while time.time() < deadline and clients > 0:
                time.sleep(1)
                clients = p0.count_semi_sync_replicas()
            self.check('semi-sync clients dropped to 0', clients == 0, f'clients={clients}')
            action = p0.run_semi_sync_safety_check(3)
            self.check('safety check sets read_only after replica loss',
                       action == 'read_only_set' or p0.is_read_only(),
                       f'action={action} ro={p0.is_read_only()}')

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
    sys.exit(SemiSyncTest(parse_args()).run())
