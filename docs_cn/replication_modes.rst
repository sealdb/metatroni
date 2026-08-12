.. _replication_modes:

=================
复制模式
=================

Patroni 使用 PostgreSQL 流式复制。有关流式复制的更多信息，请参阅 `Postgres 文档 <http://www.postgresql.org/docs/current/static/warm-standby.html#STREAMING-REPLICATION>`__。默认情况下，Patroni 将 PostgreSQL 配置为异步复制。选择哪种复制模式取决于您的业务考量。请同时研究异步复制和同步复制，以及其他 HA 解决方案，以确定最适合您的方案。


异步模式的数据持久性
============================

在异步模式下，集群允许丢失一些已提交事务以保证可用性。当 primary 服务器发生故障或因任何其他原因不可用时，Patroni 会自动将一个足够健康的 standby 提升为 primary。任何尚未复制到该 standby 的事务仍保留在 primary 的「分叉时间线」中，实际上无法恢复 [1]_。

可丢失的事务量由 ``maximum_lag_on_failover`` 参数控制。由于 primary 的事务日志位置并非实时采样，因此实际上 failover 时丢失的数据量最坏情况下受限于 ``maximum_lag_on_failover`` 字节的事务日志加上最近 ``ttl`` 秒内写入的量（平均情况下为 ``loop_wait``/2 秒）。不过，典型稳态下的复制延迟远低于一秒。

默认情况下，进行 leader 选举时，Patroni 不会考虑 replica 的当前时间线，这在某些情况下可能是不可取的行为。您可以通过将 ``check_timeline`` 参数的值改为 ``true``，来防止时间线与前一个 primary 不同的节点成为新的 leader。


PostgreSQL 同步复制
==================================

您可以配合 Patroni 使用 Postgres 的 `同步复制 <http://www.postgresql.org/docs/current/static/warm-standby.html#SYNCHRONOUS-REPLICATION>`__。同步复制通过在向连接的客户端返回成功之前确认写入已写入 secondary，来确保集群内的一致性。同步复制的代价是：写入延迟增加、吞吐量降低。吞吐量将完全取决于网络性能。

在托管的数据中心环境中（如 AWS、Rackspace，或任何您无法控制的网络），同步复制会显著增加写入性能的波动性。如果 follower 无法从 leader 访问，leader 实际上将变为只读。

要启用一个简单的同步复制测试，请在 YAML 配置文件的 ``parameters`` 部分添加以下几行：

.. code:: YAML

        synchronous_commit: "on"
        synchronous_standby_names: "*"

使用 PostgreSQL 同步复制时，请至少使用三个 Postgres 数据节点，以确保在某台主机发生故障时写入仍然可用。

使用 PostgreSQL 同步复制并不能在所有情况下保证零事务丢失。当 primary 和当前充当同步 replica 的 secondary 同时发生故障时，可能会提升一个并未包含全部事务的第三节点。


.. _synchronous_mode:

同步模式
================

对于不允许丢失已提交事务的使用场景，您可以开启 Patroni 的 ``synchronous_mode``。当 ``synchronous_mode`` 开启时，除非 Patroni 确定 standby 包含所有可能已向客户端返回成功提交状态的事务 [2]_，否则不会提升 standby。这意味着即使某些服务器可用，系统也可能无法接受写入。系统管理员仍然可以使用手动 failover 命令来提升 standby，即使这会导致事务丢失。

开启 ``synchronous_mode`` 并不能在所有情况下保证提交的多节点持久性。当没有合适的 standby 可用时，primary 服务器仍会接受写入，但不保证这些写入会被复制。在此模式下，当 primary 发生故障时不会有 standby 被提升。当原先作为 primary 的主机恢复时，它会自动被提升，除非系统管理员执行了手动 failover。这种行为使同步模式可用于 2 节点集群。

