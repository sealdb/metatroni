# MySQL High-Availability with Patroni

> **Status:** Development — MySQL backend is under active development.
> Not yet recommended for production use.

## Overview

Patroni can manage MySQL high-availability in addition to its native PostgreSQL support.
The MySQL backend provides:

- Automatic failover via Distributed Configuration Store (etcd, Consul, ZooKeeper)
- GTID-based replication management
- Primary promotion and demotion
- Automatic replica cloning via `mysqldump`
- REST API for cluster status and management
- `patronictl` compatibility

## Architecture

```
           +--------------------------+
           |   DCS (etcd/Consul/...)  |
           +--------------------------+
                 ^            ^
                 |            |
        +--------+----+  +---+---------+
        |  Patroni    |  |  Patroni    |
        |  (primary)  |  |  (replica)  |
        |  mysqld     |  |  mysqld     |
        +-------------+  +-------------+
             |                  |
        3306/tcp           3307/tcp
```

Each MySQL node runs a Patroni instance that:
1. Maintains a leader lease in DCS
2. Monitors MySQL health
3. Manages replication (CHANGE MASTER TO / START SLAVE)
4. Executes failover when the primary becomes unavailable

## Prerequisites

- Python 3.8+
- `pymysql` Python package: `pip install pymysql`
- MySQL 8.0+ (recommended: 8.0.26+ for full GTID support)
- DCS: etcd, Consul, or ZooKeeper

## Configuration

### Minimal Configuration

```yaml
# patroni.yml

name: mysql-node-1
scope: mysql-cluster

database:
  type: mysql                    # REQUIRED: selects MySQL backend

mysql:
  name: mysql-node-1
  scope: mysql-cluster
  listen: 0.0.0.0:3306
  connect_address: 192.168.1.1:3306
  data_dir: /var/lib/mysql
  config_dir: /var/lib/mysql
  bin_dir: /usr/bin
  port: 3306
  server_id: 1

  authentication:
    superuser:
      username: root
      password: ""
    replication:
      username: replicator
      password: changeme

  parameters:
    server_id: "1"
    gtid_mode: "ON"
    enforce_gtid_consistency: "ON"
    log-bin: "mysql-bin"
    log_slave_updates: "ON"

restapi:
  listen: 0.0.0.0:8008
  connect_address: 192.168.1.1:8008

etcd:
  host: 127.0.0.1:2379

bootstrap:
  dcs:
    ttl: 30
    loop_wait: 10
    retry_timeout: 10
    maximum_lag_on_failover: 1048576
```

### Configuration Reference

#### `database.type`
- **Values:** `mysql`, `postgresql` (default)
- **Required:** Yes (to enable MySQL backend)

#### `mysql` section

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `name` | string | — | Patroni node name, must be unique in the cluster |
| `scope` | string | — | Cluster name |
| `listen` | string | `127.0.0.1:3306` | MySQL bind address:port |
| `connect_address` | string | `listen` value | Address other nodes use to connect to this MySQL |
| `data_dir` | string | — | MySQL data directory path |
| `config_dir` | string | `data_dir` | Directory for my.cnf |
| `bin_dir` | string | `""` | Path to MySQL binaries (mysqld, mysql, mysqldump, mysqladmin). If empty, uses `$PATH`. |
| `port` | int | 3306 | MySQL server port |
| `server_id` | int | 1 | MySQL server_id. Each node must have a unique value. |

#### `mysql.authentication`

| Parameter | Type | Description |
|-----------|------|-------------|
| `superuser.username` | string | MySQL root user (or user with ALL PRIVILEGES) |
| `superuser.password` | string | Password for superuser |
| `replication.username` | string | User for replication (must be created after bootstrap) |
| `replication.password` | string | Password for replication user |

#### `mysql.parameters`

Standard MySQL server options. The following **must** be set for replication:

```yaml
parameters:
  server_id: "1"              # Unique per node
  gtid_mode: "ON"             # Required for GTID-based replication
  enforce_gtid_consistency: "ON"  # Required for GTID-based replication
  log-bin: "mysql-bin"        # Enable binary logging
  log_slave_updates: "ON"     # Required for cascading replication
```

Additional recommended parameters:

```yaml
parameters:
  mysqlx: "OFF"               # Disable X Plugin (prevents port conflicts)
  binlog_format: "ROW"        # Row-based replication
  expire_logs_days: "7"       # Auto-purge old binlogs
  slave_parallel_workers: "4" # Parallel replication
```

### Complete Cluster Example

#### Node 1 — Primary candidate

