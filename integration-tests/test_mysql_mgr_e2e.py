#!/usr/bin/env python3
"""Three-node MySQL Group Replication E2E: majority-loss GTID election.

Flow:
  1. Bootstrap 3 mysqld instances with shared MGR group config
  2. Start GR on n0 (bootstrap), join n1/n2
  3. Write on primary; verify replication across group
  4. STOP GROUP_REPLICATION on all nodes (majority loss)
  5. Advance GTID only on n2 (local writes while GR is down)
  6. Run Patroni election: n2 (winner + lock) bootstraps; n0/n1 rejoin
  7. Verify 3 ONLINE members and data catch-up

Usage:
  MYSQL_BASE=/home/wslu/work/mysql/mysql80-debug PYTHONPATH=. \\
    python3 -u integration-tests/test_mysql_mgr_e2e.py
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

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger('mysql_mgr_e2e')

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description='3-node MGR majority-loss E2E')
    p.add_argument('--mysql-base', default=os.environ.get('MYSQL_BASE', '/usr/local/mysql'))
    p.add_argument('--test-dir', default=os.environ.get('MYSQL_MGR_E2E_DIR',
                                                         '/tmp/patroni_mgr_e2e'))
    p.add_argument('--base-port', type=int,
                   default=int(os.environ.get('MYSQL_MGR_E2E_PORT', 34407)))
    p.add_argument('--timeout', type=int, default=int(os.environ.get('MYSQL_TIMEOUT', 120)))
    p.add_argument('--keep-data', action='store_true',
                   default=bool(int(os.environ.get('MYSQL_KEEP_DATA', '0'))))
    return p.parse_args()


def _kill_test_mysqld(test_dir: str) -> None:
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


class MgrE2ETest:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.mysql_base = args.mysql_base
        self.test_dir = args.test_dir
        self.base_port = args.base_port
        self.timeout = args.timeout
        self.keep_data = args.keep_data
        self.group_name = str(uuid.uuid4())
        self.passed = 0
        self.failed = 0
        self.MySQL = None
        self.Member = None
        self.nodes: list = []  # list of MySQL handlers
        self.ports = [self.base_port + i for i in range(3)]
        self.mgr_ports = [p + 10 for p in self.ports]
        self.names = ['n0', 'n1', 'n2']

    def check(self, label: str, cond: bool, detail: str = '') -> None:
        if cond:
            logger.info('  PASS  %s', label)
            self.passed += 1
        else:
            logger.error('  FAIL  %s%s', label, f'  ({detail})' if detail else '')
            self.failed += 1
            if self.failed >= 5 and not self.keep_data:
                self._dump_logs()
                raise SystemExit(1)

    def _dump_logs(self) -> None:
        for name in self.names:
            err = os.path.join(self.test_dir, name, f'{name}.err')
            # hostname.err is used by ConfigHandler
            data = os.path.join(self.test_dir, name)
            if not os.path.isdir(data):
                continue
            for fn in os.listdir(data):
                if fn.endswith('.err'):
                    path = os.path.join(data, fn)
                    logger.info('--- %s (last 40) ---', path)
                    try:
                        with open(path) as f:
                            for line in f.readlines()[-40:]:
                                sys.stderr.write(line)
                    except Exception:
                        pass

    def clean(self) -> None:
        _kill_test_mysqld(self.test_dir)
        time.sleep(1)
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def setup(self) -> bool:
        if not os.path.isfile(os.path.join(self.mysql_base, 'bin', 'mysqld')):
            logger.error('mysqld not found under %s', self.mysql_base)
            return False
        plugin = os.path.join(self.mysql_base, 'lib/plugin/group_replication.so')
        if not os.path.isfile(plugin):
            logger.error('group_replication.so not found at %s', plugin)
            return False
        os.environ['PATH'] = f"{self.mysql_base}/bin:{os.environ.get('PATH', '')}"
        sys.path.insert(0, REPO_ROOT)
        from patroni.mysql import MySQL
        from patroni.dcs import Member
        self.MySQL = MySQL
        self.Member = Member
        self.clean()
        for name in self.names:
            os.makedirs(os.path.join(self.test_dir, name), exist_ok=True)
        logger.info('group_name=%s ports=%s mgr_ports=%s',
                     self.group_name, self.ports, self.mgr_ports)
        return True

    def make_config(self, idx: int) -> dict:
        name = self.names[idx]
        port = self.ports[idx]
        data_dir = os.path.join(self.test_dir, name)
        seeds = ','.join(f'127.0.0.1:{p}' for p in self.mgr_ports)
        return {
            'name': name,
            'scope': 'mysql-mgr-e2e',
            'data_dir': data_dir,
            'config_dir': data_dir,
            'listen': f'127.0.0.1:{port}',
            'connect_address': f'127.0.0.1:{port}',
            'port': port,
            'server_id': idx + 1,
            'bin_dir': f'{self.mysql_base}/bin',
            'authentication': {
                'superuser': {'username': 'root', 'password': ''},
                'replication': {'username': 'replicator', 'password': 'rep-pass'},
            },
            'parameters': {
                'server_id': str(idx + 1),
                'gtid_mode': 'ON',
                'enforce_gtid_consistency': 'ON',
                'log-bin': 'mysql-bin',
                'log_slave_updates': 'ON',
                'binlog_format': 'ROW',
                'mysqlx': 'OFF',
                'plugin_dir': f'{self.mysql_base}/lib/plugin',
                'group_replication_group_name': self.group_name,
                'loose-group_replication_start_on_boot': 'OFF',
                'loose-group_replication_bootstrap_group': 'OFF',
                'loose-group_replication_single_primary_mode': 'ON',
                'loose-group_replication_local_address': f'127.0.0.1:{self.mgr_ports[idx]}',
                'loose-group_replication_group_seeds': seeds,
                'loose-group_replication_ip_allowlist': '127.0.0.1/32,::1/128',
                'loose-group_replication_recovery_use_ssl': 'OFF',
                'loose-binlog_transaction_dependency_tracking': 'WRITESET',
                'report_host': '127.0.0.1',
                'report_port': str(port),
                'cluster_size': '3',
            },
        }

    def wait_mgr_role(self, node, role: str, timeout: float | None = None) -> bool:
        deadline = time.time() + (timeout or self.timeout)
        while time.time() < deadline:
            st = node.get_mgr_status()
            if st.get('role') == role and st.get('state') == 'ONLINE':
                return True
            time.sleep(1)
        return False

    def wait_mgr_online_count(self, node, count: int, timeout: float | None = None) -> bool:
        deadline = time.time() + (timeout or self.timeout)
        while time.time() < deadline:
            try:
                rows = node._query(
                    "SELECT COUNT(*) FROM performance_schema.replication_group_members "
                    "WHERE MEMBER_STATE='ONLINE'"
                )
                if rows and int(rows[0][0]) >= count:
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False

    def dcs_members(self) -> list:
        """Build DCS-like Member list from live GTIDs / roles."""
        members = []
        for n in self.nodes:
            data = {
                'conn_url': n.connection_string,
                'gtid_executed': n.get_executed_gtid(),
                'role': n.role,
                'state': n.state,
            }
            members.append(self.Member(0, n.name, 0, data))
        return members

    def run(self) -> int:
        logger.info('=' * 60)
        logger.info('3-node MGR Majority-Loss GTID Election E2E')
        logger.info('=' * 60)
        if not self.setup():
            return 1

        try:
            # --- Phase 1: bootstrap 3 mysqld ---
            logger.info('\n=== Phase 1: Bootstrap 3 MySQL instances ===')
            for i, name in enumerate(self.names):
                h = self.MySQL(self.make_config(i))
                ok = h.bootstrap.bootstrap({})
                self.check(f'{name} bootstrap', ok)
                if not ok:
                    self._dump_logs()
                    return 1
                self.check(f'{name} post_bootstrap', bool(h.bootstrap.post_bootstrap({})))
                h.set_role('primary' if i == 0 else 'replica')
                h.set_state('running')
                self.nodes.append(h)

            # --- Phase 2: form MGR group ---
            logger.info('\n=== Phase 2: Form Group Replication ===')
            n0, n1, n2 = self.nodes
            self.check('n0 bootstrap_mgr_group', n0.bootstrap_mgr_group())
            self.check('n0 is PRIMARY ONLINE',
                       self.wait_mgr_role(n0, 'PRIMARY'), f'status={n0.get_mgr_status()}')

            self.check('n1 rejoin', n1.rejoin_mgr_group('127.0.0.1', self.ports[0]))
            self.check('n2 rejoin', n2.rejoin_mgr_group('127.0.0.1', self.ports[0]))
            self.check('group has 3 ONLINE',
                       self.wait_mgr_online_count(n0, 3),
                       f'status={n0.get_mgr_status()}')
            self.check('n1 SECONDARY ONLINE', self.wait_mgr_role(n1, 'SECONDARY'))
            self.check('n2 SECONDARY ONLINE', self.wait_mgr_role(n2, 'SECONDARY'))

            # --- Phase 3: write + replicate ---
            logger.info('\n=== Phase 3: Write on primary, verify replicas ===')
            n0._query("CREATE DATABASE IF NOT EXISTS mgr_e2e")
            n0._query("CREATE TABLE mgr_e2e.t1 (id INT PRIMARY KEY, v VARCHAR(64))")
            n0._query("INSERT INTO mgr_e2e.t1 VALUES (1,'a'), (2,'b')")
            deadline = time.time() + 30
            ok = False
            while time.time() < deadline:
                try:
                    c1 = n1._query_one("SELECT COUNT(*) FROM mgr_e2e.t1")
                    c2 = n2._query_one("SELECT COUNT(*) FROM mgr_e2e.t1")
                    if c1 and c2 and c1[0] == 2 and c2[0] == 2:
                        ok = True
                        break
                except Exception:
                    pass
                time.sleep(1)
            self.check('replicas have 2 rows', ok)

            # --- Phase 4: majority loss ---
            logger.info('\n=== Phase 4: STOP GR on all (majority loss) ===')
            for n in self.nodes:
                try:
                    n._query("STOP GROUP_REPLICATION")
                except Exception as e:
                    logger.warning('%s STOP GR: %r', n.name, e)
            time.sleep(2)
            for n in self.nodes:
                st = n.get_mgr_status()
                self.check(f'{n.name} MGR inactive after STOP', not st, f'status={st}')

            # --- Phase 5: advance GTID only on n2 ---
            logger.info('\n=== Phase 5: Advance GTID only on n2 ===')
            n2.set_read_write()
            n2._query("INSERT INTO mgr_e2e.t1 VALUES (3,'only_on_n2')")
            n2._query("INSERT INTO mgr_e2e.t1 VALUES (4,'only_on_n2_b')")
            g0 = n0.get_executed_gtid()
            g1 = n1.get_executed_gtid()
            g2 = n2.get_executed_gtid()
            logger.info('GTIDs: n0=%s', g0)
            logger.info('GTIDs: n1=%s', g1)
            logger.info('GTIDs: n2=%s', g2)
            self.check('n2 GTID ahead of n0',
                       n2.gtid_relation(g2, g0) == 'a_ahead', f'n2={g2} n0={g0}')
            self.check('n2 GTID ahead of n1',
                       n2.gtid_relation(g2, g1) == 'a_ahead', f'n2={g2} n1={g1}')

            members = self.dcs_members()
            winner = n2.select_mgr_bootstrap_winner(g2, members)
            self.check('election picks n2', winner == 'n2', f'winner={winner}')

            # --- Phase 6: election + bootstrap + rejoin ---
            logger.info('\n=== Phase 6: Winner bootstraps, others rejoin ===')
            # Simulated Patroni cycles
            msg0 = n0.run_mgr_cycle(True, 3, members)  # stale lock on behind node
            self.check('n0 (behind, has_lock) yields',
                       msg0 == 'mgr_yield_lock', f'msg={msg0}')

            msg2 = n2.run_mgr_cycle(False, 3, members)
            self.check('n2 (winner, no lock) waits for lock',
                       msg2 == 'elected MGR bootstrap winner; waiting for leader lock',
                       f'msg={msg2}')

            msg2 = n2.run_mgr_cycle(True, 3, members)
            self.check('n2 (winner + lock) bootstraps',
                       msg2 == 'bootstrapped MGR group after majority loss', f'msg={msg2}')
            self.check('n2 PRIMARY ONLINE after bootstrap',
                       self.wait_mgr_role(n2, 'PRIMARY'), f'status={n2.get_mgr_status()}')

            # Refresh members so n2 is advertised as mgr_primary
            n2.set_role('mgr_primary')
            members = self.dcs_members()

            msg0 = n0.run_mgr_cycle(False, 3, members)
            msg1 = n1.run_mgr_cycle(False, 3, members)
            self.check('n0 rejoins or waits',
                       msg0 in ('rejoining MGR group after majority loss',
                                'waiting for MGR bootstrap winner (n2)')
                       or (msg0 or '').startswith('rejoining'),
                       f'msg={msg0}')
            self.check('n1 rejoins or waits',
                       msg1 in ('rejoining MGR group after majority loss',
                                'waiting for MGR bootstrap winner (n2)')
                       or (msg1 or '').startswith('rejoining'),
                       f'msg={msg1}')

            # If cycle only waited, force rejoin with known primary
            for n, msg in ((n0, msg0), (n1, msg1)):
                if msg and msg.startswith('waiting'):
                    self.check(f'{n.name} forced rejoin',
                               n.rejoin_mgr_group('127.0.0.1', self.ports[2]))

            self.check('group back to 3 ONLINE',
                       self.wait_mgr_online_count(n2, 3),
                       f'status={n2.get_mgr_status()}')
            self.check('n0 SECONDARY ONLINE', self.wait_mgr_role(n0, 'SECONDARY'))
            self.check('n1 SECONDARY ONLINE', self.wait_mgr_role(n1, 'SECONDARY'))

            # --- Phase 7: data catch-up ---
            logger.info('\n=== Phase 7: Verify catch-up of n2-only writes ===')
            deadline = time.time() + 60
            ok = False
            while time.time() < deadline:
                try:
                    c0 = n0._query_one("SELECT COUNT(*) FROM mgr_e2e.t1")
                    c1 = n1._query_one("SELECT COUNT(*) FROM mgr_e2e.t1")
                    c2 = n2._query_one("SELECT COUNT(*) FROM mgr_e2e.t1")
                    if c0 and c1 and c2 and c0[0] == 4 and c1[0] == 4 and c2[0] == 4:
                        ok = True
                        break
                except Exception:
                    pass
                time.sleep(1)
            self.check('all nodes have 4 rows after rejoin', ok,
                       f'counts may still be catching up')

            # Continuous write after recovery
            n2._query("INSERT INTO mgr_e2e.t1 VALUES (5,'after_rejoin')")
            deadline = time.time() + 30
            ok = False
            while time.time() < deadline:
                try:
                    if (n0._query_one("SELECT v FROM mgr_e2e.t1 WHERE id=5")
                            and n0._query_one("SELECT v FROM mgr_e2e.t1 WHERE id=5")[0]
                            == 'after_rejoin'):
                        ok = True
                        break
                except Exception:
                    pass
                time.sleep(1)
            self.check('post-rejoin write replicates', ok)

        except SystemExit:
            pass
        except Exception:
            logger.exception('Unexpected error')
            self.failed += 1
            self._dump_logs()
        finally:
            for n in self.nodes:
                try:
                    n.stop()
                except Exception:
                    pass
            if not self.keep_data:
                self.clean()
            else:
                _kill_test_mysqld(self.test_dir)
                logger.info('Preserved data at %s', self.test_dir)

        total = self.passed + self.failed
        logger.info('\n' + '=' * 60)
        logger.info('=== Results: %d/%d passed, %d failed ===', self.passed, total, self.failed)
        logger.info('=' * 60)
        return 0 if self.failed == 0 else 1


if __name__ == '__main__':
    sys.exit(MgrE2ETest(parse_args()).run())
