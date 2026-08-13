.. _mysql_ops:

=============================
MySQL operations and FAQ
=============================

Operator guide: install, deploy, day-2 management, standby promote/demote
cutovers, mode changes, HAProxy, and common failures.

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
          host: primary-site.example   # or VIP / first writable endpoint
          port: 3306
          create_replica_methods:
            - xtrabackup
            - mysqldump   # fallback when xtrabackup binary is missing

Or force logical clone only: ``create_replica_methods: [mysqldump]``.

Topology rules
~~~~~~~~~~~~~~

- Use a **separate DCS scope** (and usually a separate etcd/Consul cluster) for
  the standby site. Do **not** share ``scope`` / namespace with the primary site.
- Member ``name`` values must be unique across both sites.
- **standby leader** holds the standby-site DCS lock, replicates from the
  remote primary, stays ``super_read_only``.
- Local members cascade from the standby leader (same site).
- Within each site, ``switchover`` / ``failover`` still work; they do **not**
  move the writable role across sites. Cross-site cutover uses
  ``promote-cluster`` / ``demote-cluster`` below.

Day-0: bootstrap the standby site
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. Primary site is healthy and accepting replication (``replicator`` user,
   GTID on, binlogs retained long enough for the clone window).
2. Generate / write standby-site Patroni YAML with ``standby_cluster.host`` /
   ``port`` pointing at the primary-site writable endpoint (or a stable VIP).
3. Start the first standby-site node. It clones (xtrabackup preferred), then
   becomes ``standby_leader`` and streams with ``MASTER_AUTO_POSITION=1``.
4. Start remaining standby-site nodes; they clone from the local standby
   leader and cascade.
5. Verify:

   .. code-block:: shell

       # on standby site
       patronictl -c standby0.yml list
       curl -s http://127.0.0.1:<api>/patroni | jq '{role,state,replication_state}'
       # expect role=standby_leader on the lock holder; replica elsewhere
       mysql -h127.0.0.1 -P<stb_port> -e "SELECT @@super_read_only; SHOW SLAVE STATUS\\G"

Health checks before any cutover
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- Primary site: ``patronictl list`` shows one ``primary``, replicas streaming.
- Standby site: one ``Standby Leader``, others ``Replica``, no growing lag.
- Compare a user table / GTID progress after a test insert on the primary.
- Application / LB: know which VIP points at which site; prepare DNS/LB change.
- Agree STONITH: who fences the old writable site if promote is forced.

.. warning::

   Promoting the standby while the primary site is still accepting writes
   creates a **split-brain**. Always fence (STONITH) or pause/stop writes on
   the old primary site before ``promote-cluster``, unless that site is already
   confirmed down.

Planned promote (standby site becomes writable)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use when you intentionally move the writable role to the standby site
(maintenance window or controlled DR drill).

1. **Freeze writes on the primary site** (preferred order):

   - Stop application writers, or
   - ``patronictl -c primary0.yml pause`` and set the primary ``super_read_only``
     / take the primary VIP offline, or
   - Stop Patroni + mysqld on the primary site after a final flush.

2. **Wait for standby catch-up** (Seconds_Behind_Master ≈ 0 / GTID caught up).

3. **Promote the standby cluster** (run against a standby-site config):

   .. code-block:: shell

       patronictl -c standby0.yml promote-cluster --force
       # removes DCS standby_cluster; standby_leader STOP SLAVE → writable primary

4. Confirm standby site:

   .. code-block:: shell

       patronictl -c standby0.yml list   # Leader = former standby_leader
       mysql ... -e "SELECT @@read_only, @@super_read_only"   # both 0/OFF
       curl -s http://127.0.0.1:<stb_api>/primary   # expect HTTP 200

5. Point application / LB / DNS at the **new** primary site.
6. Do **not** start the old site as a second writable primary. Either leave it
   down, or demote it (next section) so it follows the new primary.

Demote a former primary site into a standby
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

After a successful promote, convert the old primary site so it cascades from
the new primary (roles reversed).