```yaml
name: mysql-node-1
scope: mysql-cluster

database:
  type: mysql

mysql:
  name: mysql-node-1
  scope: mysql-cluster
  listen: 0.0.0.0:3306
  connect_address: 192.168.1.1:3306
  data_dir: /data/mysql
  bin_dir: /usr/local/mysql/bin
  port: 3306
  server_id: 1

  authentication:
    superuser:
      username: root
      password: ""
    replication:
      username: replicator
      password: rep-pass

  parameters:
    server_id: "1"
    gtid_mode: "ON"
    enforce_gtid_consistency: "ON"
    log-bin: "mysql-bin"
    log_slave_updates: "ON"
    mysqlx: "OFF"
    binlog_format: "ROW"

restapi:
  listen: 0.0.0.0:8008
  connect_address: 192.168.1.1:8008

etcd:
  host: 127.0.0.1:2379

bootstrap:
  dcs:
    ttl: 30
    loop_wait: 10
    retry_timeout: 10
    maximum_lag_on_failover: 1048576
```

#### Node 2 — Replica

Same config, change: `name`, `listen`, `connect_address`, `server_id`, `port`

```yaml
name: mysql-node-2
# ...
mysql:
  listen: 0.0.0.0:3307
  connect_address: 192.168.1.2:3307
  port: 3307
  server_id: 2
  # ...
restapi:
  listen: 0.0.0.0:8009
  connect_address: 192.168.1.2:8009
```

## Setup Steps

### 1. Install Dependencies

```bash
pip install patroni pymysql python-etcd
```

### 2. Prepare MySQL Installation

Ensure MySQL binaries are available. Symlink or set `bin_dir`:

```bash
# Verify binaries exist
ls /usr/local/mysql/bin/mysqld /usr/local/mysql/bin/mysql /usr/local/mysql/bin/mysqldump /usr/local/mysql/bin/mysqladmin
```

### 3. Configure and Start Patroni

```bash
patroni patroni.yml
```

On the first start, Patroni will:
1. Initialize the MySQL data directory (`mysqld --initialize-insecure`)
2. Start MySQL
3. Register the node in DCS
4. Wait for cluster initialization

### 4. Bootstrap the Cluster

The first node to start becomes the primary. After bootstrap, you must create the replication user:

```sql
-- Connect to the primary MySQL
mysql -h 127.0.0.1 -P 3306 -u root

CREATE USER IF NOT EXISTS 'replicator'@'%' IDENTIFIED BY 'rep-pass';
GRANT REPLICATION SLAVE, REPLICATION CLIENT,
      SELECT, RELOAD, LOCK TABLES, PROCESS ON *.*
      TO 'replicator'@'%';
FLUSH PRIVILEGES;
```

### 5. Add Replica Nodes

Start Patroni on the second node. It will:
1. Detect the cluster leader in DCS
2. Clone data from the leader via `mysqldump`
3. Configure GTID-based replication with `CHANGE MASTER TO`
4. Start the replica (`START SLAVE`)

## Management Commands

### Check Cluster Status

```bash
patronictl -c patroni.yml list
```

### Manual Failover

```bash
patronictl -c patroni.yml failover --master mysql-node-1 --candidate mysql-node-2
```

### Restart MySQL

```bash
patronictl -c patroni.yml restart mysql-node-2
```

### Reinitialize Replica

```bash
patronictl -c patroni.yml reinitialize mysql-node-2
```

## REST API

