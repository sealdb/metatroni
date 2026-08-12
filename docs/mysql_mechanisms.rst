.. _mysql_mechanisms:

=================================
MySQL HA mechanisms and sequences
=================================

This page explains **how** the MySQL backend behaves inside Patroni’s HA loop:
failover, demote/rejoin, semi-sync quorum, MGR majority-loss election, clone,
and GTID-fork pause.

HA control loop (shared + MySQL hooks)
=====================================

Every ``loop_wait`` seconds, each Patroni runs roughly:

.. code-block:: text

                    ┌─────────────────────┐
                    │  load cluster (DCS) │
                    └─────────┬───────────┘
                              │
                    ┌─────────▼───────────┐
                    │  touch_member()     │  (+ enrich gtid_executed)
                    └─────────┬───────────┘
                              │
              ┌───────────────▼────────────────┐
              │  hold DCS leader lock?         │
              └───────┬────────────────┬───────┘
                   yes│                │no
          ┌───────────▼──────┐   ┌─────▼──────────────────────────┐
          │ update_lock()    │   │ MySQL: run_mgr_cycle(False)    │
          │ MySQL:           │   │   MGR follow / elect / rejoin  │
          │  run_mgr_cycle   │   │ if MGR configured: STOP here   │
          │  (True)          │   │ else: follow(leader)           │
          │  semi_sync_check │   └────────────────────────────────┘
          │ enforce primary  │
          └──────────────────┘

Important MySQL-specific rules encoded in ``ha.py``:

- While holding the lock, still run **MGR** and **semi-sync** maintenance
  (previously these only ran on the non-lock path).
- If MGR is configured, **never** fall through to async ``follow()`` (avoids dual
  channels and PostgreSQL rewind helpers).
- ``mgr_yield_lock`` → ``release_leader_key_voluntarily()``
- ``mgr_gtid_fork`` → pause + read-only (see below)

Async / semi-sync: failover sequence
====================================

Happy-path automatic failover when the primary’s lease expires:

.. code-block:: text

    Primary A          DCS              Replica B           Replica C
        │               │                   │                   │
        │ X crash       │                   │                   │
        │               │  lease expires    │                   │
        │               │◄──────────────────┼───────────────────┤
        │               │   race for lock   │                   │
        │               │◄──── acquire ─────┤                   │
        │               │                   │ promote():        │
        │               │                   │  STOP/RESET SLAVE │
        │               │                   │  read_write       │
        │               │  leader=B         │                   │
        │               │                   │                   │
        │               │                   │◄── follow(B) ─────┤
        │               │                   │   CHANGE MASTER   │
        │               │                   │   AUTO_POSITION=1 │

``promote`` / ``follow`` (async GTID)
------------------------------------

.. code-block:: text

    promote (new primary)
      │
      ├─ STOP SLAVE / STOP REPLICA
      ├─ RESET SLAVE ALL / RESET REPLICA ALL
      ├─ set_read_write()
      ├─ ensure_replication_user()   (sql_log_bin=0)
      └─ role = primary

    follow (replica → primary P)
      │
      ├─ STOP SLAVE
      ├─ CHANGE MASTER TO
      │     MASTER_HOST/PORT/USER/PASSWORD
      │     MASTER_AUTO_POSITION=1
      │     [GET_MASTER_PUBLIC_KEY=1 on MySQL 8 async]
      ├─ START SLAVE
      └─ role = replica

Demote + rejoin (old primary returns)
=====================================

There is **no** ``pg_rewind``. ``Ha._demote_mysql`` keeps ``mysqld`` running:

.. code-block:: text

    Old primary A (lost lock / switchover)
      │
      ├─ set_read_only()
      ├─ MySQL.demote()          # disable semi-sync source, etc.
      ├─ set_is_leader(False)
      ├─ [graceful|immediate] release_leader_key_voluntarily()
      ├─ sleep(~2s)             # peer can take lock
      ├─ refresh cluster from DCS
      ├─ follow(new_leader)
      └─ touch_member()

Sequence (graceful switchover):

.. code-block:: text

    A (primary)          DCS              B (replica)
        │                 │                   │
        │ switchover req  │                   │
        │─ demote ───────►│ release lock      │
        │  read_only      │                   │
        │                 │◄──── acquire ─────┤
        │                 │                   │ promote
        │                 │  leader=B         │
        │◄─ follow(B) ────┤                   │
        │  CHANGE MASTER  │                   │
        │  streaming      │                   │

Semi-sync quorum safety
=======================

Aligned with xenon strong consistency:

- ``wait_point = AFTER_SYNC``
- ``wait_no_slave = ON``
- 3+ nodes: wait timeout ``10**18`` ms (effectively no async degrade)
- Wait count ``(N-1)//2``
- Boot: source plugin **OFF** until Patroni enables it on primary

Every HA cycle on the lock holder:

.. code-block:: text

    run_semi_sync_safety_check(cluster_nodes)
      │
      ├─ count connected semi-sync replicas
      ├─ quorum = (N-1)//2
      │
      ├─ if replicas < quorum:
      │     set super_read_only / read_only
      │     (refuse durable writes without ACK quorum)
      │
      └─ if replicas >= quorum and was RO for this reason:
            restore read_write

