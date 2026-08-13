.. _pause:

集群的暂停/恢复模式
===================

目标
----

在某些情况下，Patroni 需要暂时退出对集群的管理，同时仍将集群状态保留在 DCS 中。可能的使用场景包括集群上的非常规活动，例如大版本升级或损坏恢复。在这些活动期间，节点常常会因 Patroni 无法知晓的原因而被启动和停止，甚至有些节点会被暂时提升，从而违背了集群中只运行一个 primary 的假设。因此，Patroni 需要能够从正在运行的集群中"脱离"出来，实现与 Pacemaker 维护模式等效的功能。



实现
----

当 Patroni 运行在暂停（paused）模式下时，它不会改变 PostgreSQL 的状态，以下情况除外：

- 对于每个节点，DCS 中的 member key 都会以集群的当前信息进行更新。如果 member 正在运行，这会促使 Patroni 在该 member 节点上执行只读查询。

- 对于持有 leader lock 的 Postgres primary，Patroni 会更新该 lock。如果持有 leader lock 的节点不再是 primary（即被手动降级），Patroni 将释放该 lock，而不是重新将该节点提升为 primary。

- 允许手动执行计划外的 restart、手动计划外的 failover/switchover 以及 reinitialize。不允许任何计划内的操作。只有指定了要切换到的目标节点时，才允许手动 switchover。

- 如果 Patroni 检测到"并行"的 primary，它会发出警告，但不会降级未持有 leader lock 的 primary。

- 如果集群中没有 leader lock，正在运行的 primary 会获取该 lock。如果存在多个 primary 节点，那么最先获取到 lock 的 primary 获胜。如果完全没有 primary，Patroni 不会尝试提升任何 replica。这条规则有一个例外：如果 leader lock 不存在是因为旧 primary 由于手动提升而自行降级，那么只有提升请求中提到的候选节点才能获取 leader lock。当新的 leader lock 被授予时（即手动提升一个 replica 之后），Patroni 会确保此前从旧 leader 流式复制的 replica 切换到新的 leader。

- 当 Postgres 被停止时，Patroni 不会尝试启动它。当 Patroni 被停止时，它不会尝试停止其正在管理的 Postgres 实例。

- 对于不代表其他集群成员、也未列入永久 slots 配置的 replication slot，Patroni 不会尝试将其删除。

用户指南
--------

``patronictl`` 支持 :ref:`pause <patronictl_pause>` 和 :ref:`resume <patronictl_resume>` 命令。

也可以向 ``{namespace}/{cluster}/config`` key 发起携带 ``{"pause": true/false/null}`` 的 ``PATCH`` 请求。