Patroni exposes a REST API on each node:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/patroni` | GET | Node status (role, state, binlog position) |
| `/primary` | GET | 200 if this node is primary |
| `/replica` | GET | 200 if this node is a healthy replica |
| `/health` | GET | 200 if MySQL is running |
| `/cluster` | GET | Cluster topology |
| `/config` | GET | Dynamic configuration |
| `/restart` | POST | Schedule MySQL restart |
| `/reload` | POST | Reload Patroni config |
| `/reinitialize` | POST | Reinitialize replica |
| `/metrics` | GET | Prometheus metrics |

### Example: Check Node Status

```bash
curl -s http://127.0.0.1:8008/patroni | python -m json.tool
```

Response:
```json
{
    "state": "running",
    "role": "primary",
    "server_version": 80035,
    "binlog": {
        "location": 12345,
        "binlog_file": "mysql-bin.000001"
    },
    "replication_state": "primary",
    "patroni": {
        "version": "4.1.3",
        "scope": "mysql-cluster",
        "name": "mysql-node-1"
    }
}
```

### Example: Check Metrics

```bash
curl -s http://127.0.0.1:8008/metrics
```

## Failover Behavior

### How Failover Works

1. Patroni on each node maintains a heartbeat loop and periodically updates the leader lease in DCS
2. If the leader lease expires (node crash, network partition, etc.), replicas detect the absence of the leader lock
3. Replicas evaluate their health and binlog position to determine the best candidate
4. The healthiest replica acquires the leader lock and promotes itself:
   - Executes `STOP SLAVE; RESET SLAVE ALL;`
   - Node is now the new primary, accepting writes
5. Other replicas follow the new primary

### What Happens to the Old Primary

When the former primary comes back:
1. Patroni detects it was formerly primary but no longer has the leader lock
2. The node is demoted and follows the current primary
3. Replication is re-established from the new primary

## Known Limitations

### Current (Development)

| Limitation | Description |
|------------|-------------|
| **Clone methods** | `mysqldump` (default) and `xtrabackup` are both implemented and integration-tested. Configure via `mysql.create_replica_methods`. xtrabackup must match the MySQL major.minor (e.g. 8.0.35). |
| **No pg_rewind equivalent** | Patroni's pg_rewind logic is skipped for MySQL (`needs_rewind=False`). Old primary rejoins by following the new primary. MySQL handles this via GTID auto-positioning and `RESET SLAVE ALL`. |
| **Semi-synchronous replication** | Templates and runtime enforce xenon-style strong consistency: `wait_point=AFTER_SYNC`, `wait_no_slave=ON`, timeout `10**18` ms for 3+ nodes (no async degrade), wait count `(N-1)//2`. Quorum loss still forces `super_read_only`. |
| **MGR (Group Replication)** | Optional: when `group_replication_group_name` is set, Patroni follows MGR primary/secondary. On majority loss, nodes elect a bootstrapper from DCS-published `gtid_executed` (GTID_SUBSET); the winner bootstraps only with the leader lock; a lock holder that is behind yields the lock; others rejoin. Incomparable GTID sets refuse election. Validated by `integration-tests/test_mysql_mgr_e2e.py` (3-node GR). |
| **Crash recovery** | MySQL handles crash recovery automatically on startup. Patroni `start()` / `follow()` wait until the socket accepts connections. |
| **Replication slots** | Not applicable (MySQL uses GTID-based auto-positioning). |
| **Standby cluster** | Not supported. The standby cluster feature assumes PostgreSQL WAL archiving. |
| **Full Patroni+DCS E2E** | Validated by `integration-tests/test_mysql_patroni_ha.py` (etcd3, dual Patroni, failover + rejoin). |

## Config bootstrap (`patroni_mysql_init`)

Templates (committed): ``templates/mysql/`` — aligned with xenon / radondb-ansible /
xenon-mgr (see ``templates/mysql/README.md``).

Default generate path (project-local): ``deploy/mysql-ha/``

```bash
PYTHONPATH=. python3 -m patroni.mysql.initcmd --force \
  --bin-dir /usr/local/mysql/bin --memory-pct 50

# Absolute per-node buffer pool / MGR
patroni_mysql_init -o deploy/mysql-mgr --nodes 3 --innodb-buffer-pool-size 2G --mode mgr --force
```

Defaults:
- Version: auto-detect via `mysqld --version`, or `--mysql-version 5.6|5.7|8.0|8.x|9.x`
- Parameters from `patroni.mysql.versioning` (see `templates/mysql/VERSIONS.md`)
- Memory budget = `MemTotal × --memory-pct` (default **50%**), split evenly across local nodes
- Xenon semi-sync: source/master OFF at boot; `AFTER_SYNC` where supported; timeout `1e18` (≥3 nodes)
- Durability: `sync_binlog=1`, `innodb_flush_log_at_trx_commit=1`
- Layout: `<out>/<name>/patroni.yml`, `my.cnf`, `data/`, plus `start.sh` / `stop.sh`

### MySQL-Specific

| Limitation | Description |
|------------|-------------|
| **X Plugin port conflict** | MySQL 8.0 enables X Plugin (port 33060) by default. Patroni defaults `mysqlx=OFF` in `my.cnf` to avoid multi-instance conflicts. |
| **Logical clone and system users** | `mysqldump` clone only dumps user databases. Patroni calls `ensure_replication_user()` after clone and on promote (with `sql_log_bin=0`) so the replication account exists on every primary candidate. |
| **Physical clone UUID** | After xtrabackup restore, Patroni removes donor `auto.cnf` so mysqld generates a new `server_uuid`. |
| **caching_sha2_password** | Async `CHANGE MASTER` sets `GET_MASTER_PUBLIC_KEY=1` for MySQL 8 replication auth over TCP. The `group_replication_recovery` channel rejects that option (ER 3139), so the replication user is created with `mysql_native_password` for MGR distributed recovery without TLS. |
| **No timelines / sysid match** | `has_timelines=False`; `requires_sysid_match=False` (each MySQL instance has its own `server_uuid`). |

## Running Integration Tests

