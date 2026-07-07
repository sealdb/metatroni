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
| **Clone method** | Only `mysqldump` is implemented. For large databases, this will be slow. `xtrabackup` support is planned. |
| **No pg_rewind equivalent** | Patroni's pg_rewind logic is skipped for MySQL. Old primary rejoins by following the new primary. MySQL handles this gracefully via GTID auto-positioning and `RESET SLAVE ALL`. |
| **Synchronous replication** | Not yet supported. MySQL semi-sync replication integration is planned. |
| **Crash recovery** | MySQL handles crash recovery automatically on startup. Patroni monitors the recovery state. |
| **Replication slots** | Not applicable (MySQL uses GTID-based auto-positioning). |
| **Standby cluster** | Not supported. The standby cluster feature assumes PostgreSQL WAL archiving. |

### MySQL-Specific

| Limitation | Description |
|------------|-------------|
| **X Plugin port conflict** | MySQL 8.0 enables X Plugin (port 33060) by default. Multiple instances on the same host will conflict. Set `mysqlx=OFF` in parameters. |
| **`--single-transaction`** | Not used in clone dumps (was causing empty data in some configurations). Clone uses a consistent snapshot via `mysqldump`. |
| **User database dump** | Clone only dumps user databases (excludes `mysql`, `sys`, `performance_schema`, `information_schema`). |

## Running Integration Tests

```bash
# Prerequisites
pip install pymysql

# Clone repo and run test
cd /path/to/patroni
MYSQL_BASE=/usr/local/mysql python integration-tests/test_mysql_ha.py
```

The test exercises the complete HA flow:
1. Bootstrap primary
2. Clone replica
3. Configure replication
4. Verify data replication
5. Promote and demote
6. Clean up

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

To add xtrabackup support, modify `patroni/mysql/__init__.py`:

```python
# In create_replica or can_create_replica_without_replication_connection
def can_create_replica_without_replication_connection(self, methods=None):
    if methods is None:
        return True
    return any(m in ('mysqldump', 'xtrabackup', 'clone_plugin') for m in methods)
```

## Reference

- [Patroni Documentation](https://patroni.readthedocs.io/)
- [MySQL 8.0 GTID Replication](https://dev.mysql.com/doc/refman/8.0/en/replication-gtids.html)
- [mysqldump Options](https://dev.mysql.com/doc/refman/8.0/en/mysqldump.html)
