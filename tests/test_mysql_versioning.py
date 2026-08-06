"""Tests for MySQL version-aware parameter generation."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

mock_pymysql = type(sys)('pymysql')
mock_pymysql.connect = mock.Mock()
mock_err = type(sys)('pymysql.err')
mock_err.Error = Exception
mock_err.OperationalError = type('OperationalError', (Exception,), {})
mock_err.DatabaseError = type('DatabaseError', (Exception,), {})
mock_pymysql.err = mock_err
sys.modules['pymysql'] = mock_pymysql
sys.modules['pymysql.err'] = mock_err

from patroni.mysql.initcmd import (  # noqa: E402
    SEMI_SYNC_TIMEOUT_INFINITE_MS,
    align_down,
    format_size_mysql,
    generate_cluster,
    main,
)
from patroni.mysql.versioning import (  # noqa: E402
    build_mysqld_parameters,
    parse_mysql_version,
    resolve_mysql_version,
    semi_sync_plugin_names,
)


class TestParseVersion(unittest.TestCase):

    def test_parse_mysqld_banner(self):
        v = parse_mysql_version(
            '/usr/sbin/mysqld  Ver 8.0.35-debug for Linux on x86_64')
        self.assertEqual(str(v), '8.0.35')
        self.assertEqual(v.family, '8.0')
        self.assertTrue(v.uses_source_replica_names)
        self.assertTrue(v.uses_innodb_redo_log_capacity)

    def test_families(self):
        self.assertEqual(parse_mysql_version('5.6.51').family, '5.6')
        self.assertEqual(parse_mysql_version('5.7.44').family, '5.7')
        self.assertEqual(parse_mysql_version('8.0.25').family, '8.0')
        self.assertFalse(parse_mysql_version('8.0.25').uses_source_replica_names)
        self.assertTrue(parse_mysql_version('8.0.26').uses_source_replica_names)
        self.assertEqual(parse_mysql_version('8.4.0').family, '8')
        self.assertEqual(parse_mysql_version('9.0.1').family, '9')

    def test_shortcuts(self):
        self.assertEqual(resolve_mysql_version('5.7').family, '5.7')
        self.assertEqual(resolve_mysql_version('8.x').family, '8')
        self.assertEqual(resolve_mysql_version('9').family, '9')


class TestVersionParams(unittest.TestCase):

    def _build(self, ver: str, mode: str = 'semi-sync', nodes: int = 3):
        return build_mysqld_parameters(
            parse_mysql_version(ver),
            mode=mode,
            nodes=nodes,
            buffer_pool=1024 ** 3,
            format_size=format_size_mysql,
            align_down=align_down,
            timeout_infinite_ms=SEMI_SYNC_TIMEOUT_INFINITE_MS,
            timeout_two_node_ms=10000,
            group_name='aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
            local_host='127.0.0.1',
            mysql_port=3306,
            seeds='127.0.0.1:3316',
        )

    def test_56_legacy_semi_sync(self):
        p = self._build('5.6.51')
        self.assertIn('query_cache_type', p)
        self.assertIn('expire_logs_days', p)
        self.assertNotIn('binlog_expire_logs_seconds', p)
        self.assertIn('rpl_semi_sync_master_enabled', p)
        self.assertNotIn('rpl_semi_sync_source_enabled', p)
        self.assertNotIn('rpl_semi_sync_master_wait_point', p)  # no AFTER_SYNC on 5.6
        self.assertIn('innodb_log_file_size', p)
        self.assertNotIn('innodb_redo_log_capacity', p)
        self.assertEqual(semi_sync_plugin_names(parse_mysql_version('5.6.51'))[0],
                         'semisync_master.so')

    def test_57_after_sync(self):
        p = self._build('5.7.44')
        self.assertEqual(p['rpl_semi_sync_master_wait_point'], 'AFTER_SYNC')
        self.assertEqual(p['rpl_semi_sync_master_wait_for_slave_count'], '1')
        self.assertIn('slave_parallel_type', p)
        self.assertIn('query_cache_type', p)

    def test_80_pre26_master_names(self):
        p = self._build('8.0.25')
        self.assertIn('rpl_semi_sync_master_enabled', p)
        self.assertNotIn('query_cache_type', p)
        self.assertIn('binlog_expire_logs_seconds', p)
        self.assertIn('innodb_log_file_size', p)  # redo capacity from 8.0.30

    def test_80_35_modern(self):
        p = self._build('8.0.35')
        self.assertEqual(p['rpl_semi_sync_source_wait_point'], 'AFTER_SYNC')
        self.assertEqual(p['rpl_semi_sync_source_wait_no_replica'], 'ON')
        self.assertIn('innodb_redo_log_capacity', p)
        self.assertEqual(p['mysqlx'], 'OFF')
        self.assertEqual(p['collation_server'], 'utf8mb4_0900_ai_ci')
        self.assertIn('log_replica_updates', p)

    def test_9x(self):
        p = self._build('9.0.0')
        self.assertIn('rpl_semi_sync_source_enabled', p)
        self.assertIn('innodb_redo_log_capacity', p)

    def test_mgr_rejected_on_56(self):
        with self.assertRaises(ValueError):
            self._build('5.6.51', mode='mgr')


class TestInitcmdVersioned(unittest.TestCase):

    def test_generate_57(self):
        with tempfile.TemporaryDirectory() as tmp:
            ns = mock.Mock(
                output_dir=tmp, nodes=3, mode='semi-sync', scope='c',
                namespace='/service/', name_prefix='mysql', host='127.0.0.1',
                mysql_port_base=13306, api_port_base=18008, bin_dir='',
                mysql_version='5.7', etcd='127.0.0.1:2379', etcd_version=3,
                memory_pct=50, total_memory='6G', innodb_buffer_pool_size=None,
                superuser_password='', replication_password='rep',
                create_replica_methods='mysqldump', mgr_group_name=None,
                set=[], pythonpath='', force=True,
            )
            generate_cluster(ns)
            with open(os.path.join(tmp, 'mysql0', 'my.cnf')) as f:
                text = f.read()
            self.assertIn('plugin-load-add = semisync_master.so;semisync_slave.so', text)
            self.assertIn('rpl_semi_sync_master_wait_point = AFTER_SYNC', text)
            self.assertIn('query_cache_type = OFF', text)
            self.assertNotIn('rpl_semi_sync_source_', text)

    def test_main_detect_or_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc = main([
                '-o', tmp, '--nodes', '1', '--mode', 'async',
                '--mysql-version', '8.0.35', '--total-memory', '4G',
                '--force',
            ])
            self.assertEqual(rc, 0)


if __name__ == '__main__':
    unittest.main()
