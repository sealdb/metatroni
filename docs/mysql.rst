.. _mysql:

==============================
MySQL high-availability support
==============================

.. warning::

   MySQL support is under active development and is **not yet recommended for
   production use**.

Patroni can manage MySQL high availability in addition to its native PostgreSQL
support. The MySQL backend provides:

- Automatic failover via a Distributed Configuration Store (etcd, Consul, ZooKeeper, …)
- GTID-based replication management
- Primary promotion and demotion
- Replica cloning via ``mysqldump`` or ``xtrabackup``
- REST API for cluster status and management
- ``patronictl`` compatibility

Architecture
============

Each MySQL node runs a Patroni instance that:

1. Maintains a leader lease in the DCS
2. Monitors MySQL health
3. Manages replication (``CHANGE MASTER TO`` / ``START SLAVE`` or Group Replication)
4. Executes failover when the primary becomes unavailable

::

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

Prerequisites
=============

- Python 3.8+
- ``pymysql`` (``pip install patroni[mysql]`` or ``pip install pymysql``)
- MySQL 8.0+ recommended (8.0.26+ for full GTID / naming support)
- A DCS: etcd, Consul, or ZooKeeper

Installation
============

Install Patroni with the MySQL extra:

.. code-block:: shell

    pip install 'patroni[mysql,etcd3]'

Generate a local multi-node layout with ``patroni_mysql_init``:

.. code-block:: shell

    patroni_mysql_init -o deploy/mysql-ha --force \
      --bin-dir /usr/local/mysql/bin --memory-pct 50

    # async / semi-sync (default) / MGR
    patroni_mysql_init -o deploy/mysql-mgr --mode mgr --nodes 3 --force

Templates live under ``templates/mysql/`` (xenon / radondb-ansible aligned).
Defaults write to ``deploy/mysql-ha/`` with per-node ``patroni.yml``, ``my.cnf``,
``data/``, plus ``start.sh`` / ``stop.sh``.

Configuration
=============

Set ``database.type: mysql`` and provide a ``mysql`` section (analogous to
``postgresql``).

Minimal example
---------------

.. code:: YAML

    name: mysql-node-1
    scope: mysql-cluster

    database:
      type: mysql

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

    etcd3:
      host: 127.0.0.1:2379

    bootstrap:
      dcs:
        ttl: 30
        loop_wait: 10
        retry_timeout: 10
        maximum_lag_on_failover: 1048576

``mysql`` section
-----------------

.. list-table::
   :header-rows: 1
   :widths: 22 12 18 48

   * - Parameter
     - Type
     - Default
     - Description
   * - ``name``
     - string
     - —
     - Patroni node name (unique in the cluster)
   * - ``scope``
     - string
     - —
     - Cluster name
   * - ``listen``
     - string
     - ``127.0.0.1:3306``
     - MySQL bind address:port
   * - ``connect_address``
     - string
     - ``listen``
     - Address other nodes use to reach this MySQL
   * - ``data_dir``
     - string
     - —
     - MySQL data directory
   * - ``config_dir``
     - string
     - ``data_dir``
     - Directory for ``my.cnf``
   * - ``bin_dir``
     - string
     - ``""``
     - Path to ``mysqld`` / ``mysql`` / ``mysqldump`` / ``mysqladmin`` (empty → ``$PATH``)
   * - ``port``
     - int
     - ``3306``
     - MySQL server port
   * - ``server_id``
     - int
     - ``1``
     - Unique ``server_id`` per node

Required replication parameters under ``mysql.parameters``:

.. code:: YAML

    parameters:
      server_id: "1"
      gtid_mode: "ON"
      enforce_gtid_consistency: "ON"
      log-bin: "mysql-bin"
      log_slave_updates: "ON"

Recommended extras: ``mysqlx: "OFF"``, ``binlog_format: "ROW"``, and a sensible
binlog expiry setting for your MySQL version.

Setup
=====

1. Install dependencies (``patroni[mysql,…]``).
2. Ensure MySQL binaries are on ``PATH`` or set ``bin_dir``.
3. Start Patroni: ``patroni patroni.yml``.
4. On first start Patroni initializes the data directory
   (``mysqld --initialize-insecure``), starts MySQL, and registers in the DCS.
5. Create the replication user on the primary if it was not created by bootstrap
   helpers:

   .. code-block:: sql

       CREATE USER IF NOT EXISTS 'replicator'@'%' IDENTIFIED BY 'rep-pass';
       GRANT REPLICATION SLAVE, REPLICATION CLIENT,
             SELECT, RELOAD, LOCK TABLES, PROCESS ON *.*
             TO 'replicator'@'%';
       FLUSH PRIVILEGES;

