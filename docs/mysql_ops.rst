.. _mysql_ops:

=============================
MySQL operations and FAQ
=============================

Operator guide: install, deploy, day-2 management, mode cutovers, HAProxy, and
common failures.

.. contents::
   :local:
   :depth: 2

Prerequisites
=============

- Python 3.8+
- MySQL 8.0+ recommended (8.0.26+ for ``source``/``replica`` naming); 5.7 supported
  via versioning templates
- ``pip install 'patroni[mysql,etcd3]'`` (or another DCS extra)
- DCS reachable from every node (etcd **3.x** → use ``etcd3:`` in YAML)
- Optional: Percona XtraBackup matching MySQL major.minor
- Optional: HAProxy for primary/replica routing

Install
=======

.. code-block:: shell

    pip install 'patroni[mysql,etcd3]'

    # verify
    python -c 'import pymysql; import patroni; print(patroni.__version__)'
    mysqld --version

Generate a local multi-node layout (single host, staggered ports):

.. code-block:: shell

    patroni_mysql_init -o deploy/mysql-ha --force \
      --bin-dir /usr/local/mysql/bin \
      --memory-pct 50 \
      --mode semi-sync \
      --nodes 3

Outputs per node: ``patroni.yml``, ``my.cnf``, ``data/``, plus cluster helpers
``start.sh``, ``stop.sh``, ``haproxy.cfg``, ``README.md``,
``cluster-summary.yaml``.

Useful flags
------------

.. list-table::
   :header-rows: 1
   :widths: 28 28 44

   * - Flag
     - Example
     - Meaning
   * - ``--mode``
     - ``async|semi-sync|mgr``
     - Replication template
   * - ``--nodes``
     - ``3``
     - Local instance count (MGR requires ≥3)
   * - ``--mysql-version``
     - ``8.0.35``
     - Skip auto-detect / pin family
   * - ``--innodb-buffer-pool-size``
     - ``2G``
     - Per-node absolute BP (overrides pct)
   * - ``--create-replica-methods``
     - ``xtrabackup,mysqldump``
     - Clone order
   * - ``--etcd``
     - ``127.0.0.1:2379``
     - DCS endpoints

Deploy checklist
================

1. Start DCS (etcd/Consul/ZK). Prefer odd-sized DCS clusters.
2. Ensure unique ``server_id`` / ports / ``connect_address`` per node.
3. Start Patroni on the first node → initializes datadir if empty.
4. Confirm REST ``/primary`` and ``patronictl list``.
5. Start remaining nodes → clone + replicate (or MGR join).
6. (Optional) Start HAProxy with the generated ``haproxy.cfg``.
7. Smoke-test writes through ``:5000`` and reads through ``:5001``.

Multi-host production sketch
----------------------------

On each host, use a real ``connect_address``, unique ``server_id``, shared
``scope`` / ``group_replication_group_name`` (MGR), and the same replication
password. Do **not** share ``data_dir``. Prefer generating once with
``patroni_mysql_init`` then editing hostnames, or maintaining Ansible/Helm from
``templates/mysql/``.

Configuration reference (short)
===============================

Required selector:

.. code:: YAML

    database:
      type: mysql

Minimal ``mysql`` block:

.. code:: YAML

    mysql:
      name: mysql-node-1
      scope: mysql-cluster
      listen: 0.0.0.0:3306
      connect_address: 10.0.0.1:3306
      data_dir: /var/lib/mysql
      bin_dir: /usr/local/mysql/bin
      port: 3306
      server_id: 1
      authentication:
        superuser:
          username: root
          password: "s3cret"
        replication:
          username: replicator
          password: "rep-pass"
      parameters:
        server_id: "1"
        gtid_mode: "ON"
        enforce_gtid_consistency: "ON"
        log-bin: "mysql-bin"
        log_slave_updates: "ON"
        mysqlx: "OFF"

See :ref:`mysql` and ``templates/mysql/VERSIONS.md`` for version-specific names
(``source``/``replica`` vs ``master``/``slave``, binlog expiry, redo capacity).

Day-2 operations
================

Status
------