```bash
# Prerequisites
pip install pymysql
# Optional for physical clone: Percona XtraBackup matching MySQL version

MYSQL_BASE=/home/wslu/work/mysql/mysql80-debug

# Handler-level async GTID HA (failover + rejoin)
python3 integration-tests/test_mysql_ha.py

# Full Patroni + etcd3
PYTHONPATH=. python3 -u integration-tests/test_mysql_patroni_ha.py

# Semi-sync quorum → read_only / restore
PYTHONPATH=. python3 -u integration-tests/test_mysql_semi_sync.py

# xtrabackup clone + stream
PYTHONPATH=. python3 -u integration-tests/test_mysql_xtrabackup.py

# 3-node MGR majority-loss GTID election E2E
PYTHONPATH=. python3 -u integration-tests/test_mysql_mgr_e2e.py
```

Handler HA flow:
1. Bootstrap primary
2. Clone replica (mysqldump)
3. Configure GTID replication
4. Verify data replication
5. Failover (stop primary, promote replica, write)
6. Old primary rejoin (restart, demote, follow)
7. Verify catch-up

### Semi-sync config sketch

```yaml
mysql:
  parameters:
    rpl_semi_sync_source_enabled: ON
    rpl_semi_sync_replica_enabled: ON
    cluster_size: 3   # Patroni-only; not written to my.cnf
```

### xtrabackup config sketch

```yaml
mysql:
  create_replica_methods:
    - xtrabackup
    - mysqldump   # fallback
```

### MGR majority-loss GTID election

1. Every HA cycle, `touch_member` publishes `gtid_executed` via `enrich_dcs_data`.
2. If local MGR status is empty, each node runs `select_mgr_bootstrap_winner`:
   - drop candidates that are a strict GTID subset of another;
   - among equal maximal sets, pick the lexicographically smallest name;
   - if maximal sets are incomparable → **GTID fork** (see below).
3. Winner + holds DCS lock → `bootstrap_mgr_group()`.
4. Lock holder that is not the winner → `mgr_yield_lock` → release leader key.
5. Non-winners → wait / `rejoin_mgr_group` once a primary is advertised.
6. While racing for the lock after a yield, `_is_healthiest_node` compares GTIDs
   (not binlog file offsets) when MGR is configured.

### MGR GTID fork (incomparable sets)

When two or more members each hold transactions the others lack, automatic
bootstrap is unsafe. Patroni then:

1. Logs a `CRITICAL` alert with each maximal member's `gtid_executed`.
2. Forces `super_read_only` on the detecting node.
3. Returns `mgr_gtid_fork` from `run_mgr_cycle` (no bootstrap).
4. By default writes DCS `pause: true` plus a `mgr_gtid_fork` breadcrumb so
   autofailover stops (`patronictl pause` equivalent). Disable with
   `mysql.parameters.mgr_pause_on_gtid_fork: false`.
5. Publishes `mgr_gtid_fork` on the member key and `/patroni` until the group
   is healthy again.

Operator recovery: repair/reconcile GTIDs (or rebuild the divergent node),
then `patronictl resume`.

```bash
# Handler-level election helpers (no real multi-member GR)
PYTHONPATH=. python3 -u integration-tests/test_mysql_mgr_election.py

# Real 3-node GR: form group → STOP all → n2-only GTID advance → bootstrap + rejoin
PYTHONPATH=. python3 -u integration-tests/test_mysql_mgr_e2e.py

# etcd3 + 3 Patroni processes (HA loops drive recovery)
PYTHONPATH=. python3 -u integration-tests/test_mysql_mgr_patroni_ha.py
```

MGR E2E notes:
- Local MGR port = client port + 10 (avoids `port*10+1` overflow).
- `get_mgr_status` reads `performance_schema.replication_group_members` (primary via subquery; `@@group_replication_primary_member` is not a sysvar).
- Recovery channel: `CHANGE MASTER ... FOR CHANNEL 'group_replication_recovery'` without `GET_MASTER_PUBLIC_KEY`.

## Development

### Adding MySQL Support

The MySQL backend is implemented as a `DatabaseHandler` ABC subclass:

```
patroni/
  db/__init__.py        # DatabaseHandler ABC + factory
  mysql/
    __init__.py         # MySQL (main class)
    config.py           # my.cnf configuration management
    connection.py       # pymysql connection pool
    bootstrap.py        # Initialize, clone, post_bootstrap
    postmaster.py       # mysqld process management
    misc.py             # Enums, version parsing
```

### Implementing a Custom Clone Method

`create_replica_methods` already supports `mysqldump` and `xtrabackup`. To add another method, extend `Bootstrap.create_replica()` in `patroni/mysql/bootstrap.py` and list the name in `can_create_replica_without_replication_connection()`.

```yaml
mysql:
  create_replica_methods:
    - xtrabackup
    - mysqldump   # fallback
```

## Reference

- [Patroni Documentation](https://patroni.readthedocs.io/)
- [MySQL 8.0 GTID Replication](https://dev.mysql.com/doc/refman/8.0/en/replication-gtids.html)
- [mysqldump Options](https://dev.mysql.com/doc/refman/8.0/en/mysqldump.html)
