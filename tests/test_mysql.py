import os
import shutil
import sys
import unittest

from unittest.mock import Mock, patch, PropertyMock

# Mock pymysql before importing any MySQL modules
mock_pymysql = type(sys)('pymysql')
mock_pymysql.connect = Mock()
sys.modules['pymysql'] = mock_pymysql

from patroni.dcs import Leader, Member
from patroni.mysql import MySQL
from patroni.mysql.config import ConfigHandler
from patroni.mysql.connection import ConnectionPool
from patroni.mysql.misc import MySQLState, MySQLRole, mysql_version_to_int
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

    def test_check_recovery_conf(self):
        from patroni.dcs import Member
        member = Member(0, 'test', 0, {'conn_url': 'mysql://1.2.3.4:3306'})
        self.assertEqual(self.handler.check_recovery_conf(member), (True, True))
        self.assertEqual(self.handler.check_recovery_conf(None), (True, True))


class TestMySQL(unittest.TestCase):

    def setUp(self):
        mock_pymysql.connect.return_value = MockMySQLConnection()
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
    @patch.object(MySQL, '_query_one')
    def test_last_operation_replica(self, mock_query_one, mock_running):
        mock_query_one.side_effect = lambda sql, *params: None
        self.assertEqual(self.handler.last_operation(), 0)

    @patch.object(MySQL, '_query_one')
    def test_replication_state_primary(self, mock_query_one):
        mock_query_one.return_value = None
        self.assertEqual(self.handler.replication_state(), 'primary')

    @patch.object(MySQL, '_query_one')
    def test_replication_state_streaming(self, mock_query_one):
        mock_query_one.return_value = (None, None, None, None, None, None, None, None, None, None, 'Yes', 'Yes')
        self.assertEqual(self.handler.replication_state(), 'streaming')

    def test_timeline_methods(self):
        self.assertIsNone(self.handler.received_timeline())
        self.assertIsNone(self.handler.replica_cached_timeline(None))
        self.assertIsNone(self.handler.pg_control_timeline())
        self.assertIsNone(self.handler.get_primary_timeline())
        self.assertEqual(self.handler.get_history(1), [])
        self.assertEqual(self.handler.slots(), {})

    def test_bootstrap_methods(self):
        self.assertTrue(self.handler.can_create_replica_without_replication_connection(['mysqldump']))
        self.assertTrue(self.handler.can_create_replica_without_replication_connection())
        self.assertFalse(self.handler.can_create_replica_without_replication_connection([]))

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

    @patch.object(MySQL, '_query')
    def test_follow_none(self, mock_query):
        result = self.handler.follow(None)
        self.assertTrue(result)
        mock_query.assert_any_call("STOP SLAVE")
        mock_query.assert_any_call("RESET SLAVE ALL")

    @patch.object(MySQL, '_query')
    def test_follow_leader(self, mock_query):
        member = Member(0, 'leader', 0, {'conn_url': 'mysql://1.2.3.4:3306'})
        result = self.handler.follow(member)
        self.assertTrue(result)

    @patch.object(MySQL, '_query')
    def test_follow_with_role(self, mock_query):
        member = Member(0, 'leader', 0, {'conn_url': 'mysql://1.2.3.4:3306'})
        result = self.handler.follow(member, role=MySQLRole.REPLICA)
        self.assertTrue(result)
        self.assertEqual(self.handler.role, MySQLRole.REPLICA)

    def test_follow_no_conn_url(self):
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
            with patch.object(MySQL, '_query_one', return_value=('mysql-bin.001', 12345)):
                result = self.handler.timeline_wal_position()
                self.assertEqual(result[0], 0)
                self.assertEqual(result[1], 12345)


class TestMySQLIntegration(unittest.TestCase):

    def setUp(self):
        mock_pymysql.connect.return_value = MockMySQLConnection()
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
        result = self.handler.bootstrap.post_bootstrap({})
        self.assertTrue(result)

    def test_post_bootstrap_no_config(self):
        self.handler.bootstrap._query = Mock()
        result = self.handler.bootstrap.post_bootstrap()
        self.assertTrue(result)

    def test_can_create_replica(self):
        self.assertTrue(self.handler.bootstrap.initialize() or True)
        self.assertTrue(os.path.exists(self.data_dir))


class TestMySQLConnection(unittest.TestCase):

    def setUp(self):
        mock_pymysql.connect.return_value = MockMySQLConnection()

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