.. code-block:: shell

    patronictl -c /path/to/patroni.yml list
    curl -s http://127.0.0.1:8008/patroni | jq .
    curl -s http://127.0.0.1:8008/cluster | jq .

Switchover / failover
---------------------

.. code-block:: shell

    # planned
    patronictl -c patroni.yml switchover --master mysql0 --candidate mysql1

    # unplanned / force candidate
    patronictl -c patroni.yml failover --master mysql0 --candidate mysql1

Restart / reload / rebuild replica
----------------------------------

.. code-block:: shell

    patronictl -c patroni.yml restart mysql1
    patronictl -c patroni.yml reload mysql1
    patronictl -c patroni.yml reinitialize mysql1   # wipe + reclone

Pause autofailover
------------------

.. code-block:: shell

    patronictl -c patroni.yml pause
    # … maintenance …
    patronictl -c patroni.yml resume

Standby cluster (cross-site cascade)
------------------------------------

MySQL standby sites use **full clone + GTID cascade**, not WAL archive /
``restore_command``. Prefer physical clone:

.. code-block:: yaml

    bootstrap:
      dcs:
        standby_cluster:
          host: primary-site.example
          port: 3306
          create_replica_methods:
            - xtrabackup
            - mysqldump   # fallback when xtrabackup binary is missing

Or force logical clone only: ``create_replica_methods: [mysqldump]``.

- **standby leader** holds the DCS lock, replicates from the remote primary,
  stays ``super_read_only``.
- Local members cascade from the standby leader.
- Promote: ``patronictl promote-cluster`` (removes ``standby_cluster``).
- Demote back: ``patronictl demote-cluster --host … --port …``.

Use a **separate DCS scope** from the primary site. Member names must be unique
across sites connected by replication.

HAProxy
=======

Generated ``haproxy.cfg`` (and root example ``haproxy-mysql.cfg``):

.. list-table::
   :header-rows: 1
   :widths: 18 18 64

   * - Listen
     - Port
     - Health check
   * - primary
     - ``*:5000``
     - ``HEAD /primary`` → 200
   * - replicas
     - ``*:5001``
     - ``HEAD /replica`` → 200
   * - stats
     - ``*:7000``
     - HAProxy stats UI

.. code-block:: shell

    haproxy -f deploy/mysql-ha/haproxy.cfg -db
    mysql -h 127.0.0.1 -P 5000 -u root -p
    mysql -h 127.0.0.1 -P 5001 -u root -p -e 'SELECT @@read_only, @@super_read_only'

For dynamic membership, adapt ``extras/confd/templates/haproxy.tmpl`` (same
``conn_url`` / ``api_url`` pattern as PostgreSQL).

Replication mode cutovers
=========================

**No online hot switch.** Always snapshot/backup first.

async ↔ semi-sync
-----------------

1. ``patronictl pause`` (recommended).
2. Stop Patroni; align ``rpl_semi_sync_*`` + ``plugin-load-add`` order in
   ``my.cnf`` / YAML (or regenerate ``--mode``).
3. Restart mysqld + Patroni; ``patronictl resume``.
4. Verify ``SHOW STATUS LIKE 'Rpl_semi_sync_%'`` and that primary is writable
   only with quorum.

async / semi-sync → MGR
-----------------------

1. Drain writes; pause.
2. ``STOP SLAVE; RESET SLAVE ALL;`` on every node (GR rejects dual channels).
3. Install MGR parameters (shared UUID, seeds, local port = client+10).
4. Replication user: ``mysql_native_password`` (no ``GET_MASTER_PUBLIC_KEY`` on
   recovery channel).
5. Bootstrap one node; others ``rejoin_mgr_group`` via Patroni.
6. Confirm ``replication_group_members`` all ``ONLINE``; resume.

MGR → async / semi-sync
-----------------------

1. Pause; ``STOP GROUP_REPLICATION`` everywhere; remove GR config.
2. Choose GTID-ahead / former primary as async source; others ``follow``.
3. Enable semi-sync after streaming if needed; resume.

Prefer wiping ``/service/<scope>/`` after a clean stop when changing mode so
stale member roles do not confuse election.

