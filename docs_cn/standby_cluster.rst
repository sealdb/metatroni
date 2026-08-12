.. _standby_cluster:

Standby cluster
---------------

Patroni 还支持使用一种称为"standby cluster"的特性，向远程数据中心（区域）运行级联复制（cascading replication）。此类集群具有：

* "standby leader"，它的行为与常规集群的 leader 非常相似，区别在于它从远程节点复制数据。

* cascade replicas，它们从 standby leader 复制数据。

Standby leader 持有并更新 DCS 中的 leader lock。如果 leader lock 过期，cascade replicas 将进行选举，从 standbys 中选出另一个 leader。

standby cluster 与其复制的 primary cluster 之间没有其他关系，特别是，如果它们使用同一个 DCS，则不能共享相同的 DCS scope。除了复制信息之外，它们彼此互不了解。此外，standby cluster 不会显示在 primary cluster 上的 :ref:`patronictl_list` 或 :ref:`patronictl_topology` 输出中。

为了灵活性，你可以通过在 `standby_cluster` 部分提供 :ref:`create_replica_methods <custom_replica_creation>` key，来指定集群处于"standby 模式"时创建 replica 和恢复 WAL 记录的方法。这与集群脱离 standby 模式并作为普通集群运行时创建 replica 的方式不同，后者由 `postgresql` 部分中的 `create_replica_methods` 控制。"standby" 和 "normal" 两种 `create_replica_methods` 都引用 `postgresql` 部分中的 key。

要配置此类集群，你需要在 patroni 配置中指定 ``standby_cluster`` 部分：

.. code:: YAML

    bootstrap:
        dcs:
            standby_cluster:
                host: 1.2.3.4
                port: 5432
                primary_slot_name: patroni
                create_replica_methods:
                - basebackup

**MySQL** 使用相同的 DCS ``standby_cluster`` 键（``host``、``port``、可选
``create_replica_methods``），但 bootstrap 是对远程主的 **全量克隆**（默认
``xtrabackup`` 再 ``mysqldump``），随后通过 GTID 流式复制
（``MASTER_AUTO_POSITION=1``）。MySQL 不要设置 PostgreSQL 专用的
``restore_command`` / ``primary_slot_name``。示例：

.. code:: YAML

    bootstrap:
        dcs:
            standby_cluster:
                host: primary-site.example
                port: 3306
                create_replica_methods:
                - xtrabackup
                - mysqldump

请注意，这些选项只在集群 bootstrap 期间应用一次，之后唯一的修改方式是通过 DCS。

Patroni 期望在远程 primary 的 PGDATA 中找到 `postgresql.conf` 或 `postgresql.conf.backup`，如果在 basebackup 之后找不到，将无法启动。如果远程 primary 将 `postgresql.conf` 保存在其他位置，则需要你自行将其复制到 PGDATA。

如果你在 standby cluster 上使用 replication slots，还必须在其对应的 primary cluster 上创建相应的 replication slot。standby cluster 的实现不会自动完成这一操作。你可以使用 Patroni 在 primary cluster 上的永久 replication slots 功能，来维护一个与 ``primary_slot_name`` 同名（如果未提供 ``primary_slot_name``，则使用其默认值）的 replication slot。

如果远程站点没有提供连接到 primary 的单一端点，你可以在 ``standby_cluster.host`` 部分列出源集群的所有主机。当 ``standby_cluster.host`` 包含多个以逗号分隔的主机时，Patroni 将：

* 在 standby leader 节点的 ``primary_conninfo`` 中添加 ``target_session_attrs=read-write``。
* 在尝试判断是否需要运行 ``pg_rewind``，或在 standby cluster 的所有节点上执行 ``pg_rewind`` 时，使用 ``target_session_attrs=read-write``。
* 需要特别注意的是，要让 ``pg_rewind`` 成功运行，集群必须使用 ``data page checksums``（``initdb`` 的 ``--data-checksums`` 选项）初始化，并且/或者 ``wal_log_hints`` 必须设置为 ``on``。否则，``pg_rewind`` 将无法正常工作。

还有一种可能，即从另一个 standby cluster 或 primary cluster 的 standby 成员复制 standby cluster 数据：为此，你需要在 ``standby_cluster.host`` 部分中定义一个单一主机。但你需要小心，在这种情况下 ``pg_rewind`` 将无法在 standby cluster 上执行。



.. warning::
      成员名称（每个节点 Patroni 配置中的 ``name`` 字段）在 primary cluster 及其连接的所有 standby clusters 之间必须唯一。

   Patroni 使用成员名称在 primary 上设置 ``synchronous_standby_names``，这些名称同时也成为 ``pg_stat_replication`` 中每个复制连接的 ``application_name``。如果 standby cluster 的节点与 primary cluster 的成员同名，PostgreSQL 将看到两个 ``application_name`` 值相同的连接。这种歧义可能导致 PostgreSQL 使用 standby cluster 的连接而不是预期的 primary cluster 成员来满足同步复制要求，从而使 PostgreSQL 过早地将事务确认为已同步提交，而实际上这些事务并未在正确的 standby 上持久化。

   这是一种静默故障——复制仍在继续，也不会记录任何错误，但集群实际上是在没有有效同步 standby 的情况下运行，如果 primary 发生故障，就存在数据丢失的潜在风险。