6. Start additional nodes. They clone from the leader and configure GTID
   replication (or join MGR when configured).

Management
==========

.. code-block:: shell

    patronictl -c patroni.yml list
    patronictl -c patroni.yml failover --master mysql-node-1 --candidate mysql-node-2
    patronictl -c patroni.yml restart mysql-node-2
    patronictl -c patroni.yml reinitialize mysql-node-2

REST API endpoints (``/patroni``, ``/primary``, ``/replica``, ``/health``,
``/cluster``, ``/restart``, ``/reinitialize``, ``/metrics``, …) behave like the
PostgreSQL backend; MySQL status exposes ``binlog`` (and ``gtid_set`` when
available) instead of ``xlog``.

HAProxy routing
---------------

``patroni_mysql_init`` writes a layout-local ``haproxy.cfg`` that uses Patroni
REST health checks (same pattern as the PostgreSQL demo):

- ``*:5000`` → current primary (``HEAD /primary``)
- ``*:5001`` → healthy replicas (``HEAD /replica``, round-robin)
- ``*:7000`` → HAProxy stats UI

.. code-block:: shell

    haproxy -f deploy/mysql-ha/haproxy.cfg -db
    mysql -h 127.0.0.1 -P 5000 -u root
    mysql -h 127.0.0.1 -P 5001 -u root -e 'SELECT @@read_only'

A static example matching default ports (MySQL ``3306-3308``, API ``8008-8010``)
is also committed as ``haproxy-mysql.cfg`` at the repository root.

For dynamic membership, adapt ``extras/confd/templates/haproxy.tmpl`` the same
way: keep ``conn_url`` / ``api_url`` from DCS member keys and check
``/primary`` or ``/replica``. ProxySQL can use the same REST endpoints as
mysql_galera_hostgroup / external health scripts if you prefer that stack.

Failover behavior
=================

1. Each node renews the DCS leader lease.
2. If the lease expires, healthy replicas race for leadership.
3. The winner promotes (``STOP SLAVE; RESET SLAVE ALL;`` for async / semi-sync)
   and accepts writes.
4. Other replicas follow the new primary.
5. A returning former primary is demoted and rejoins via GTID auto-positioning
   (there is no ``pg_rewind`` equivalent; Patroni skips rewind for MySQL).

Replication modes
=================

Mode is **configuration-selected**, not switched by a single online API call.
Runtime detection:

.. list-table::
   :header-rows: 1
   :widths: 18 52 30

   * - Mode
     - How Patroni decides
     - ``patroni_mysql_init --mode``
   * - **async GTID**
     - No ``group_replication_group_name``; no semi-sync plugins/params (or off)
     - ``async``
   * - **semi-sync**
     - ``rpl_semi_sync_*`` present; HA enforces quorum → ``super_read_only``
     - ``semi-sync`` (default)
   * - **MGR**
     - ``mysql.parameters.group_replication_group_name`` set (``is_mgr_configured()``)
     - ``mgr``

.. list-table:: Mode comparison
   :header-rows: 1
   :widths: 14 28 28 30

   * -
     - async
     - semi-sync
     - MGR
   * - Consistency
     - eventual
     - commit waits for ACK (``AFTER_SYNC``)
     - group certification
   * - Failover
     - DCS lock + promote / ``follow``
     - same + quorum read-only safety
     - MGR elects primary; majority-loss uses GTID election
   * - Channels
     - async slave
     - async + semi-sync plugins
     - GR + recovery (no async slave while ONLINE)
   * - Min nodes
     - 2 workable
     - 2 (timeout 10s) / 3+ (timeout ~∞)
     - 3

Switching modes
---------------

There is **no in-place hot switch**. Treat a mode change as a rebuild or carefully
orchestrated cutover. Always keep a backup / snapshot first.

**async ↔ semi-sync**

1. Optionally ``patronictl pause``.
2. Stop Patroni on every node; align ``rpl_semi_sync_*`` (or regenerate with
   ``--mode``).
3. Ensure ``plugin-load-add`` lists the correct plugin pair **before** plugin
   variables in ``my.cnf``.
4. Restart mysqld + Patroni; unpause.
5. Confirm ``SHOW STATUS LIKE 'Rpl_semi_sync_%'`` and ``patronictl list``.