当 ``synchronous_mode`` 开启且某个 standby 崩溃时，提交将被阻塞，直到 Patroni 的下一次迭代运行并将 primary 切换到独立模式（写入的最坏情况延迟为 ``ttl`` 秒，平均情况为 ``loop_wait``/2 秒）。手动关闭或重启 standby 不会导致提交服务中断。standby 会在 PostgreSQL 关闭启动前通知 primary 将其从同步 standby 职责中释放。

当必须绝对保证每次写入都持久地存储在至少两个节点上时，请在 ``synchronous_mode`` 之外再启用 ``synchronous_mode_strict``。该参数防止 Patroni 在没有同步 standby 候选可用时关闭 primary 上的同步复制。其缺点是，primary 将无法接受写入（除非 Postgres 事务显式关闭 ``synchronous_commit``），所有客户端写请求都会被阻塞，直到至少一个同步 replica 启动。

您可以通过将 ``nosync`` 标签设置为 true 来确保 standby 永远不会成为同步 standby。建议为那些位于慢速网络连接之后、成为同步 standby 会导致性能下降的 standby 设置此标签。将 ``nostream`` 标签设置为 true 也会产生同样的效果。

同步模式可以通过 ``patronictl edit-config`` 命令或 Patroni REST 接口开启和关闭。有关说明，请参见 :ref:`dynamic configuration <dynamic_configuration>`。

注意：由于 PostgreSQL 中同步复制的实现方式，即使使用 ``synchronous_mode_strict`` 仍有可能丢失事务。如果 PostgreSQL 后端在等待复制确认时被取消（由于客户端超时导致的数据包取消或后端故障），事务更改会对其他后端可见。此类更改尚未被复制，在 standby 提升的情况下可能会丢失。


同步复制因子
==============================

``synchronous_node_count`` 参数由 Patroni 用于管理同步 standby 数据库的数量。默认值为 ``1``。当 ``synchronous_mode`` 设置为 ``off`` 时，它不起作用。启用后，Patroni 根据 ``synchronous_node_count`` 参数管理精确数量的同步 standby 数据库，并在成员加入和离开时调整 DCS 中的状态以及 PostgreSQL 中的 ``synchronous_standby_names``。如果该参数设置的值高于合格节点的数量，Patroni 会自动将其降低。


同步节点的最大滞后
===============================

默认情况下，即使有其他节点领先，Patroni 也会坚持选择那些根据 ``pg_stat_replication`` 视图声明为 ``synchronous`` 的节点。这样做是为了尽量减少 ``synchronous_standby_names`` 的变更次数。要改变这一行为，可以使用 ``maximum_lag_on_syncnode`` 参数。它控制 replica 仍被视为「synchronous」所允许的最大滞后量。

如果有多个 standby，Patroni 使用最大的 replica LSN，否则使用 leader 当前的 WAL LSN。默认值为 ``-1``，当该值设置为 ``0`` 或更小时，Patroni 不会采取行动来替换不健康的同步 standby。请将该值设置得足够高，以免 Patroni 在高事务量期间频繁替换同步 standby。


同步模式的实现
===============================

在同步模式下，Patroni 在 DCS（``/sync`` 键）中维护同步状态，其中包含最新的 primary 和当前的同步 standby 数据库。该状态通过严格的顺序约束进行更新，以确保以下不变式成立：

- 只要节点能够接受写事务，它就必须被标记为最新的 leader。Patroni 崩溃或 PostgreSQL 未能关闭可能导致此不变式被违反。

- 只要节点被发布为 DCS 中 ``/sync`` 键里的同步 standby，它就必须在 PostgreSQL 中被设置为同步 standby。

- 不是 leader 或当前同步 standby 的节点不允许自动提升自己。

Patroni 只会根据 ``synchronous_node_count`` 参数将一个或多个同步 standby 节点分配给 ``synchronous_standby_names``。

在每次 HA 循环迭代中，Patroni 都会重新评估同步 standby 节点的选择。如果当前的同步 standby 节点列表已连接且未请求移除其同步状态，则继续选中它们。否则，将选择可用于同步且复制进度最靠前的集群成员。

示例：
---------

