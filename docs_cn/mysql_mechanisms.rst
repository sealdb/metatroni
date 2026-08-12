.. _mysql_mechanisms:

=================================
MySQL HA 机制与流程
=================================

本页说明 MySQL 后端在 Patroni 的 HA 循环中的 **行为机制**：failover、demote/rejoin、
半同步 quorum、MGR 多数派丢失选举、克隆（clone）以及 GTID 分叉暂停。

HA 控制循环（共享 + MySQL 钩子）
=====================================

每隔 ``loop_wait`` 秒，每个 Patroni 大约执行以下操作：

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

``ha.py`` 中实现的重要 MySQL 专属规则：

- 持有锁期间，仍会运行 **MGR** 和 **semi-sync** 的维护逻辑
  （此前这些逻辑只会在非锁路径上运行）。
- 如果配置了 MGR，**绝不会** 回退到异步 ``follow()`` （可避免双通道以及
  PostgreSQL rewind 辅助逻辑）。
- ``mgr_yield_lock`` → ``release_leader_key_voluntarily()``
- ``mgr_gtid_fork`` → pause + read-only（详见下文）

异步 / 半同步：failover 流程
====================================

正常路径下，当 primary 的 lease 过期时自动 failover：

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

``promote`` / ``follow`` （异步 GTID）
---------------------------------------

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

降级并重新加入（旧 primary 回归）
=====================================

**不存在** ``pg_rewind``。``Ha._demote_mysql`` 会让 ``mysqld`` 保持运行：

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

流程（优雅 switchover）：

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

半同步 quorum 安全机制
=======================

与 xenon 强一致性对齐：

- ``wait_point = AFTER_SYNC``
- ``wait_no_slave = ON``
- 3 个及以上节点：等待超时 ``10**18`` 毫秒（实际上不会降级为异步）
- 等待计数 ``(N-1)//2``
- 启动时：source 插件保持 **OFF**，直到 Patroni 在 primary 上启用它

锁持有者在每个 HA 周期中：

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

流程：

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

MGR：稳态
=================

当设置了 ``group_replication_group_name`` 且本地成员处于 ONLINE 状态时：

.. code-block:: text

    get_mgr_status()  # performance_schema.replication_group_members
      │
      ├─ role PRIMARY  → role=mgr_primary, set_read_write
      └─ role SECONDARY → role=mgr_secondary, set_read_only

配置了 MGR 时，Patroni **不会** 驱动异步 ``CHANGE MASTER``。

MGR：多数派丢失时的 GTID 选举
================================

当本地 MGR 状态为空（group 宕机 / 多数派丢失）时：

流程图
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

流程（赢家单独 bootstrap，其余节点重新加入）
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

重新加入的正确性
------------------

``rejoin_mgr_group`` 仅在本地状态变为 ``ONLINE`` 或
``RECOVERING`` 后才返回成功。针对 DCS 中 **过期/失效** 的
``mgr_primary`` 直接执行 ``START GROUP_REPLICATION`` 必须失败，这样 GTID 赢家仍能 bootstrap。

DCS 中过期的 ``role=primary`` （多数派丢失后遗留的异步角色）会被
``_find_mgr_primary_member`` **忽略**；只有 ``mgr_primary`` 才算数。

GTID 分叉（不可比较的集合）
=============================

当两个最大的 GTID 集合各自包含对方所没有的事务时：

.. code-block:: text

    describe_mgr_gtid_fork() → non-empty
      │
      ├─ CRITICAL log with each maximal member’s gtid_executed
      ├─ force super_read_only
      ├─ return mgr_gtid_fork (no bootstrap)
      ├─ default: DCS pause=true + mgr_gtid_fork breadcrumb
      │     (mysql.parameters.mgr_pause_on_gtid_fork, default true)
      └─ publish fork on member key / REST until group healthy

运维恢复：修复或重建分歧成员，然后执行
``patronictl resume``。

克隆 / bootstrap
=================

数据目录为空时：

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

xtrabackup 说明：

- Major.minor 必须与 donor 一致
- 恢复完成后，会移除 donor 的 ``auto.cnf``，从而生成新的 ``server_uuid``

Pause 交互
=================

``patronictl pause`` （或在 GTID 分叉时自动 pause）会在保持 MySQL 运行的同时停止自动 failover。可在模式切换、高风险维护以及分叉修复后使用。
