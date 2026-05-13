#!/usr/bin/env python3
"""Patroni MySQL HA Integration Test.

Tests the complete MySQL high-availability flow:
  1. Bootstrap a primary node
  2. Create replication user and test data
  3. Clone a replica from the primary
  4. Configure GTID-based replication
  5. Verify data replication
  6. Promote replica to primary
  7. Demote and re-follow

Usage:
  # Set path to MySQL installation, then run:
  export MYSQL_BASE=/path/to/mysql
  python integration-tests/test_mysql_ha.py

  # Or pass via command line:
  python integration-tests/test_mysql_ha.py /path/to/mysql
"""

import os
import sys
import time
import subprocess
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger('mysql_ha_test')

_DEFAULT_MYSQL_BASE = '/usr/local/mysql'
MYSQL_BASE = os.environ.get('MYSQL_BASE') or (sys.argv[1] if len(sys.argv) > 1 else _DEFAULT_MYSQL_BASE)
if not os.path.isdir(MYSQL_BASE):
    logger.error("%s is not a valid directory", MYSQL_BASE)
    logger.error("Usage: MYSQL_BASE=/path/to/mysql %s [mysql_base]", sys.argv[0])
    sys.exit(1)

os.environ['PATH'] = f"{MYSQL_BASE}/bin:{os.environ['PATH']}"

import pymysql
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from patroni.mysql import MySQL
from patroni.dcs import Member


TEST_DIR = '/tmp/patroni_mysql_ha_test'
P0_PORT = 33907
P1_PORT = 33908


def clean():
    import shutil
    for pid_file in [f"{TEST_DIR}/p0/mysqld.pid", f"{TEST_DIR}/p1/mysqld.pid"]:
        if os.path.exists(pid_file):
            try:
                with open(pid_file) as f:
                    pid = int(f.read().strip())
                    os.kill(pid, 9)
            except Exception:
                pass
    if os.path.exists(TEST_DIR):
        shutil.rmtree(TEST_DIR)


def make_config(name, data_dir, port, server_id):
    return {
        'name': name,
        'scope': 'mysql-ha-test',
        'data_dir': data_dir,
        'config_dir': data_dir,
        'listen': f'127.0.0.1:{port}',
        'connect_address': f'127.0.0.1:{port}',
        'port': port,
        'server_id': server_id,
        'bin_dir': f'{MYSQL_BASE}/bin',
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
        },
    }


def main():
    clean()
    os.makedirs(f"{TEST_DIR}/p0", exist_ok=True)
    os.makedirs(f"{TEST_DIR}/p1", exist_ok=True)

    passed = 0
    failed = 0

    def check(label, condition, detail=''):
        nonlocal passed, failed
        if condition:
            logger.info("  PASS  %s", label)
            passed += 1
        else:
            logger.error("  FAIL  %s%s", label, f'  ({detail})' if detail else '')
            failed += 1

    # ===== Phase 1: Bootstrap primary =====
    logger.info("\n=== Phase 1: Bootstrap primary node (p0) ===")
    p0 = MySQL(make_config('p0', f'{TEST_DIR}/p0', P0_PORT, 1))
    check('bootstrap() returns True', p0.bootstrap.bootstrap({}))
    time.sleep(2)
    check('is_running()', p0.is_running())
    check('is_primary() (no slave configured)', p0.is_primary())
    check('is_healthy()', p0.is_healthy())
    check('state == running', p0.state == 'running')
    check('db_type == mysql', p0.db_type == 'mysql')
    check('connection_string format', 'mysql://' in p0.connection_string)

    # ===== Phase 2: Create replication user and test data =====
    logger.info("\n=== Phase 2: Create replication user and test data ===")
    p0._query("SET sql_log_bin=0")
    p0._query("CREATE USER IF NOT EXISTS 'replicator'@'%' IDENTIFIED BY 'rep-pass'")
    p0._query("GRANT REPLICATION SLAVE, REPLICATION CLIENT, "
              "SELECT, RELOAD, LOCK TABLES, PROCESS ON *.* TO 'replicator'@'%'")
    p0._query("FLUSH PRIVILEGES")
    p0._query("SET sql_log_bin=1")

    p0._query("CREATE DATABASE IF NOT EXISTS ha_test")
    p0._query("CREATE TABLE ha_test.t1 (id INT PRIMARY KEY, v VARCHAR(64))")
    p0._query("INSERT INTO ha_test.t1 VALUES (1, 'hello'), (2, 'world')")
    cnt = p0._query_one("SELECT COUNT(*) FROM ha_test.t1")
    check('source has 2 rows', cnt and cnt[0] == 2)
    check('server_version > 0', p0.server_version > 0, str(p0.server_version))
    check('sysid (server_uuid) is not None', p0.sysid is not None)

    row = p0._query_one("SHOW MASTER STATUS")
    check('SHOW MASTER STATUS returns binlog info', row is not None)

    # ===== Phase 3: Clone replica =====
    logger.info("\n=== Phase 3: Clone replica (p1) from primary (p0) ===")
    p1 = MySQL(make_config('p1', f'{TEST_DIR}/p1', P1_PORT, 2))
    leader = Member(0, 'p0', 0, {'conn_url': f'mysql://127.0.0.1:{P0_PORT}'})
    ok = p1.bootstrap.clone(leader)
    check('clone() returns True', ok)

    if ok:
        check('replica is_running() after clone', p1.is_running())
        data = p1._query("SELECT * FROM ha_test.t1")
        check('cloned data matches source', len(data) == 2)
        check('cloned data content', data[0][1] == 'hello')

        # ===== Phase 4: Configure replication =====
        logger.info("\n=== Phase 4: Configure GTID-based replication ===")
        p1.follow(leader)
        time.sleep(2)

        sl = p1._query_one("SHOW SLAVE STATUS")
        check('Slave_IO_Running', sl and sl[10] == 'Yes')
        check('Slave_SQL_Running', sl and sl[11] == 'Yes')
        check('replication_state == streaming', p1.replication_state() == 'streaming')

        # ===== Phase 5: Verify data replication =====
        logger.info("\n=== Phase 5: Verify data replication ===")
        p0._query("INSERT INTO ha_test.t1 VALUES (3, 'replicated')")
        time.sleep(1)
        r = p1._query("SELECT COUNT(*) FROM ha_test.t1")
        check('replicated row visible on replica', r and r[0][0] == 3)

        # ===== Phase 6: Promote replica =====
        logger.info("\n=== Phase 6: Promote replica (p1) to primary ===")
        check('promote() returns True', p1.promote(10))
        check('p1.is_primary() after promote', p1.is_primary())
        check('p1.is_primary() is True', p1.is_primary() is True)

        # ===== Phase 7: Demote and re-follow =====
        logger.info("\n=== Phase 7: Demote and re-follow ===")
        p1.demote()
        check('role == demoted after demote()', p1.role == 'demoted')
        p1.follow(leader)
        time.sleep(2)
        check('replication resumes after re-follow', p1.replication_state() == 'streaming')

    # ===== Cleanup =====
    logger.info("\n=== Cleanup ===")
    p0.stop()
    p1.stop()
    check('p0 stopped', not p0.is_running())
    check('p1 stopped', not p1.is_running())
    clean()

    # ===== Summary =====
    total = passed + failed
    logger.info("\n=== Results: %d/%d passed, %d failed ===\n", passed, total, failed)
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