DCS 中的 ``/config`` 键
^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: YAML

    synchronous_mode: on
    synchronous_node_count: 2
    ...

DCS 中的 ``/sync`` 键
^^^^^^^^^^^^^^^^^^^^^

.. code-block:: JSON

    {
        "leader": "node0",
        "sync_standby": "node1,node2"
    }

postgresql.conf
^^^^^^^^^^^^^^^

.. code-block:: INI

    synchronous_standby_names = 'FIRST 2 (node1,node2)'


在上述示例中，只有节点 ``node1`` 和 ``node2`` 被认为是同步的，并且如果 primary（``node0``）发生故障，允许自动提升。


.. _quorum_mode:

Quorum 提交模式
==================

从 PostgreSQL v10 开始，Patroni 支持基于 quorum 的同步复制。

在此模式下，Patroni 在 DCS 中维护同步状态，其中包含最新已知的 primary、quorum 所需的节点数量，以及当前有资格对 quorum 投票的节点。在稳定状态下，对 quorum 投票的节点是 leader 和所有同步 standby。该状态通过严格的顺序约束（涉及节点提升和 ``synchronous_standby_names``）进行更新，以确保在任意时刻，任何能够达成 quorum 的投票者子集都至少包含一个拥有最新成功提交的节点。

在每次 HA 循环迭代中，Patroni 都会根据节点可用性和请求的集群配置重新评估同步 standby 的选择和 quorum。在高于 9.6 的 PostgreSQL 版本中，一旦所有合格节点的复制追上 leader，它们就会被添加为同步 standby。

Quorum 提交有助于降低最坏情况下的延迟，即使在正常操作期间也是如此，因为复制到某个 standby 的较高延迟可以由其他 standby 来弥补。

可以通过使用 ``patronictl edit-config`` 命令或 Patroni REST 接口将 ``synchronous_mode`` 设置为 ``quorum`` 来启用基于 quorum 的同步模式。有关说明，请参见 :ref:`dynamic configuration <dynamic_configuration>`。

其他参数，如 ``synchronous_node_count``、``maximum_lag_on_syncnode`` 和 ``synchronous_mode_strict``，其工作方式与 ``synchronous_mode=on`` 时相同。

示例：
---------

DCS 中的 ``/config`` 键
^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: YAML

    synchronous_mode: quorum
    synchronous_node_count: 2
    ...

DCS 中的 ``/sync`` 键
^^^^^^^^^^^^^^^^^^^^^

.. code-block:: JSON

    {
        "leader": "node0",
        "sync_standby": "node1,node2,node3",
        "quorum": 1
    }

postgresql.conf
^^^^^^^^^^^^^^^

.. code-block:: INI

    synchronous_standby_names = 'ANY 2 (node1,node2,node3)'


如果 primary（``node0``）发生故障，在上述示例中，``node1``、``node2``、``node3`` 中的两个将收到最新事务，但我们不知道是哪两个。要判断节点 ``node1`` 是否收到了最新事务，我们需要将其 LSN 与 ``node2`` 和 ``node3`` 中 **至少** 一个节点（``/sync`` 键中的 ``quorum=1``）的 LSN 进行比较。如果 ``node1`` 不落后于其中至少一个节点，那么我们可以保证提升 ``node1`` 不会造成用户可见的数据丢失。


.. [1] 数据仍然存在，但恢复它需要数据恢复专家进行手动恢复。当允许 Patroni 使用 ``use_pg_rewind`` 回退时，分叉的时间线将被自动擦除，以便让故障的 primary 重新加入集群。然而，要让 ``use_pg_rewind`` 正常工作，集群必须使用 ``data page checksums`` 初始化（``initdb`` 的 ``--data-checksums`` 选项），并且/或者必须将 ``wal_log_hints`` 设置为 ``on``。

.. [2] 客户端可以使用 PostgreSQL 的 ``synchronous_commit`` 设置按事务更改此行为。``synchronous_commit`` 值为 ``off`` 和 ``local`` 的事务在 failover 时可能会丢失，但不会被复制延迟阻塞。