1. Ensure the **new** primary site is healthy and writable.
2. On the **old** site (still has its own DCS scope), demote:

   .. code-block:: shell

       patronictl -c old_primary0.yml demote-cluster \
         --host <new-primary-vip-or-host> --port 3306 --force
       # writes standby_cluster into DCS; former primary follows remote as
       # standby_leader (super_read_only)

3. Verify old site shows ``Standby Leader`` / ``Replica`` and streams from the
   new primary. If GTID history diverged while both were writable, **rebuild**
   the old site from a fresh clone instead of demote (no ``pg_rewind`` for MySQL).

Planned cross-site switchover (drill checklist)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Typical two-site flip (Site A writable → Site B writable → optionally A as
standby):

.. list-table::
   :header-rows: 1
   :widths: 8 42 50

   * - #
     - Action
     - Verify
   * - 1
     - Announce maintenance; snapshot / backup both sites
     - Backup OK
   * - 2
     - Stop writers on Site A (app + optional pause)
     - No new commits on A
   * - 3
     - Wait Site B catch-up
     - Lag ≈ 0; test row visible on B
   * - 4
     - ``promote-cluster`` on Site B
     - B ``/primary`` = 200; ``super_read_only`` OFF
   * - 5
     - Cut LB/DNS to Site B
     - App writes succeed on B
   * - 6
     - Fence or stop Site A writers if still up
     - No dual-primary
   * - 7
     - ``demote-cluster --host <B> --port …`` on Site A **or** rebuild A
     - A is standby_leader/replica streaming from B
   * - 8
     - Resume monitoring; document new “primary site”
     - Both ``patronictl list`` clean

Disaster promote (primary site unavailable)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. Confirm Site A is down or unreachable (network / DC failure). Prefer
   fencing power/storage if there is any doubt.
2. ``patronictl -c standby0.yml promote-cluster --force`` on Site B.
3. Retarget LB/DNS to Site B.
4. When Site A returns: **do not** start it as primary. Either
   ``demote-cluster`` toward B (if GTID still continuous) or wipe and reclone
   as a new standby site.

Rollback after a bad promote
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If you promoted B by mistake while A was still writable:

1. Stop writers on **both** sites immediately.
2. Decide the source of truth (usually the site with the wanted commits).
3. Rebuild the other site from a full clone; do not rely on automatic rewind.
4. Re-establish ``standby_cluster`` only on the secondary site.

Commands cheat-sheet
~~~~~~~~~~~~~~~~~~~~

.. code-block:: shell

    # Standby site status
    patronictl -c standby0.yml list
    curl -s http://127.0.0.1:<api>/standby-leader   # 200 on standby leader
    curl -s http://127.0.0.1:<api>/leader           # 200 for lock holder (standby or real)

    # Promote standby cluster → standalone primary
    patronictl -c standby0.yml promote-cluster [--force]

    # Demote standalone cluster → standby of remote
    patronictl -c siteA0.yml demote-cluster --host <remote> --port 3306 [--force]

    # Inspect DCS dynamic config (standby_cluster present or not)
    patronictl -c standby0.yml show-config

MySQL-specific notes for ``demote-cluster``: pass ``--host`` / ``--port`` of
the remote primary. ``--restore-command`` / ``--primary-slot-name`` are
PostgreSQL-oriented and unused for MySQL GTID cascade.

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

Standby promote / demote problems
---------------------------------

- ``promote-cluster`` leaves node read-only: check Patroni logs for
  ``STOP SLAVE`` / ``set_read_write`` failures; confirm DCS no longer has
  ``standby_cluster`` (``patronictl show-config``).
- After demote, old site is not ``standby_leader``: ensure ``--host``/``--port``
  reach the **new** primary and replication credentials work; look for
  ``CHANGE MASTER`` / GTID errors.
- Split-brain after promote: fence one site, rebuild the loser from clone.
- Lag never drains before promote: fix network / increase binlog retention;
  do not promote a lagging standby for planned cutover.

Known limitations (ops view)
============================

- MySQL standby cluster uses **clone + GTID cascade** (not WAL archive /
  ``restore_command``). Prefer ``create_replica_methods: [xtrabackup, mysqldump]``.
- No ``pg_rewind`` equivalent
- Mode changes are rebuild/cutover, not hot switch
- Still under active development — validate with your workload and the
  integration suite before production
