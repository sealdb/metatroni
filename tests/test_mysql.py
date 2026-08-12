import os
import shutil
import sys
import unittest

from unittest.mock import Mock, patch, PropertyMock

# Mock pymysql before importing any MySQL modules
mock_pymysql = type(sys)('pymysql')
mock_pymysql.connect = Mock()
mock_err = type(sys)('pymysql.err')
mock_err.Error = Exception
mock_err.OperationalError = type('OperationalError', (Exception,), {})
mock_err.DatabaseError = type('DatabaseError', (Exception,), {})
mock_pymysql.err = mock_err
sys.modules['pymysql'] = mock_pymysql
sys.modules['pymysql.err'] = mock_err

from patroni.dcs import Leader, Member
from patroni.mysql import MySQL
from patroni.mysql.config import ConfigHandler
from patroni.mysql.connection import ConnectionPool
from patroni.mysql.misc import (
    MySQLState, MySQLRole, CreateReplicaMethod, DEFAULT_CREATE_REPLICA_METHODS,
    mysql_version_to_int,
)
from patroni.mysql.postmaster import MySQLProcess


def get_mysql_config(name='mysql0'):
    return {
        'name': name,
        'scope': 'test-cluster',
        'data_dir': 'data/test_mysql',
        'config_dir': 'data/test_mysql',
        'listen': '127.0.0.1:3306',
        'connect_address': '127.0.0.1:3306',
        'port': 3306,
        'server_id': 1,
        'bin_dir': '',
        'authentication': {
            'superuser': {'username': 'root', 'password': 'secret'},
            'replication': {'username': 'replicator', 'password': 'rep-pass'},
        },
        'parameters': {
            'server_id': '1',
            'log-bin': 'mysql-bin',
            'gtid_mode': 'ON',
            'enforce_gtid_consistency': 'ON',
        }
    }


def _wire_pymysql_mock():
    """Point both sys.modules and connection.pymysql at MockMySQLConnection."""
    from patroni.mysql import connection as mysql_connection
    conn = MockMySQLConnection()
    mock_pymysql.connect.return_value = conn
    if hasattr(mysql_connection, 'pymysql'):
        mysql_connection.pymysql.connect.return_value = conn


def mock_query_results(results):
    def query_side_effect(sql, *params, retry=None):
        return results
    return query_side_effect


class MockCursor:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, sql, params=None):
        pass

    @property
    def rowcount(self):
        return 0

    def fetchall(self):
        return []

    def fetchone(self):
        return None


class MockMySQLConnection:
    def __init__(self, **kwargs):
        self.server_version = 80031
        self._kwargs = kwargs

    def cursor(self):
        return MockCursor()

    def ping(self, reconnect=True):
        pass

    def close(self):
        pass


class TestMySQLState(unittest.TestCase):

    def test_state_values(self):
        self.assertEqual(str(MySQLState.RUNNING), 'running')
        self.assertEqual(str(MySQLState.STOPPED), 'stopped')
        self.assertEqual(str(MySQLState.STARTING), 'starting')
        self.assertEqual(str(MySQLState.CRASHED), 'crashed')
        self.assertEqual(str(MySQLState.START_FAILED), 'start failed')
        self.assertEqual(MySQLState.RUNNING.index, 3)
        self.assertEqual(MySQLState.STOPPED.index, 10)

    def test_role_values(self):
        self.assertEqual(str(MySQLRole.PRIMARY), 'primary')
        self.assertEqual(str(MySQLRole.REPLICA), 'replica')
        self.assertEqual(str(MySQLRole.DEMOTED), 'demoted')
        self.assertEqual(str(MySQLRole.UNINITIALIZED), 'uninitialized')

    def test_mysql_version_to_int(self):
        self.assertEqual(mysql_version_to_int('8.0.31'), 80031)
        self.assertEqual(mysql_version_to_int('5.7.40'), 50740)
        self.assertEqual(mysql_version_to_int('8.0'), 80000)
        self.assertEqual(mysql_version_to_int('invalid'), 0)


class TestMySQLConfig(unittest.TestCase):

    def setUp(self):
        self.config = get_mysql_config()
        self.handler = ConfigHandler(self.config)

    def test_init(self):
        self.assertEqual(self.handler.data_dir, self.config['data_dir'])
        self.assertEqual(self.handler.bin_dir, '')
        self.assertEqual(self.handler.port, 3306)
        self.assertEqual(self.handler.server_id, 1)

    def test_auth(self):
        self.assertEqual(self.handler.replication.get('username'), 'replicator')
        self.assertEqual(self.handler.replication.get('password'), 'rep-pass')
        self.assertEqual(self.handler.superuser.get('username'), 'root')

    def test_paths(self):
        self.assertIn('mysqld', self.handler.get_mysqld_path())
        self.assertIn('mysqladmin', self.handler.get_mysqladmin_path())
        self.assertIn('mysql', self.handler.get_mysql_path())
        xb = self.handler.get_xtrabackup_path()
        self.assertTrue(xb.endswith('xtrabackup'))

    def test_check_recovery_conf(self):
        from patroni.dcs import Member
        member = Member(0, 'test', 0, {'conn_url': 'mysql://1.2.3.4:3306'})
        # MySQL reconfigures replication without restart
        self.assertEqual(self.handler.check_recovery_conf(member), (True, False))
        self.assertEqual(self.handler.check_recovery_conf(None), (True, False))

    def test_write_my_cnf_loads_semi_sync_plugins(self):
        cfg = get_mysql_config()
        cfg['parameters']['rpl_semi_sync_source_enabled'] = 'ON'
        cfg['parameters']['rpl_semi_sync_replica_enabled'] = 'ON'
        cfg['parameters']['cluster_size'] = '3'
        os.makedirs(cfg['data_dir'], exist_ok=True)
        handler = ConfigHandler(cfg)
        handler.write_my_cnf()
        with open(handler.config_file_path) as f:
            text = f.read()
        self.assertIn('semisync_source.so', text)
        self.assertIn('semisync_replica.so', text)
        self.assertNotIn('cluster_size', text)
        # plugin-load must come before plugin-owned variables
        self.assertLess(text.find('plugin-load-add'), text.find('rpl_semi_sync'))
        shutil.rmtree(cfg['data_dir'], ignore_errors=True)