**async / semi-sync → MGR**

Do not leave an async replication channel up while joining GR.

1. Drain writes; ``patronictl pause``.
2. ``STOP SLAVE; RESET SLAVE ALL;`` on each node.
3. Regenerate or edit configs with ``--mode mgr``.
4. Use ``mysql_native_password`` for the replication user (MGR recovery channel
   cannot use ``GET_MASTER_PUBLIC_KEY``).
5. Bootstrap GR on one node, then let others ``rejoin_mgr_group``.
6. Verify ``replication_group_members`` are ``ONLINE``; ``patronictl resume``.

**MGR → async / semi-sync**

1. Pause / drain writes.
2. ``STOP GROUP_REPLICATION`` on all members; remove ``group_replication_*``.
3. Pick the former MGR primary (or GTID-ahead node) as async primary; others
   ``follow``.
4. Enable semi-sync plugins after replicas are streaming if needed.
5. Resume Patroni HA.

MGR majority-loss and GTID fork
-------------------------------

On majority loss, members publish ``gtid_executed`` via ``enrich_dcs_data``.
Patroni elects a bootstrap winner with ``GTID_SUBSET`` (ties broken by node name).
Only a live DCS ``mgr_primary`` is treated as an existing group primary; stale
async-style ``primary`` roles do not block bootstrap. Rejoin waits until the
member reaches ``ONLINE`` or ``RECOVERING``.

If GTID sets are incomparable (fork), Patroni refuses automatic bootstrap, forces
``super_read_only``, and by default writes DCS ``pause: true`` plus an
``mgr_gtid_fork`` breadcrumb (disable with
``mysql.parameters.mgr_pause_on_gtid_fork: false``). After repair, run
``patronictl resume``.

Pitfalls
--------

- Do not run async ``follow()`` while MGR is configured (dual channel).
- Changing mode usually implies a new layout or wiping ``/service/<scope>/``.
- Physical ``xtrabackup`` clone must match MySQL major.minor; after restore
  Patroni drops donor ``auto.cnf`` so ``server_uuid`` is regenerated.

Known limitations
=================

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Topic
     - Notes
   * - Clone methods
     - ``mysqldump`` (default) and ``xtrabackup`` are implemented. Configure via
       ``mysql.create_replica_methods``.
   * - No ``pg_rewind``
     - ``needs_rewind=False``. Old primary rejoins by following the new primary
       (GTID auto-position + ``RESET SLAVE ALL``).
   * - Semi-sync
     - Xenon-style: ``AFTER_SYNC``, ``wait_no_slave=ON``, timeout ``10**18`` ms for
       3+ nodes, wait count ``(N-1)//2``. Quorum loss forces ``super_read_only``.
   * - MGR
     - Optional via ``group_replication_group_name``. Majority-loss GTID election
       and GTID-fork pause as above.
   * - Standby cluster
     - Not supported (assumes PostgreSQL WAL archiving).
   * - X Plugin
     - Defaults ``mysqlx=OFF`` to avoid multi-instance port conflicts.
   * - Auth
     - Async ``CHANGE MASTER`` may use ``GET_MASTER_PUBLIC_KEY=1``. MGR recovery
       uses ``mysql_native_password`` without that option.

Development notes
=================

The MySQL backend is a ``DatabaseHandler`` subclass:

::

    patroni/
      db/__init__.py        # DatabaseHandler ABC + factory
      mysql/
        __init__.py         # MySQL handler
        config.py           # my.cnf
        connection.py       # pymysql pool
        bootstrap.py        # initialize / clone
        postmaster.py       # mysqld process
        initcmd.py          # patroni_mysql_init
        versioning.py       # per-version parameter matrix
        misc.py

Unit tests: ``tests/test_mysql.py``, ``tests/test_mysql_init.py``,
``tests/test_mysql_versioning.py``.

Integration tests (require a local MySQL build), for example:

.. code-block:: shell

    MYSQL_BASE=/path/to/mysql PYTHONPATH=. \
      python3 -u integration-tests/test_mysql_patroni_ha.py

    MYSQL_BASE=/path/to/mysql PYTHONPATH=. \
      python3 -u integration-tests/test_mysql_mgr_patroni_ha.py

See also
========

- Templates: ``templates/mysql/README.md`` and ``templates/mysql/VERSIONS.md``
- Engineering progress notes: ``notes/TODO.md``
- `MySQL 8.0 GTID replication <https://dev.mysql.com/doc/refman/8.0/en/replication-gtids.html>`_
