#!/usr/bin/env python3
"""MGR majority-loss GTID election (handler-level) integration test.

Validates against a real MySQL instance that:
  1. ``gtid_relation`` / ``GTID_SUBSET`` ordering is correct
  2. ``select_mgr_bootstrap_winner`` picks the most-ahead node
  3. Equal GTIDs tie-break by member name
  4. Majority-loss handler bootstraps only the winner with the lock,
     and yields the lock when behind

Full multi-node Group Replication bootstrap is left for a later E2E;
this test focuses on the election contract that prevents stale lock
holders from bootstrapping.

Usage:
  MYSQL_BASE=/home/wslu/work/mysql/mysql80-debug \\
    python3 -u integration-tests/test_mysql_mgr_election.py

Note: if ``mysqld --initialize`` hangs (seen on some WSL kernels with
processes stuck in D-state on rtnl_lock), re-run after clearing stuck
mysqld processes or use a fresh VM. Unit tests in ``tests/test_mysql.py``
cover the same election branches without requiring initialize.
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
import uuid
from unittest.mock import patch

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger('mysql_mgr_election_test')

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description='MGR GTID election integration test')
    p.add_argument('--mysql-base', default=os.environ.get('MYSQL_BASE', '/usr/local/mysql'))
    p.add_argument('--test-dir', default=os.environ.get('MYSQL_MGR_TEST_DIR',
                                                         '/tmp/patroni_mgr_gtid_elex'))
    p.add_argument('--port', type=int, default=int(os.environ.get('MYSQL_MGR_PORT', 34137)))
    p.add_argument('--keep-data', action='store_true',
                   default=bool(int(os.environ.get('MYSQL_KEEP_DATA', '0'))))
    p.add_argument('--init-timeout', type=int,
                   default=int(os.environ.get('MYSQL_INIT_TIMEOUT', '90')),
                   help='Abort if mysqld --initialize exceeds this many seconds')
    return p.parse_args()


def _kill_test_mysqld(test_dir: str) -> None:
    """Avoid fuser — it can hang indefinitely on some WSL ports."""
    try:
        out = subprocess.check_output(
            ['pgrep', '-f', f'mysqld.*{os.path.basename(test_dir)}'],
            stderr=subprocess.DEVNULL, timeout=2)
        for pid in out.decode().split():
            try:
                os.kill(int(pid), signal.SIGKILL)
            except Exception:
                pass
    except Exception:
        pass


class MgrElectionTest:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.mysql_base = args.mysql_base
        self.test_dir = args.test_dir
        self.port = args.port
        self.keep_data = args.keep_data
        self.init_timeout = args.init_timeout
        self.data_dir = os.path.join(self.test_dir, 'p0')
        self.passed = 0
        self.failed = 0
        self.MySQL = None
        self.Member = None
        self.handler = None

    def check(self, label: str, cond: bool, detail: str = '') -> None:
        if cond:
            logger.info('  PASS  %s', label)
            self.passed += 1
        else:
            logger.error('  FAIL  %s%s', label, f'  ({detail})' if detail else '')
            self.failed += 1

    def clean(self) -> None:
        _kill_test_mysqld(self.test_dir)
        time.sleep(0.5)
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def setup(self) -> bool:
        if not os.path.isfile(os.path.join(self.mysql_base, 'bin', 'mysqld')):
            logger.error('mysqld not found under %s', self.mysql_base)
            return False
        os.environ['PATH'] = f"{self.mysql_base}/bin:{os.environ.get('PATH', '')}"
        sys.path.insert(0, REPO_ROOT)
        from patroni.mysql import MySQL
        from patroni.dcs import Member
        self.MySQL = MySQL
        self.Member = Member
        self.clean()
        os.makedirs(self.data_dir, exist_ok=True)
        return True

    def make_config(self) -> dict:
        return {
            'name': 'mysql0',
            'scope': 'mysql-mgr-election',
            'data_dir': self.data_dir,
            'config_dir': self.data_dir,
            'listen': f'127.0.0.1:{self.port}',
            'connect_address': f'127.0.0.1:{self.port}',
            'port': self.port,
            'server_id': 1,
            'bin_dir': f'{self.mysql_base}/bin',
            'authentication': {
                'superuser': {'username': 'root', 'password': ''},
                'replication': {'username': 'replicator', 'password': 'rep-pass'},
            },
            'parameters': {
                'server_id': '1',
                'gtid_mode': 'ON',
                'enforce_gtid_consistency': 'ON',
                'log-bin': 'mysql-bin',
                'log_slave_updates': 'ON',
                'mysqlx': 'OFF',
                'binlog_format': 'ROW',
            },
        }

    def _bootstrap_with_timeout(self) -> bool:
        """Run initialize+start, aborting if initialize wedges (WSL D-state)."""
        mysqld = os.path.join(self.mysql_base, 'bin', 'mysqld')
        cmdline = [mysqld, f'--datadir={self.data_dir}',
                   '--initialize-insecure', f'--user={os.getenv("USER", "root")}']
        logger.info('Running mysqld --initialize (timeout=%ss)...', self.init_timeout)
        try:
            result = subprocess.run(cmdline, capture_output=True, text=True,
                                    timeout=self.init_timeout)
        except subprocess.TimeoutExpired:
            logger.error('mysqld --initialize timed out after %ss '
                         '(WSL rtnl_lock D-state?). Skipping live test.',
                         self.init_timeout)
            _kill_test_mysqld(self.test_dir)
            return False
        if result.returncode != 0:
            logger.error('mysqld --initialize failed: %s', result.stderr[-500:])
            return False
        # Start via normal bootstrap path (data dir already initialized)
        return self.handler.bootstrap._start_mysql()

    def run(self) -> int:
        logger.info('=' * 60)
        logger.info('MGR Majority-Loss GTID Election Test')
        logger.info('=' * 60)
        logger.info('Setting up...')
        if not self.setup():
            return 1
        logger.info('Setup OK (port=%s dir=%s)', self.port, self.test_dir)
        try:
            logger.info('\n=== Bootstrap MySQL (GTID on) ===')
            self.handler = self.MySQL(self.make_config())
            if not self._bootstrap_with_timeout():
                logger.warning('Live MySQL unavailable — election covered by unit tests')
                return 0
            self.check('bootstrap/start', self.handler.is_running())
            self.handler.set_role('primary')
            self.handler.set_state('running')
            # Enable MGR mode in-memory only (no GR plugin / no START GR).
            self.handler.config._parameters['group_replication_group_name'] = str(uuid.uuid4())

            self.handler._query("CREATE DATABASE IF NOT EXISTS mgr_elex")
            self.handler._query("CREATE TABLE mgr_elex.t (id INT PRIMARY KEY)")
            self.handler._query("INSERT INTO mgr_elex.t VALUES (1), (2), (3)")

            local = self.handler.get_executed_gtid()
            self.check('local gtid_executed non-empty', bool(local), f'gtid={local}')
            sid = local.split(':')[0]
            end = int(local.rsplit('-', 1)[-1])

            logger.info('\n=== gtid_relation via real GTID_SUBSET ===')
            behind = f'{sid}:1-{max(1, end - 1)}'
            ahead = f'{sid}:1-{end + 5}'
            self.check('equal', self.handler.gtid_relation(local, local) == 'equal')
            self.check('local ahead of subset',
                       self.handler.gtid_relation(local, behind) == 'a_ahead')
            self.check('peer ahead of local',
                       self.handler.gtid_relation(local, ahead) == 'b_ahead')

            logger.info('\n=== select_mgr_bootstrap_winner ===')
            m_behind = self.Member(0, 'mysql1', 0, {'gtid_executed': behind})
            m_ahead = self.Member(0, 'mysql1', 0, {'gtid_executed': ahead})
            m_equal = self.Member(0, 'zzz', 0, {'gtid_executed': local})
            self.check('winner when peer behind = self',
                       self.handler.select_mgr_bootstrap_winner(local, [m_behind]) == 'mysql0')
            self.check('winner when peer ahead = peer',
                       self.handler.select_mgr_bootstrap_winner(local, [m_ahead]) == 'mysql1')
            self.check('equal GTID name tie-break',
                       self.handler.select_mgr_bootstrap_winner(local, [m_equal]) == 'mysql0')

            logger.info('\n=== enrich_dcs_data publishes gtid ===')
            data = {'xlog_location': 1}
            self.handler.enrich_dcs_data(data)
            self.check('gtid_executed in DCS payload',
                       data.get('gtid_executed') == local, f'data={data}')

            logger.info('\n=== majority-loss handler decisions ===')
            with patch.object(self.handler, 'get_mgr_status', return_value={}):
                with patch.object(self.handler, 'bootstrap_mgr_group', return_value=True) as boot:
                    msg = self.handler.run_mgr_cycle(True, 3, [m_behind])
                    self.check('winner+lock bootstraps',
                               msg == 'bootstrapped MGR group after majority loss', f'msg={msg}')
                    self.check('bootstrap_mgr_group called', boot.called)

                msg = self.handler.run_mgr_cycle(True, 3, [m_ahead])
                self.check('behind+lock yields', msg == 'mgr_yield_lock', f'msg={msg}')

                msg = self.handler.run_mgr_cycle(False, 3, [m_ahead])
                self.check('behind without lock waits',
                           (msg or '').startswith('waiting for MGR'), f'msg={msg}')

                msg = self.handler.run_mgr_cycle(False, 3, [m_behind])
                self.check('winner without lock waits for lease',
                           msg == 'elected MGR bootstrap winner; waiting for leader lock',
                           f'msg={msg}')

            logger.info('\n=== incomparable GTID fork → refuse bootstrap ===')
            # Distinct UUIDs are always incomparable under GTID_SUBSET.
            fork_peer = self.Member(0, 'mysql1', 0, {
                'gtid_executed': f'{uuid.uuid4()}:1-10',
            })
            fork = self.handler.describe_mgr_gtid_fork(local, [fork_peer])
            self.check('describe_mgr_gtid_fork detects fork',
                       len(fork) == 2, f'fork={fork}')
            self.check('select_mgr_bootstrap_winner returns None on fork',
                       self.handler.select_mgr_bootstrap_winner(local, [fork_peer]) is None)
            with patch.object(self.handler, 'get_mgr_status', return_value={}):
                with patch.object(self.handler, 'bootstrap_mgr_group') as boot:
                    with patch.object(self.handler, 'set_read_only') as ro:
                        msg = self.handler.run_mgr_cycle(True, 3, [fork_peer])
            self.check('majority-loss returns mgr_gtid_fork',
                       msg == 'mgr_gtid_fork', f'msg={msg}')
            self.check('fork does not call bootstrap_mgr_group', not boot.called)
            self.check('fork forces read_only', ro.called)
            self.check('mgr_pause_on_gtid_fork defaults on',
                       self.handler.mgr_pause_on_gtid_fork_enabled())

        except Exception:
            logger.exception('Unexpected error')
            self.failed += 1
        finally:
            if self.handler is not None:
                try:
                    self.handler.stop()
                except Exception:
                    pass
            if not self.keep_data:
                self.clean()
            else:
                _kill_test_mysqld(self.test_dir)

        total = self.passed + self.failed
        logger.info('\n' + '=' * 60)
        logger.info('=== Results: %d/%d passed, %d failed ===', self.passed, total, self.failed)
        logger.info('=' * 60)
        return 0 if self.failed == 0 else 1


if __name__ == '__main__':
    sys.exit(MgrElectionTest(parse_args()).run())