Monitoring hooks
================

- REST ``/metrics`` — Prometheus-style gauges (binlog location substituted for
  xlog where applicable)
- DCS member ``gtid_executed`` — MGR election input
- ``mgr_gtid_fork`` on member / ``/patroni`` — split-brain GTID alert
- Semi-sync: watch ``Rpl_semi_sync_*_clients`` and primary ``read_only``

Integration tests (dev)
=======================

.. code-block:: shell

    MYSQL_BASE=/path/to/mysql PYTHONPATH=. \
      python3 -u integration-tests/test_mysql_patroni_ha.py

    MYSQL_BASE=/path/to/mysql PYTHONPATH=. \
      python3 -u integration-tests/test_mysql_semi_sync.py

    MYSQL_BASE=/path/to/mysql PYTHONPATH=. \
      python3 -u integration-tests/test_mysql_mgr_patroni_ha.py

FAQ / troubleshooting
=====================

``patronictl list`` empty / no leader
------------------------------------

- Check DCS connectivity (``etcdctl endpoint health``).
- Confirm all nodes share ``scope`` and ``namespace``.
- For etcd 3.x, YAML must use ``etcd3:``, not ``etcd:``.

Replica never becomes ``streaming``
-----------------------------------

- Verify replication user/password and grants.
- On MySQL 8 async, ensure ``GET_MASTER_PUBLIC_KEY`` path works or use
  ``mysql_native_password``.
- Inspect ``SHOW SLAVE STATUS`` / ``SHOW REPLICA STATUS`` for ``Last_IO_Error``.
- Reclone: ``patronictl reinitialize <name>``.

Semi-sync primary stuck read-only
---------------------------------

Expected when connected semi-sync replicas are below quorum ``(N-1)//2``. Restore
replicas or temporarily adjust ``cluster_size`` only with care. Check
``Rpl_semi_sync_*_clients``.

MGR group will not form
-----------------------

- Need ≥3 nodes and matching ``group_replication_group_name``.
- Local MGR port defaults to ``mysql_port + 10`` (avoid overflow schemes).
- ``caching_sha2_password`` + ``GET_MASTER_PUBLIC_KEY`` fails on recovery
  channel (ER 3139) → use ``mysql_native_password``.
- Query ``performance_schema.replication_group_members`` (not
  ``@@group_replication_primary_member``, which is not a sysvar).

Majority lost; cluster paused / ``mgr_gtid_fork``
------------------------------------------------

- Incomparable ``gtid_executed`` sets → automatic bootstrap refused.
- Repair data (rebuild divergent node) then ``patronictl resume``.
- Disable auto-pause only if you accept risk:
  ``mysql.parameters.mgr_pause_on_gtid_fork: false``.

Old primary does not rejoin after failover
------------------------------------------

- MySQL demote must release the leader lock on graceful/immediate paths.
- Confirm ``follow()`` toward the new primary and GTID auto-position.
- Check logs for demote/follow errors; no rewind step is expected.

xtrabackup clone fails
----------------------

- XtraBackup major.minor must match MySQL.
- Ensure ``BACKUP_ADMIN`` (or equivalent) grants on the donor.
- On failure Patroni should clean partial datadir; retry or fall back to
  ``mysqldump`` in ``create_replica_methods``.

Port conflicts / X Plugin
-------------------------

- Default ``mysqlx=OFF`` in generated ``my.cnf``.
- Multi-instance on one host: stagger MySQL and REST ports
  (``patroni_mysql_init`` does this).

Switchover loops forever
------------------------

- Usually the demoting primary did not release the DCS lock. Upgrade to a
  build that includes graceful MySQL demote lock release, or manually delete
  the leader key and ``follow`` the intended primary.

Known limitations (ops view)
============================

- MySQL standby cluster uses **clone + GTID cascade** (not WAL archive /
  ``restore_command``). Prefer ``create_replica_methods: [xtrabackup, mysqldump]``.
- No ``pg_rewind`` equivalent
- Mode changes are rebuild/cutover, not hot switch
- Still under active development — validate with your workload and the
  integration suite before production