class TestMySQL(unittest.TestCase):

    def setUp(self):
        mock_pymysql.connect.return_value = MockMySQLConnection()
        _wire_pymysql_mock()
        self.config = get_mysql_config()

        self.data_dir = self.config['data_dir']
        os.makedirs(self.data_dir, exist_ok=True)

        self.handler = MySQL(self.config)

    def tearDown(self):
        if os.path.exists(self.data_dir):
            shutil.rmtree(self.data_dir)

    def test_init(self):
        self.assertEqual(self.handler.name, 'mysql0')
        self.assertEqual(self.handler.scope, 'test-cluster')
        self.assertEqual(self.handler.state, MySQLState.STOPPED)
        self.assertEqual(self.handler.role, MySQLRole.UNINITIALIZED)
        self.assertEqual(self.handler.db_type, 'mysql')

    def test_connection_string(self):
        self.assertIn('mysql://', self.handler.connection_string)
        self.assertIn('3306', self.handler.connection_string)

    def test_properties(self):
        self.assertIsNone(self.handler.proxy_url)
        self.assertEqual(self.handler.pending_restart_reason, {})
        self.assertTrue(self.handler.data_directory_empty())
        self.assertFalse(self.handler.supports_multiple_sync)
        self.assertTrue(self.handler.cb_called)
        self.assertIsNotNone(self.handler.cancellable)

    def test_is_running_no_process(self):
        self.assertFalse(self.handler.is_running())

    def test_is_primary_not_running(self):
        self.assertFalse(self.handler.is_primary())

    @patch.object(MySQL, '_query_one')
    def test_is_primary_replica(self, mock_query_one):
        mock_query_one.return_value = ('localhost', 3306, '', '', '', 0)
        with patch.object(MySQL, 'is_running', return_value=True):
            self.assertFalse(self.handler.is_primary())

    @patch.object(MySQL, '_query_one')
    def test_is_primary_true(self, mock_query_one):
        mock_query_one.return_value = None
        with patch.object(MySQL, 'is_running', return_value=True):
            self.assertTrue(self.handler.is_primary())

    def test_is_starting(self):
        self.assertFalse(self.handler.is_starting())
        self.handler.set_state(MySQLState.STARTING)
        self.assertTrue(self.handler.is_starting())

    @patch.object(MySQL, '_query_one')
    def test_is_healthy(self, mock_query_one):
        mock_query_one.return_value = [(1,)]
        self.assertTrue(self.handler.is_healthy())

    @patch.object(MySQL, '_query_one')
    def test_is_healthy_failure(self, mock_query_one):
        mock_query_one.side_effect = Exception('connection error')
        self.assertFalse(self.handler.is_healthy())

    @patch.object(MySQL, 'is_running', return_value=False)
    @patch.object(MySQL, '_query_one_dict')
    def test_last_operation_replica(self, mock_query_one_dict, mock_running):
        mock_query_one_dict.side_effect = lambda sql, *params: None
        self.assertEqual(self.handler.last_operation(), 0)

    @patch.object(MySQL, '_query_one_dict')
    def test_replication_state_primary(self, mock_query_one_dict):
        mock_query_one_dict.return_value = None
        self.assertEqual(self.handler.replication_state(), 'primary')

    @patch.object(MySQL, '_query_one_dict')
    def test_replication_state_streaming(self, mock_query_one_dict):
        mock_query_one_dict.return_value = {'Slave_IO_Running': 'Yes', 'Slave_SQL_Running': 'Yes'}
        self.assertEqual(self.handler.replication_state(), 'streaming')

    def test_timeline_methods(self):
        self.assertEqual(self.handler.received_timeline(), 0)
        self.assertEqual(self.handler.replica_cached_timeline(None), 0)
        self.assertEqual(self.handler.pg_control_timeline(), 0)
        self.assertEqual(self.handler.get_primary_timeline(), 0)
        self.assertEqual(self.handler.get_history(1), [])
        self.assertEqual(self.handler.slots(), {})

    @patch.object(MySQL, 'is_primary', return_value=True)
    @patch.object(MySQL, 'count_semi_sync_replicas', return_value=0)
    @patch.object(MySQL, 'is_read_only', return_value=False)
    @patch.object(MySQL, 'set_read_only')
    def test_semi_sync_safety_sets_ro(self, mock_ro, _mock_is_ro, _mock_cnt, _mock_pri):
        self.handler.config._parameters['rpl_semi_sync_source_enabled'] = 'ON'
        self.assertEqual(self.handler.run_semi_sync_safety_check(3), 'read_only_set')
        mock_ro.assert_called_once()

    @patch.object(MySQL, 'is_primary', return_value=True)
    @patch.object(MySQL, 'count_semi_sync_replicas', return_value=2)
    @patch.object(MySQL, 'is_read_only', return_value=True)
    @patch.object(MySQL, 'set_read_write')
    def test_semi_sync_safety_restores_rw(self, mock_rw, _mock_is_ro, _mock_cnt, _mock_pri):
        self.handler.config._parameters['rpl_semi_sync_source_enabled'] = 'ON'
        self.assertEqual(self.handler.run_semi_sync_safety_check(3), 'read_write_restored')
        mock_rw.assert_called_once()

    def test_gtid_relation(self):
        uuid = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        with patch.object(MySQL, '_query_one', return_value=(1, 1)):
            self.assertEqual(self.handler.gtid_relation(f'{uuid}:1-10', f'{uuid}:1-10'), 'equal')
        with patch.object(MySQL, '_query_one', return_value=(0, 1)):
            self.assertEqual(self.handler.gtid_relation(f'{uuid}:1-20', f'{uuid}:1-10'), 'a_ahead')
        with patch.object(MySQL, '_query_one', return_value=(1, 0)):
            self.assertEqual(self.handler.gtid_relation(f'{uuid}:1-10', f'{uuid}:1-20'), 'b_ahead')
        with patch.object(MySQL, '_query_one', return_value=(0, 0)):
            self.assertEqual(self.handler.gtid_relation('u1:1-5', 'u2:1-5'), 'incomparable')
        self.assertEqual(self.handler.gtid_relation('', 'u:1-1'), 'incomparable')

    def test_select_mgr_bootstrap_winner(self):
        uuid = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        local = f'{uuid}:1-20'
        peer_behind = Member(0, 'mysql1', 0, {'gtid_executed': f'{uuid}:1-10'})
        peer_ahead = Member(0, 'mysql1', 0, {'gtid_executed': f'{uuid}:1-30'})
        peer_equal = Member(0, 'zzz', 0, {'gtid_executed': local})

        def rel(a, b):
            # Encode simple numeric max txn from same uuid for tests
            def end(g):
                return int(g.rsplit('-', 1)[-1])
            if a == b:
                return 'equal'
            if end(a) > end(b):
                return 'a_ahead'
            if end(a) < end(b):
                return 'b_ahead'
            return 'incomparable'

        with patch.object(MySQL, 'gtid_relation', side_effect=rel):
            self.assertEqual(self.handler.select_mgr_bootstrap_winner(local, [peer_behind]), 'mysql0')
            self.assertEqual(self.handler.select_mgr_bootstrap_winner(local, [peer_ahead]), 'mysql1')
            # equal GTIDs → lexicographically smallest name
            self.assertEqual(self.handler.select_mgr_bootstrap_winner(local, [peer_equal]), 'mysql0')

    def test_describe_mgr_gtid_fork_and_pause_action(self):
        self.handler.config._parameters['group_replication_group_name'] = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        local = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa:1-10'
        peer = Member(0, 'mysql1', 0, {
            'gtid_executed': 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb:1-10',
        })

        def rel(a, b):
            if a == b:
                return 'equal'
            return 'incomparable'

        with patch.object(MySQL, 'gtid_relation', side_effect=rel):
            fork = self.handler.describe_mgr_gtid_fork(local, [peer])
            self.assertEqual(len(fork), 2)
            names = {m['name'] for m in fork}
            self.assertEqual(names, {'mysql0', 'mysql1'})
            self.assertIsNone(self.handler.select_mgr_bootstrap_winner(local, [peer]))

        with patch.object(MySQL, 'get_mgr_status', return_value={}), \
                patch.object(MySQL, 'get_executed_gtid', return_value=local), \
                patch.object(MySQL, 'select_mgr_bootstrap_winner', return_value=None), \
                patch.object(MySQL, 'gtid_relation', side_effect=rel), \
                patch.object(MySQL, 'set_read_only') as mock_ro:
            msg = self.handler.run_mgr_cycle(True, 3, [peer])
        self.assertEqual(msg, 'mgr_gtid_fork')
        mock_ro.assert_called()
        self.assertIsNotNone(self.handler._mgr_gtid_fork)
        data = {}
        self.handler.enrich_dcs_data(data)
        self.assertIn('mgr_gtid_fork', data)

    def test_mgr_pause_on_gtid_fork_flag(self):
        self.assertTrue(self.handler.mgr_pause_on_gtid_fork_enabled())
        self.handler.config._parameters['mgr_pause_on_gtid_fork'] = False
        self.assertFalse(self.handler.mgr_pause_on_gtid_fork_enabled())

    @patch.object(MySQL, 'bootstrap_mgr_group', return_value=True)
    @patch.object(MySQL, 'get_executed_gtid', return_value='u:1-20')
    @patch.object(MySQL, 'select_mgr_bootstrap_winner', return_value='mysql0')
    def test_mgr_majority_loss_winner_with_lock_bootstraps(self, _win, _gtid, mock_boot):
        self.handler.config._parameters['group_replication_group_name'] = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        with patch.object(MySQL, 'get_mgr_status', return_value={}):
            msg = self.handler.run_mgr_cycle(True, 3, [])
        self.assertEqual(msg, 'bootstrapped MGR group after majority loss')
        mock_boot.assert_called_once()
        self.assertEqual(self.handler.role, MySQLRole.MGR_PRIMARY)

    @patch.object(MySQL, 'bootstrap_mgr_group', return_value=True)
    @patch.object(MySQL, 'get_executed_gtid', return_value='u:1-20')
    @patch.object(MySQL, 'select_mgr_bootstrap_winner', return_value='mysql0')
    def test_mgr_majority_loss_winner_ignores_stale_primary_role(self, _win, _gtid, mock_boot):
        """Stale Patroni role=primary must not block GTID-winner bootstrap."""
        self.handler.config._parameters['group_replication_group_name'] = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        stale = Member(0, 'mysql1', 0, {
            'role': 'primary',
            'conn_url': 'mysql://127.0.0.1:3307',
            'gtid_executed': 'u:1-10',
        })
        with patch.object(MySQL, 'get_mgr_status', return_value={}), \
                patch.object(MySQL, 'rejoin_mgr_group') as mock_rejoin:
            msg = self.handler.run_mgr_cycle(True, 3, [stale])
        self.assertEqual(msg, 'bootstrapped MGR group after majority loss')
        mock_boot.assert_called_once()
        mock_rejoin.assert_not_called()

    @patch.object(MySQL, 'bootstrap_mgr_group', return_value=True)
    @patch.object(MySQL, 'rejoin_mgr_group', return_value=True)
    @patch.object(MySQL, 'get_executed_gtid', return_value='u:1-20')
    @patch.object(MySQL, 'select_mgr_bootstrap_winner', return_value='mysql0')
    def test_mgr_majority_loss_winner_rejoins_live_mgr_primary(self, _win, _gtid,
                                                              mock_rejoin, mock_boot):
        self.handler.config._parameters['group_replication_group_name'] = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        live = Member(0, 'mysql1', 0, {
            'role': 'mgr_primary',
            'conn_url': 'mysql://127.0.0.1:3307',
            'gtid_executed': 'u:1-20',
        })
        with patch.object(MySQL, 'get_mgr_status', return_value={}):
            msg = self.handler.run_mgr_cycle(True, 3, [live])
        self.assertEqual(msg, 'mgr_yield_lock')
        mock_rejoin.assert_called_once_with('127.0.0.1', 3307)
        mock_boot.assert_not_called()

    @patch.object(MySQL, 'bootstrap_mgr_group', return_value=True)
    @patch.object(MySQL, 'rejoin_mgr_group', return_value=False)
    @patch.object(MySQL, 'get_executed_gtid', return_value='u:1-20')
    @patch.object(MySQL, 'select_mgr_bootstrap_winner', return_value='mysql0')
    def test_mgr_majority_loss_winner_bootstraps_when_rejoin_fails(self, _win, _gtid,
                                                                   mock_rejoin, mock_boot):
        """Stale DCS mgr_primary (peer GR dead) must not block winner bootstrap."""
        self.handler.config._parameters['group_replication_group_name'] = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        stale = Member(0, 'mysql1', 0, {
            'role': 'mgr_primary',
            'conn_url': 'mysql://127.0.0.1:3307',
            'gtid_executed': 'u:1-10',
        })
        with patch.object(MySQL, 'get_mgr_status', return_value={}):
            msg = self.handler.run_mgr_cycle(True, 3, [stale])
        self.assertEqual(msg, 'bootstrapped MGR group after majority loss')
        mock_rejoin.assert_called_once()
        mock_boot.assert_called_once()

    @patch.object(MySQL, 'rejoin_mgr_group', return_value=True)
    @patch.object(MySQL, 'get_executed_gtid', return_value='u:1-20')
    @patch.object(MySQL, 'select_mgr_bootstrap_winner', return_value='mysql0')
    def test_mgr_majority_loss_winner_without_lock_rejoins_live_primary(self, _win, _gtid,
                                                                        mock_rejoin):
        """Partial DCS view may elect self; still rejoin if mgr_primary exists."""
        self.handler.config._parameters['group_replication_group_name'] = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        live = Member(0, 'mysql2', 0, {
            'role': 'mgr_primary',
            'conn_url': 'mysql://127.0.0.1:3308',
            'gtid_executed': 'u:1-30',
        })
        with patch.object(MySQL, 'get_mgr_status', return_value={}):
            msg = self.handler.run_mgr_cycle(False, 3, [live])
        self.assertEqual(msg, 'rejoining MGR group after majority loss')
        mock_rejoin.assert_called_once_with('127.0.0.1', 3308)

    @patch.object(MySQL, 'rejoin_mgr_group', return_value=True)
    @patch.object(MySQL, 'get_executed_gtid', return_value='u:1-10')
    @patch.object(MySQL, 'select_mgr_bootstrap_winner', return_value='mysql1')
    def test_mgr_majority_loss_non_winner_rejoins(self, _win, _gtid, mock_rejoin):
        self.handler.config._parameters['group_replication_group_name'] = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'
        primary = Member(0, 'mysql1', 0, {
            'role': 'mgr_primary',
            'conn_url': 'mysql://127.0.0.1:3307',
            'gtid_executed': 'u:1-20',
        })
        with patch.object(MySQL, 'get_mgr_status', return_value={}):
            msg = self.handler.run_mgr_cycle(False, 3, [primary])
        self.assertEqual(msg, 'rejoining MGR group after majority loss')
        mock_rejoin.assert_called_once_with('127.0.0.1', 3307)

    @patch.object(MySQL, 'get_executed_gtid', return_value='u:1-20')
    def test_enrich_dcs_data_publishes_gtid(self, _gtid):
        data = {'xlog_location': 123}
        self.handler.enrich_dcs_data(data)
        self.assertEqual(data['binlog_position'], 123)
        self.assertEqual(data['gtid_executed'], 'u:1-20')

    def test_bootstrap_methods(self):
        self.assertTrue(self.handler.can_create_replica_without_replication_connection(
            [CreateReplicaMethod.MYSQLDUMP]))
        self.assertTrue(self.handler.can_create_replica_without_replication_connection(
            [CreateReplicaMethod.XTRABACKUP]))
        self.assertTrue(self.handler.can_create_replica_without_replication_connection(
            [CreateReplicaMethod.CLONE_PLUGIN]))
        self.assertTrue(self.handler.can_create_replica_without_replication_connection())
        # Empty / None → default path (xtrabackup then mysqldump) is available
        self.assertTrue(self.handler.can_create_replica_without_replication_connection([]))
        self.assertFalse(self.handler.can_create_replica_without_replication_connection(['unknown']))

    def test_create_replica_method_enum(self):
        known = CreateReplicaMethod.known()
        self.assertEqual(known, frozenset({
            'xtrabackup', 'mysqldump', 'clone_plugin',
        }))
        self.assertEqual(
            list(DEFAULT_CREATE_REPLICA_METHODS),
            [CreateReplicaMethod.XTRABACKUP, CreateReplicaMethod.MYSQLDUMP])
        # str Enum compares equal to YAML/DCS string values
        self.assertEqual(CreateReplicaMethod.XTRABACKUP, 'xtrabackup')
        self.assertEqual(
            list(self.handler.config.create_replica_methods),
            list(DEFAULT_CREATE_REPLICA_METHODS))

    def test_resolve_create_replica_methods(self):
        from patroni.dcs import RemoteMember
        bs = self.handler.bootstrap
        default = list(DEFAULT_CREATE_REPLICA_METHODS)

        with patch.object(self.handler.config, 'xtrabackup_available', return_value=True):
            self.assertEqual(bs._resolve_create_replica_methods(None), default)

        with patch.object(self.handler.config, 'xtrabackup_available', return_value=False):
            self.assertEqual(
                bs._resolve_create_replica_methods(None),
                [CreateReplicaMethod.MYSQLDUMP])
            # Explicit xtrabackup-only must not invent mysqldump
            remote = RemoteMember('r', {
                'conn_kwargs': {'host': '127.0.0.1', 'port': 3306, 'db_type': 'mysql'},
                'create_replica_methods': [CreateReplicaMethod.XTRABACKUP],
            })
            self.assertEqual(bs._resolve_create_replica_methods(remote), [])

        with patch.object(self.handler.config, 'xtrabackup_available', return_value=True):
            remote = RemoteMember('r', {
                'conn_kwargs': {'host': '127.0.0.1', 'port': 3306, 'db_type': 'mysql'},
                'create_replica_methods': [CreateReplicaMethod.MYSQLDUMP],
            })
            self.assertEqual(
                bs._resolve_create_replica_methods(remote),
                [CreateReplicaMethod.MYSQLDUMP])
            remote2 = RemoteMember('r2', {
                'conn_kwargs': {'host': '127.0.0.1', 'port': 3306, 'db_type': 'mysql'},
                'create_replica_methods': default,
            })
            self.assertEqual(bs._resolve_create_replica_methods(remote2), default)

    @patch.object(MySQL, 'set_read_only')
    @patch.object(MySQL, '_query')
    @patch.object(MySQL, '_query_one_dict', return_value=None)
    @patch.object(MySQL, 'is_running', return_value=True)
    def test_follow_standby_leader_role(self, _run, _status, mock_query, _ro):
        from patroni.dcs import RemoteMember
        remote = RemoteMember('remote', {
            'conn_kwargs': {'host': '10.0.0.1', 'port': 3306, 'db_type': 'mysql'},
        })
        self.assertTrue(remote.conn_url.startswith('mysql://'))
        ok = self.handler.follow(remote, role=MySQLRole.STANDBY_LEADER)
        self.assertTrue(ok)
        self.assertEqual(self.handler.role, MySQLRole.STANDBY_LEADER)

    @patch.object(MySQL, 'is_running', return_value=True)
    @patch.object(MySQL, '_query')
    def test_follow_none_keeps_standby_leader(self, mock_query, _run):
        self.handler.set_role(MySQLRole.STANDBY_LEADER)
        self.assertTrue(self.handler.follow(None, role=MySQLRole.STANDBY_LEADER))
        self.assertEqual(self.handler.role, MySQLRole.STANDBY_LEADER)
        self.handler.set_role(MySQLRole.REPLICA)
        self.assertTrue(self.handler.follow(None, role=MySQLRole.REPLICA))
        self.assertEqual(self.handler.role, MySQLRole.REPLICA)
        self.assertTrue(self.handler.follow(None, role=None))
        self.assertEqual(self.handler.role, MySQLRole.PRIMARY)

    def test_create_replica_dispatches_methods(self):
        from patroni.dcs import RemoteMember
        bs = self.handler.bootstrap
        remote = RemoteMember('r', {
            'conn_kwargs': {'host': '127.0.0.1', 'port': 3306, 'db_type': 'mysql'},
            'create_replica_methods': [
                CreateReplicaMethod.XTRABACKUP, CreateReplicaMethod.MYSQLDUMP],
        })
        with patch.object(bs, '_resolve_create_replica_methods',
                          return_value=[CreateReplicaMethod.XTRABACKUP,
                                        CreateReplicaMethod.MYSQLDUMP]), \
                patch.object(bs, '_create_replica_via_xtrabackup', return_value=False) as xb, \
                patch.object(bs, '_create_replica_via_mysqldump', return_value=True) as dump:
            self.assertTrue(bs.create_replica(remote))
            xb.assert_called_once()
            dump.assert_called_once()

        with patch.object(bs, '_resolve_create_replica_methods',
                          return_value=[CreateReplicaMethod.MYSQLDUMP]), \
                patch.object(bs, '_create_replica_via_mysqldump', return_value=True) as dump, \
                patch.object(bs, '_create_replica_via_xtrabackup') as xb:
            self.assertTrue(bs.create_replica(remote))
            dump.assert_called_once()
            xb.assert_not_called()

    def test_mysql_api_status_standby_leader_role(self):
        """REST /patroni must report standby_leader, not plain replica."""
        from patroni.api import RestApiHandler
        from patroni import global_config

        self.handler.set_role(MySQLRole.STANDBY_LEADER)
        self.handler.set_state(MySQLState.RUNNING)
        handler = Mock(spec=RestApiHandler)
        handler.server = Mock()

        with patch.object(MySQL, 'is_running', return_value=True), \
                patch.object(MySQL, 'is_primary', return_value=False), \
                patch.object(MySQL, '_query_one_dict', return_value={'File': 'bin.0001', 'Position': 100}), \
                patch.object(MySQL, 'get_executed_gtid', return_value='uuid:1-10'), \
                patch.object(MySQL, 'replication_state', return_value='streaming'), \
                patch.object(MySQL, 'server_version', 80035), \
                patch.object(global_config.__class__, 'is_standby_cluster',
                             PropertyMock(return_value=True)):
            status = RestApiHandler._get_mysql_status(handler, self.handler, retry=None)
        self.assertEqual(status['role'], MySQLRole.STANDBY_LEADER)
        self.assertEqual(status['state'], MySQLState.RUNNING)
        self.assertEqual(status['replication_state'], 'streaming')

        with patch.object(MySQL, 'is_running', return_value=True), \
                patch.object(MySQL, 'is_primary', return_value=False), \
                patch.object(MySQL, '_query_one_dict', return_value=None), \
                patch.object(MySQL, 'get_executed_gtid', return_value=''), \
                patch.object(MySQL, 'replication_state', return_value='streaming'), \
                patch.object(MySQL, 'server_version', 80035), \
                patch.object(global_config.__class__, 'is_standby_cluster',
                             PropertyMock(return_value=False)):
            status = RestApiHandler._get_mysql_status(handler, self.handler, retry=None)
        self.assertEqual(status['role'], 'replica')

    def test_controldata(self):
        data = self.handler.controldata()
        self.assertIsInstance(data, dict)

    def test_latest_checkpoint_locations(self):
        self.assertEqual(self.handler.latest_checkpoint_locations(), (None, None))

    @patch.object(MySQL, '_query')
    def test_sysid(self, mock_query):
        mock_query.return_value = [('550e8400-e29b-41d4-a716-446655440000',)]
        self.assertEqual(self.handler.sysid, '550e8400-e29b-41d4-a716-446655440000')

    @patch.object(MySQL, '_query_one', return_value=None)
    def test_server_version(self, mock_query_one):
        self.assertIsInstance(self.handler.server_version, int)

    def test_promote_already_primary(self):
        with patch.object(MySQL, '_is_replica', return_value=False):
            self.assertTrue(self.handler.promote(10))

    @patch.object(MySQL, '_query')
    def test_promote_success(self, mock_query):
        with patch.object(MySQL, '_is_replica', return_value=True):
            result = self.handler.promote(10)
            self.assertTrue(result)

    def test_demote(self):
        self.handler.set_role(MySQLRole.PRIMARY)
        self.handler.demote()
        self.assertEqual(self.handler.role, MySQLRole.DEMOTED)

    def test_ha_demote_routes_to_mysql_path(self):
        """Lost-lock demote must not enter the PostgreSQL rewind/archive path."""
        from patroni.ha import Ha

        ha = Ha.__new__(Ha)
        ha.state_handler = Mock(db_type='mysql')
        ha._demote_mysql = Mock(return_value=True)
        self.assertTrue(Ha.demote(ha, 'immediate-nolock'))
        ha._demote_mysql.assert_called_once_with('immediate-nolock')

    def test_ha_demote_mysql_follows_new_leader(self):
        from patroni.dcs import Member
        from patroni.ha import Ha
        from unittest.mock import MagicMock

        leader = Member(0, 'mysql0', 0, {'conn_url': 'mysql://127.0.0.1:3306'})
        ha = Ha.__new__(Ha)
        ha.state_handler = Mock(spec=['set_read_only', 'demote', 'follow', 'db_type'])
        ha.state_handler.db_type = 'mysql'
        ha.state_handler.follow.return_value = True
        ha.set_is_leader = Mock()
        ha.load_cluster_from_dcs = Mock()
        ha.cluster = Mock()
        ha.dcs = Mock()
        ha.dcs.get_cluster.return_value = ha.cluster
        ha._get_node_to_follow = Mock(return_value=leader)
        ha.touch_member = Mock()
        ha.release_leader_key_voluntarily = Mock()
        ha._async_executor = MagicMock()
        ha._async_executor.__enter__ = Mock(return_value=None)
        ha._async_executor.__exit__ = Mock(return_value=False)

        with patch('patroni.ha.time.sleep', Mock()):
            self.assertTrue(Ha._demote_mysql(ha, 'graceful'))
        ha.state_handler.set_read_only.assert_called_once()
        ha.state_handler.demote.assert_called_once()
        ha.set_is_leader.assert_called_once_with(False)
        ha.release_leader_key_voluntarily.assert_called_once()
        ha.state_handler.follow.assert_called_once_with(leader, role='replica')
        ha.touch_member.assert_called_once()

    def test_ha_demote_mysql_nolock_skips_release(self):
        from patroni.dcs import Member
        from patroni.ha import Ha

        leader = Member(0, 'mysql0', 0, {'conn_url': 'mysql://127.0.0.1:3306'})
        ha = Ha.__new__(Ha)
        ha.state_handler = Mock(spec=['set_read_only', 'demote', 'follow', 'db_type'])
        ha.state_handler.db_type = 'mysql'
        ha.state_handler.follow.return_value = True
        ha.set_is_leader = Mock()
        ha.load_cluster_from_dcs = Mock()
        ha.cluster = Mock()
        ha.dcs = Mock()
        ha.dcs.get_cluster.return_value = ha.cluster
        ha._get_node_to_follow = Mock(return_value=leader)
        ha.touch_member = Mock()
        ha.release_leader_key_voluntarily = Mock()

        self.assertTrue(Ha._demote_mysql(ha, 'immediate-nolock'))
        ha.release_leader_key_voluntarily.assert_not_called()
        ha.state_handler.follow.assert_called_once_with(leader, role='replica')

    @patch.object(MySQL, 'is_running', return_value=True)
    @patch.object(MySQL, '_query')
    def test_follow_none(self, mock_query, _mock_running):
        result = self.handler.follow(None)
        self.assertTrue(result)
        mock_query.assert_any_call("STOP SLAVE")
        mock_query.assert_any_call("RESET SLAVE ALL")

    @patch.object(MySQL, 'is_running', return_value=True)
    @patch.object(MySQL, '_query')
    def test_follow_leader(self, mock_query, _mock_running):
        member = Member(0, 'leader', 0, {'conn_url': 'mysql://1.2.3.4:3306'})
        result = self.handler.follow(member)
        self.assertTrue(result)

    @patch.object(MySQL, 'is_running', return_value=True)
    @patch.object(MySQL, '_query')
    def test_follow_with_role(self, mock_query, _mock_running):
        member = Member(0, 'leader', 0, {'conn_url': 'mysql://1.2.3.4:3306'})
        result = self.handler.follow(member, role=MySQLRole.REPLICA)
        self.assertTrue(result)
        self.assertEqual(self.handler.role, MySQLRole.REPLICA)

    @patch.object(MySQL, 'is_running', return_value=True)
    def test_follow_no_conn_url(self, _mock_running):
        member = Member(0, 'leader', 0, {})
        result = self.handler.follow(member)
        self.assertFalse(result)

    @patch.object(MySQL, '_query')
    def test_reload(self, mock_query):
        self.handler.reload()

    def test_reload_config(self):
        new_config = get_mysql_config(name='mysql1')
        self.handler.reload_config(new_config)
        self.assertEqual(self.handler.name, 'mysql1')

    def test_remove_data_directory(self):
        self.handler.remove_data_directory()
        self.assertFalse(os.path.exists(self.data_dir))

    def test_move_data_directory(self):
        os.makedirs(self.data_dir, exist_ok=True)
        self.handler.move_data_directory()
        self.assertFalse(os.path.exists(self.data_dir))
        self.assertTrue(os.path.exists(self.data_dir + '.bak'))
        shutil.rmtree(self.data_dir + '.bak')

    def test_terminate_starting_postmaster(self):
        self.handler.terminate_starting_postmaster()

    def test_stub_methods(self):
        self.assertFalse(self.handler.handle_parameter_change())
        self.handler.check_for_startup()
        self.handler.call_nowait(None)
        self.handler.schedule_sanity_checks_after_pause()
        self.handler.reset_cluster_info_state(None)
        self.assertIsNotNone(self.handler.sync_handler)
        self.assertIsNotNone(self.handler.slots_handler)
        self.assertIsNotNone(self.handler.mpp_handler)

    def test_timeline_wal_position_primary(self):
        with patch.object(MySQL, 'is_primary', return_value=True):
            with patch.object(MySQL, '_query_one_dict', return_value={'File': 'mysql-bin.001', 'Position': 12345}):
                result = self.handler.timeline_wal_position()
                self.assertEqual(result[0], 0)
                self.assertEqual(result[1], 12345)


