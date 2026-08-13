.. _mysql_architecture:

============================
MySQL architecture and model
============================

This page describes the structural design of the MySQL backend: process layout,
code modules, DCS data, and how it differs from the PostgreSQL path.

Design goals
============

Patroni was built around PostgreSQL. MySQL support is layered through a
``DatabaseHandler`` abstraction so the shared HA loop (``patroni.ha.Ha``), DCS,
REST API, and ``patronictl`` stay common, while engine-specific work lives under
``patroni.mysql``.

Goals:

- Reuse DCS leader election and the HA control loop
- Drive MySQL with GTID (no timeline / ``sysid`` matching)
- Support three ops-selected modes: async GTID, xenon-style semi-sync, MGR
- Prefer shared HA loop abstractions; avoid PostgreSQL-only paths
  (``pg_rewind``). MySQL standby clusters use clone + GTID cascade instead of
  WAL ``restore_command``.

Cluster layout
==============

Each physical (or local) node runs **one Patroni process** and **one mysqld**.
Patroni owns process lifecycle, config files, replication topology, and the
DCS heartbeat. Clients should talk to MySQL through a proxy that health-checks
Patroni’s REST API (see :ref:`mysql_ops`).

::

    +---------------------------------------------------------------+
    |                         Cluster scope                         |
    |                                                               |
    |   +-------------------+         +-------------------+         |
    |   | Node A            |         | Node B            |         |
    |   |  Patroni  --------+----+----+--------  Patroni  |         |
    |   |  REST :8008       |    |    |        REST :8009 |         |
    |   |  mysqld :3306     |    |    |        mysqld :3307         |
    |   +-------------------+    |    +-------------------+         |
    |                            |                                  |
    |                    +-------v--------+                         |
    |                    | DCS (etcd3/…)  |                         |
    |                    | /service/<scope>/                        |
    |                    |  leader, members,                        |
    |                    |  config, pause, …                        |
    |                    +----------------+                         |
    +---------------------------------------------------------------+

    Optional: HAProxy / ProxySQL
      :5000  -> HEAD /primary  -> writable mysqld
      :5001  -> HEAD /replica  -> read replicas

Replication data path (async / semi-sync)
-----------------------------------------

::

    Primary mysqld  --binlog/GTID-->  Replica mysqld
         ^                                ^
         |                                |
      Patroni (lock)                 Patroni (follow)

MGR data path
-------------

::

    +---- Group Replication (Paxos-like certification) ----+
    |  member0 (PRIMARY)  <->  member1  <->  member2       |
    +------------------------------------------------------+
              ^                         ^
              |                         |
         Patroni follows            Patroni follows
         GR role / state            GR role / state
         (+ DCS lock for            (+ GTID election on
          bootstrap / ops)           majority loss)

Component map
=============

.. list-table::
   :header-rows: 1
   :widths: 12 28 60

   * - Layer
     - Module
     - Responsibility
   * - ABC
     - ``patroni.db``
     - ``DatabaseHandler`` interface + factory
   * - Handler
     - ``patroni.mysql``
     - Role, promote/demote/follow, MGR, semi-sync
   * - Config
     - ``patroni.mysql.config``
     - ``my.cnf`` generation / reload
   * - Conn
     - ``patroni.mysql.connection``
     - ``pymysql`` pool
   * - Boot
     - ``patroni.mysql.bootstrap``
     - ``initialize``, clone (dump / xtrabackup)
   * - Proc
     - ``patroni.mysql.postmaster``
     - ``mysqld`` start/stop
   * - Init
     - ``patroni.mysql.initcmd``
     - ``patroni_mysql_init`` layout generator
   * - Vers
     - ``patroni.mysql.versioning``
     - 5.6 / 5.7 / 8.0 / 8.x / 9.x parameter matrix
   * - HA
     - ``patroni.ha``
     - Shared loop; MySQL demote / MGR / semi-sync hooks
   * - API
     - ``patroni.api``
     - ``/patroni`` exposes ``binlog`` + GTID

Capability flags (vs PostgreSQL)
================================

The MySQL handler advertises engine capabilities so the HA loop skips
PostgreSQL-only behavior:

.. list-table::
   :header-rows: 1
   :widths: 28 12 60

   * - Flag
     - MySQL
     - Effect
   * - ``has_timelines``
     - False
     - No timeline history files
   * - ``needs_rewind``
     - False
     - No ``pg_rewind``; rejoin via GTID follow
   * - ``needs_crash_recovery``
     - False
     - ``mysqld`` recovers itself on start
   * - ``requires_sysid_match``
     - False
     - Each instance has its own ``server_uuid``
   * - ``db_type``
     - ``mysql``
     - Selects MySQL branches in HA / API

DCS data model (MySQL-specific)
===============================

Standard Patroni keys under ``/service/<scope>/`` still apply (``leader``,
``members/<name>``, ``config``, ``initialize``, ``failover``, ``pause``, …).

Member payload enrichment (``enrich_dcs_data``) adds:

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Field
     - Purpose
   * - ``binlog_position``
     - Mirror of xlog location for metrics / lag
   * - ``gtid_executed``
     - Published every HA cycle for MGR election
   * - ``mgr_gtid_fork``
     - Present while incomparable GTIDs are detected
   * - ``role``
     - ``primary`` / ``replica`` / ``mgr_primary`` / …

REST ``GET /patroni`` includes a ``binlog`` object (file, position, and
``gtid_set`` when available) instead of PostgreSQL’s ``xlog``.

Roles
=====

Async / semi-sync
-----------------

- **primary** — holds DCS lock, writable (unless semi-sync quorum forces RO)
- **replica** — follows primary with ``MASTER_AUTO_POSITION=1``

MGR
---

- **mgr_primary** — Group Replication PRIMARY + typically holds DCS lock
- **mgr_secondary** — GR SECONDARY, ``super_read_only``
- On majority loss, roles may briefly look like async ``primary`` in DCS; election
  logic **only trusts** a live ``mgr_primary`` advertisement when deciding whether
  to bootstrap a new group

Mode selection (configuration, not runtime API)
===============================================

.. list-table::
   :header-rows: 1
   :widths: 14 50 36

   * - Mode
     - Detection
     - Init flag
   * - async
     - No GR UUID; semi-sync off / absent
     - ``--mode async``
   * - semi-sync
     - ``rpl_semi_sync_*`` present
     - ``--mode semi-sync``
   * - MGR
     - ``group_replication_group_name`` set
     - ``--mode mgr``

There is no hot “switch mode” API. Treat cutovers as rebuilds; see
:ref:`mysql_ops`.

Trust boundaries
================

- **DCS** is the source of truth for *who may be Patroni leader*
- **MySQL replication / MGR** is the source of truth for *data currency*
- For MGR majority loss, Patroni combines both: GTID comparison elects who may
  bootstrap, but bootstrap only proceeds with the DCS lock (or rejoin to an
  already advertised live ``mgr_primary``)
