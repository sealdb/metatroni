"""Tests for ``patroni_mysql_init`` config generation."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

from unittest import mock

# Mock pymysql before importing patroni.mysql (same pattern as test_mysql.py)
# Include pymysql.err so connection.HAS_MYSQL becomes True.
mock_pymysql = type(sys)('pymysql')
mock_pymysql.connect = mock.Mock()
mock_err = type(sys)('pymysql.err')
mock_err.Error = Exception
mock_err.OperationalError = type('OperationalError', (Exception,), {})
mock_err.DatabaseError = type('DatabaseError', (Exception,), {})
mock_pymysql.err = mock_err
sys.modules['pymysql'] = mock_pymysql
sys.modules['pymysql.err'] = mock_err

import yaml  # noqa: E402

from patroni.mysql.initcmd import compute_buffer_pool_bytes, format_size_mysql, \
    generate_cluster, main, parse_size, SEMI_SYNC_TIMEOUT_INFINITE_MS  # noqa: E402


class TestSizeHelpers(unittest.TestCase):

    def test_parse_size(self):
        self.assertEqual(parse_size('512M'), 512 * 1024 ** 2)
        self.assertEqual(parse_size('2G'), 2 * 1024 ** 3)
        self.assertEqual(parse_size('1GiB'), 1024 ** 3)
        self.assertEqual(parse_size('1024'), 1024)

    def test_format_size(self):
        self.assertEqual(format_size_mysql(2 * 1024 ** 3), '2G')
        self.assertEqual(format_size_mysql(128 * 1024 ** 2), '128M')

    def test_buffer_pool_splits_across_nodes(self):
        total = 12 * 1024 ** 3
        # 50% of 12G = 6G shared → 2G per node for 3 nodes
        bp = compute_buffer_pool_bytes(total, 50, 3)
        self.assertEqual(bp, 2 * 1024 ** 3)

    def test_buffer_pool_explicit(self):
        bp = compute_buffer_pool_bytes(16 * 1024 ** 3, 50, 3, explicit=1024 ** 3)
        self.assertEqual(bp, 1024 ** 3)


class TestGenerateCluster(unittest.TestCase):

    def _args(self, **kwargs):
        defaults = {
            'output_dir': None,
            'nodes': 3,
            'mode': 'semi-sync',
            'scope': 'mysql-cluster',
            'namespace': '/service/',
            'name_prefix': 'mysql',
            'host': '127.0.0.1',
            'mysql_port_base': 13306,
            'api_port_base': 18008,
            'bin_dir': '/opt/mysql/bin',
            'mysql_version': '8.0.35',
            'etcd': '127.0.0.1:2379',
            'etcd_version': 3,
            'memory_pct': 50,
            'total_memory': '6G',
            'innodb_buffer_pool_size': None,
            'superuser_password': '',
            'replication_password': 'rep-pass',
            'create_replica_methods': 'mysqldump',
            'mgr_group_name': None,
            'set': [],
            'pythonpath': '',
            'force': True,
        }
        defaults.update(kwargs)
        ns = argparse_namespace(defaults)
        return ns

    def test_semi_sync_three_node_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self._args(output_dir=tmp)
            nodes = generate_cluster(args)
            self.assertEqual(len(nodes), 3)

            y0 = os.path.join(tmp, 'mysql0', 'patroni.yml')
            c0 = os.path.join(tmp, 'mysql0', 'my.cnf')
            self.assertTrue(os.path.isfile(y0))
            self.assertTrue(os.path.isfile(c0))
            self.assertTrue(os.path.isdir(os.path.join(tmp, 'mysql0', 'data')))
            self.assertTrue(os.path.isfile(os.path.join(tmp, 'start.sh')))
            self.assertTrue(os.path.isfile(os.path.join(tmp, 'haproxy.cfg')))
            with open(os.path.join(tmp, 'haproxy.cfg')) as f:
                hap = f.read()
            self.assertIn('listen mysql_primary', hap)
            self.assertIn('httpchk HEAD /primary', hap)
            self.assertIn('httpchk HEAD /replica', hap)
            self.assertIn('server mysql0 127.0.0.1:13306', hap)
            self.assertIn('check port 18008', hap)

            with open(y0) as f:
                cfg = yaml.safe_load(f)
            self.assertEqual(cfg['database']['type'], 'mysql')
            self.assertIn('etcd3', cfg)
            params = cfg['mysql']['parameters']
            self.assertEqual(params['rpl_semi_sync_source_wait_point'], 'AFTER_SYNC')
            self.assertEqual(params['rpl_semi_sync_source_enabled'], 'OFF')  # xenon posture
            self.assertEqual(params['rpl_semi_sync_replica_enabled'], 'ON')
            # 8.0.35+ uses replica_* naming
            self.assertTrue(
                params.get('replica_parallel_workers') == '64'
                or params.get('slave_parallel_workers') == '64')
            self.assertTrue(
                params.get('skip_replica_start') == 'ON'
                or params.get('skip_slave_start') == 'ON')
            self.assertEqual(params['rpl_semi_sync_source_timeout'],
                             str(SEMI_SYNC_TIMEOUT_INFINITE_MS))
            self.assertEqual(params['rpl_semi_sync_source_wait_for_replica_count'], '1')
            # 50% of 6G / 3 = 1G
            self.assertEqual(params['innodb_buffer_pool_size'], '1G')
            self.assertEqual(cfg['mysql']['port'], 13306)
            self.assertEqual(cfg['mysql']['listen'], '127.0.0.1:13306')

            with open(c0) as f:
                text = f.read()
            self.assertIn('innodb_buffer_pool_size = 1G', text)
            self.assertIn('rpl_semi_sync_source_wait_point = AFTER_SYNC', text)
            self.assertTrue(
                'replica_parallel_type = LOGICAL_CLOCK' in text
                or 'slave_parallel_type = LOGICAL_CLOCK' in text)
            self.assertNotIn('cluster_size', text)

            # Distinct ports for node 2
            with open(os.path.join(tmp, 'mysql2', 'patroni.yml')) as f:
                cfg2 = yaml.safe_load(f)
            self.assertEqual(cfg2['mysql']['port'], 13308)
            self.assertEqual(cfg2['restapi']['listen'], '127.0.0.1:18010')

    def test_mgr_seeds_and_ports(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self._args(output_dir=tmp, mode='mgr',
                              mgr_group_name='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee')
            generate_cluster(args)
            with open(os.path.join(tmp, 'mysql1', 'patroni.yml')) as f:
                cfg = yaml.safe_load(f)
            params = cfg['mysql']['parameters']
            self.assertEqual(params['group_replication_group_name'],
                             'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee')
            seeds = params['loose-group_replication_group_seeds']
            self.assertIn('127.0.0.1:13316', seeds)  # 13306+10
            self.assertIn('127.0.0.1:13317', seeds)
            self.assertIn('127.0.0.1:13318', seeds)
            self.assertEqual(params['loose-group_replication_local_address'],
                             '127.0.0.1:13317')

    def test_main_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = main([
                '-o', tmp, '--nodes', '2', '--mode', 'async',
                '--total-memory', '4G', '--memory-pct', '50',
                '--mysql-port-base', '2306', '--mysql-version', '8.0.35',
                '--force',
            ])
            self.assertEqual(rc, 0)
            self.assertTrue(os.path.isfile(os.path.join(tmp, 'mysql0', 'patroni.yml')))
            self.assertTrue(os.path.isfile(os.path.join(tmp, 'cluster-summary.yaml')))


def argparse_namespace(values):
    return mock.Mock(**values)


if __name__ == '__main__':
    unittest.main()