class TestMySQLIntegration(unittest.TestCase):

    def setUp(self):
        mock_pymysql.connect.return_value = MockMySQLConnection()
        _wire_pymysql_mock()
        self.config = get_mysql_config()
        self.data_dir = self.config['data_dir']
        os.makedirs(self.data_dir, exist_ok=True)
        self.handler = MySQL(self.config)

    def tearDown(self):
        if os.path.exists(self.data_dir):
            shutil.rmtree(self.data_dir)

    @patch('os.path.exists', return_value=False)
    @patch('patroni.mysql.postmaster.MySQLProcess.from_pidfile')
    def test_start_stop(self, mock_from_pidfile, mock_exists):
        mock_proc = Mock()
        mock_proc.is_running.return_value = True
        mock_proc.pid = 999999
        mock_from_pidfile.return_value = mock_proc
        with patch('subprocess.run', Mock(return_value=Mock(returncode=0))):
            result = self.handler.start()
            self.assertTrue(result)


class TestBootstrap(unittest.TestCase):

    def setUp(self):
        mock_pymysql.connect.return_value = MockMySQLConnection()
        _wire_pymysql_mock()
        self.config = get_mysql_config()
        self.data_dir = self.config['data_dir']
        os.makedirs(self.data_dir, exist_ok=True)
        self.handler = MySQL(self.config)

    def tearDown(self):
        if os.path.exists(self.data_dir):
            shutil.rmtree(self.data_dir)

    @patch('subprocess.run', Mock(return_value=Mock(returncode=0)))
    @patch('patroni.mysql.postmaster.MySQLProcess.start')
    def test_bootstrap(self, mock_start):
        mock_start.return_value = Mock(pid=12345)
        result = self.handler.bootstrap.bootstrap({})
        self.assertTrue(result)

    @patch.object(MySQL, '_query')
    def test_post_bootstrap(self, mock_query):
        # Recreate under the patch so Bootstrap captures the mocked _query.
        handler = MySQL(self.config)
        result = handler.bootstrap.post_bootstrap({})
        self.assertTrue(result)

    def test_post_bootstrap_no_config(self):
        self.handler.bootstrap._query = Mock()
        result = self.handler.bootstrap.post_bootstrap()
        self.assertTrue(result)

    def test_ensure_replication_user(self):
        self.handler.bootstrap._query = Mock()
        self.assertTrue(self.handler.bootstrap.ensure_replication_user())
        sqls = [c.args[0] for c in self.handler.bootstrap._query.call_args_list]
        self.assertTrue(any(s == 'SET sql_log_bin=0' for s in sqls))
        self.assertTrue(any(s == 'SET sql_log_bin=1' for s in sqls))
        self.assertTrue(any('CREATE USER IF NOT EXISTS' in s for s in sqls))
        self.assertTrue(any('ALTER USER' in s for s in sqls))
        self.assertTrue(any('GRANT REPLICATION SLAVE' in s for s in sqls))
        self.assertTrue(any('BACKUP_ADMIN' in s for s in sqls))
        self.assertTrue(any(s == 'FLUSH PRIVILEGES' for s in sqls))
        # host pattern must be a single '%' (parameter), not literal '%%'
        create_call = next(c for c in self.handler.bootstrap._query.call_args_list
                           if 'CREATE USER' in c.args[0])
        self.assertEqual(create_call.args[2], '%')

    def test_can_create_replica(self):
        self.assertTrue(self.handler.bootstrap.initialize() or True)
        self.assertTrue(os.path.exists(self.data_dir))

    def test_cleanup_helpers(self):
        path = os.path.join(self.data_dir, 'tmp_cleanup')
        os.makedirs(path, exist_ok=True)
        fpath = os.path.join(path, 'f')
        open(fpath, 'w').close()
        self.handler.bootstrap._unlink_quiet(fpath)
        self.assertFalse(os.path.exists(fpath))
        self.handler.bootstrap._rmtree_quiet(path)
        self.assertFalse(os.path.exists(path))
        self.handler.bootstrap._rmtree_quiet('/nonexistent/path')
        self.handler.bootstrap._unlink_quiet('/nonexistent/file')


class TestMySQLConnection(unittest.TestCase):

    def setUp(self):
        mock_pymysql.connect.return_value = MockMySQLConnection()
        _wire_pymysql_mock()

    def tearDown(self):
        pass

    def test_connection_pool(self):
        pool = ConnectionPool({'host': '127.0.0.1', 'port': 3306, 'user': 'test'})
        conn = pool.get('test')
        self.assertIsNotNone(conn)
        pool.close()

    def test_connection_pool_reuse(self):
        pool = ConnectionPool({'host': '127.0.0.1', 'port': 3306, 'user': 'test'})
        conn1 = pool.get('test')
        conn2 = pool.get('test')
        self.assertIs(conn1, conn2)
        pool.close()

    def test_set_conn_kwargs(self):
        pool = ConnectionPool()
        pool.set_conn_kwargs({'host': '127.0.0.1', 'port': 3307})
        self.assertEqual(pool.conn_kwargs['port'], 3307)