Flow:

.. code-block:: text

         ┌──────────────────────┐
         │ Hold lock + primary  │
         └──────────┬───────────┘
                    │
         ┌──────────▼───────────┐
         │ semi-sync clients    │
         │   >= quorum ?        │
         └─────┬──────────┬─────┘
            yes│          │no
       ┌───────▼────┐  ┌──▼──────────────┐
       │ read_write │  │ super_read_only │
       └────────────┘  └─────────────────┘

MGR: steady state
=================

When ``group_replication_group_name`` is set and the local member is ONLINE:

.. code-block:: text

    get_mgr_status()  # performance_schema.replication_group_members
      │
      ├─ role PRIMARY  → role=mgr_primary, set_read_write
      └─ role SECONDARY → role=mgr_secondary, set_read_only

Patroni does **not** drive async ``CHANGE MASTER`` while MGR is configured.

MGR: majority-loss GTID election
================================

When local MGR status is empty (group down / majority lost):

Flowchart
---------

.. code-block:: text

    ┌─────────────────────────────────────┐
    │ MGR configured but status empty     │
    └──────────────────┬──────────────────┘
                       │
    ┌──────────────────▼──────────────────┐
    │ Collect gtid_executed (self+DCS)    │
    │ Drop strict GTID subsets            │
    │ Maximal set size >=2 & incomparable?│
    └──────┬───────────────────┬──────────┘
        fork│               ok │
    ┌──────▼────────┐   ┌──────▼────────────────────┐
    │ mgr_gtid_fork │   │ winner = max GTID;        │
    │ RO + pause    │   │ tie → lexicographically   │
    │ no bootstrap  │   │ smallest name             │
    └───────────────┘   └──────┬────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │ Am I the winner?    │
                    └────┬───────────┬────┘
                      no │           │ yes
              ┌──────────▼───┐  ┌────▼─────────────────────────┐
              │ wait / rejoin│  │ has_lock?                    │
              │ if mgr_primary│  └────┬──────────────────┬─────┘
              │ advertised   │    no │                  │ yes
              └──────────────┘  ┌────▼──────────┐  ┌────▼──────────────────┐
                                │ try rejoin    │  │ try rejoin live       │
                                │ live primary  │  │ mgr_primary           │
                                │ else wait lock│  │ success → yield lock  │
                                └───────────────┘  │ fail → bootstrap_mgr  │
                                                   │ (ignore stale primary)│
                                                   └───────────────────────┘

Sequence (winner alone bootstraps, peers rejoin)
------------------------------------------------

.. code-block:: text

    n0,n1,n2 (all STOP GR)     DCS
        │                       │
        │ publish gtid_executed │
        │ (n2 ahead)            │
        │                       │
        │ n0 has lock, behind → yield / wait
        │ n2 winner, takes lock │
        │                       │
        │ n2 bootstrap_mgr_group│
        │ role=mgr_primary ────►│
        │                       │
        │ n0/n1 rejoin_mgr_group│
        │  STOP/RESET SLAVE     │
        │  recovery channel     │
        │  START GROUP_REPLICATION
        │  wait ONLINE|RECOVERING
        │                       │
        │ group size = 3 ONLINE │

Rejoin correctness
------------------

``rejoin_mgr_group`` returns success only after local state is ``ONLINE`` or
``RECOVERING``. A bare ``START GROUP_REPLICATION`` against a **stale/dead**
``mgr_primary`` in DCS must fail so the GTID winner can still bootstrap.

Stale DCS ``role=primary`` (async leftover after majority loss) is **ignored**
by ``_find_mgr_primary_member``; only ``mgr_primary`` counts.

GTID fork (incomparable sets)
=============================

When two maximal GTID sets each contain transactions the other lacks:

.. code-block:: text

    describe_mgr_gtid_fork() → non-empty
      │
      ├─ CRITICAL log with each maximal member’s gtid_executed
      ├─ force super_read_only
      ├─ return mgr_gtid_fork (no bootstrap)
      ├─ default: DCS pause=true + mgr_gtid_fork breadcrumb
      │     (mysql.parameters.mgr_pause_on_gtid_fork, default true)
      └─ publish fork on member key / REST until group healthy

Operator recovery: repair or rebuild divergent members, then
``patronictl resume``.

Clone / bootstrap
=================

Empty data directory path:

.. code-block:: text

    data_directory_empty?
      │
      ├─ no leader yet → bootstrap():
      │     mysqld --initialize-insecure
      │     start → post_bootstrap (users/grants)
      │
      └─ leader exists → create_replica(leader):
            for method in create_replica_methods:
              mysqldump | xtrabackup
            on failure: clean partial datadir
            start → follow / join MGR

xtrabackup notes:

- Major.minor must match the donor
- After restore, donor ``auto.cnf`` is removed so a new ``server_uuid`` is created

Pause interaction
=================

``patronictl pause`` (or automatic pause on GTID fork) stops autofailover while
keeping MySQL running. Use during mode cutovers, risky maintenance, and after
fork remediation.
