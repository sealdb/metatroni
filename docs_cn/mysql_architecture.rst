.. _mysql_architecture:

===========================
MySQL 架构与模型
===========================

本页介绍 MySQL 后端的结构设计：进程布局、代码模块、DCS 数据，以及它与 PostgreSQL 路径的不同之处。

设计目标
============

Patroni 是围绕 PostgreSQL 构建的。MySQL 支持通过 ``DatabaseHandler`` 抽象进行分层，因此共享的 HA 循环（``patroni.ha.Ha``）、DCS、REST API 和 ``patronictl`` 保持通用，而引擎特定的工作位于 ``patroni.mysql`` 之下。

目标：

- 复用 DCS leader 选举和 HA 控制循环
- 使用 GTID 驱动 MySQL（不进行 timeline / ``sysid`` 匹配）
- 支持三种按运维选择的模式：异步 GTID、xenon 风格的半同步、MGR
- 优先复用共享 HA 抽象；避免仅限 PostgreSQL 的路径（``pg_rewind``）。
  MySQL standby cluster 使用全量克隆 + GTID 级联，而非 WAL ``restore_command``。

集群布局
==============

每个物理（或本地）节点运行 **一个 Patroni 进程** 和 **一个 mysqld**。Patroni 负责进程生命周期、配置文件、复制拓扑和 DCS 心跳。客户端应通过代理与 MySQL 通信，该代理会检查 Patroni 的 REST API 的健康状态（参见 :ref:`mysql_ops`）。

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

复制数据路径（异步 / 半同步）
-----------------------------------------

::

    Primary mysqld  --binlog/GTID-->  Replica mysqld
         ^                                ^
         |                                |
      Patroni (lock)                 Patroni (follow)

MGR 数据路径
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

组件映射
=============

.. list-table::
   :header-rows: 1
   :widths: 12 28 60

   * -  层
     - 模块
     - 职责
   * -  ABC
     - ``patroni.db``
     - ``DatabaseHandler`` 接口 + 工厂
   * -  处理器
     - ``patroni.mysql``
     - 角色、提升/降级/跟随、MGR、半同步
   * -  配置
     - ``patroni.mysql.config``
     - ``my.cnf`` 生成 / 重载
   * -  连接
     - ``patroni.mysql.connection``
     - ``pymysql`` 连接池
   * -  引导
     - ``patroni.mysql.bootstrap``
     - ``initialize``、克隆（dump / xtrabackup）
   * -  进程
     - ``patroni.mysql.postmaster``
     - ``mysqld`` 启动/停止
   * -  初始化
     - ``patroni.mysql.initcmd``
     - ``patroni_mysql_init`` 布局生成器
   * -  版本
     - ``patroni.mysql.versioning``
     - 5.6 / 5.7 / 8.0 / 8.x / 9.x 参数矩阵
   * -  HA
     - ``patroni.ha``
     - 共享循环；MySQL 降级 / MGR / 半同步钩子
   * -  API
     - ``patroni.api``
     - ``/patroni`` 暴露 ``binlog`` 和 GTID

能力标志（与 PostgreSQL 对比）
================================

MySQL handler 会宣告引擎能力，以便 HA 循环跳过仅限 PostgreSQL 的行为：

.. list-table::
   :header-rows: 1
   :widths: 28 12 60

   * -  标志
     - MySQL
     - 效果
   * -  ``has_timelines``
     - False
     - 无 timeline 历史文件
   * -  ``needs_rewind``
     - False
     - 不需要 ``pg_rewind``；通过 GTID follow 重新加入
   * -  ``needs_crash_recovery``
     - False
     - ``mysqld`` 在启动时自行恢复
   * -  ``requires_sysid_match``
     - False
     - 每个实例都有自己的 ``server_uuid``
   * -  ``db_type``
     - ``mysql``
     - 在 HA / API 中选择 MySQL 分支

DCS 数据模型（MySQL 特定）
===============================

``/service/<scope>/`` 下的标准 Patroni 键仍然适用（``leader``、``members/<name>``、``config``、``initialize``、``failover``、``pause`` 等）。

成员载荷扩充（``enrich_dcs_data``）会添加：

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * -  字段
     - 用途
   * -  ``binlog_position``
     - xlog 位置的镜像，用于指标 / 滞后计算
   * -  ``gtid_executed``
     - 每个 HA 周期发布一次，用于 MGR 选举
   * -  ``mgr_gtid_fork``
     - 在检测到不可比较的 GTID 时出现
   * -  ``role``
     - ``primary``/ ``replica``/ ``mgr_primary``/ ……

REST 的 ``GET /patroni`` 包含一个 ``binlog`` 对象（文件、位置，以及可用时的 ``gtid_set``），而不是 PostgreSQL 的 ``xlog``。

角色
=====

异步 / 半同步
-----------------

- **primary**—— 持有 DCS 锁，可写（除非半同步 quorum 强制为只读）
- **replica**—— 使用 ``MASTER_AUTO_POSITION=1`` 跟随 primary

MGR
---

- **mgr_primary**—— Group Replication PRIMARY，通常持有 DCS 锁
- **mgr_secondary**—— GR SECONDARY，``super_read_only``
- 在失去多数派时，DCS 中的角色可能会短暂地表现为异步 ``primary``；在决定是否
  bootstrap 新组时，选举逻辑 **只信任** 活跃的 ``mgr_primary`` 宣告

模式选择（配置方式，而非运行时 API）
===============================================

.. list-table::
   :header-rows: 1
   :widths: 14 50 36

   * -  模式
     - 检测
     - 初始化标志
   * -  async
     - 无 GR UUID；半同步关闭或不存在
     - ``--mode async``
   * -  semi-sync
     - 存在 ``rpl_semi_sync_*``
     - ``--mode semi-sync``
   * -  MGR
     - 已设置 ``group_replication_group_name``
     - ``--mode mgr``

不存在热「切换模式」API。请将模式切换视为重建；参见 :ref:`mysql_ops`。

信任边界
================

- **DCS** 是 *谁可以成为 Patroni leader* 的权威来源
- **MySQL 复制 / MGR** 是 *数据时效性* 的权威来源
- 对于 MGR 失去多数派的情况，Patroni 会将两者结合：GTID 比较决定谁可以 bootstrap，但 bootstrap 只有在持有 DCS 锁（或重新加入已宣告的活跃 ``mgr_primary``）时才会继续
