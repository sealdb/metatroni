.. _dynamic_configuration:

============
动态配置设置
============

动态配置存储在 DCS（分布式配置存储）中，并应用于所有集群节点。

要修改动态配置，你可以使用 :ref:`patronictl_edit_config` 工具或 Patroni :ref:`REST API <rest_api>`。

-  **loop\_wait**\：循环休眠的秒数。默认值：10，最小可能值：1
-  **ttl**\：获取 leader lock 的 TTL（以秒为单位）。可以把它理解为自动 failover 流程启动之前的时长。默认值：30，最小可能值：20
-  **retry\_timeout**\：DCS 和 PostgreSQL 操作重试的超时时间（以秒为单位）。短于该时间的 DCS 或网络问题不会导致 Patroni 降级 leader。默认值：10，最小可能值：3

.. warning::
    在更改 **loop_wait**\、**retry_timeout** 或 **ttl** 的值时，你必须遵循以下规则：

    .. code-block:: python

        loop_wait + 2 * retry_timeout <= ttl


-  **maximum\_lag\_on\_failover**\：follower 可以落后于 leader 并仍能参与 leader 选举的最大字节数。
-  **maximum\_lag\_on\_syncnode**\：同步 follower 被视为不健康候选并被健康的异步 follower 替换之前，允许落后的最大字节数。如果有多个 follower，Patroni 会使用最大的 replica lsn，否则将使用 leader 当前的 wal lsn。默认值为 -1，当该值设置为 0 或更低时，Patroni 不会采取行动替换不健康的同步 follower。请将该值设置得足够大，这样在高事务量期间，Patroni 就不会频繁替换同步 follower。
-  **max\_timelines\_history**\：DCS 中保存的 timeline history 项的最大数量。默认值：0。设置为 0 时，会在 DCS 中保留完整的历史记录。
-  **primary\_start\_timeout**\：在触发 failover 之前，允许 primary 从故障中恢复的时间量（以秒为单位）。默认值为 300 秒。设置为 0 时，如果可能，检测到崩溃后会立即进行 failover。使用异步复制时，failover 可能导致事务丢失。primary 故障时最坏情况的 failover 时间为：loop\_wait + primary\_start\_timeout + loop\_wait，除非 primary\_start\_timeout 为零，此时仅为 loop\_wait。请根据你的持久性/可用性权衡来设置该值。
-  **primary\_stop\_timeout**\：Patroni 在停止 Postgres 时被允许等待的秒数，且仅在启用了 synchronous_mode 时生效。当设置为 > 0 且 synchronous_mode 已启用时，如果停止操作运行时间超过 primary\_stop\_timeout 设置的值，Patroni 会向 postmaster 发送 SIGKILL。请根据你的持久性/可用性权衡来设置该值。如果该参数未设置或设置为 <= 0，则 primary\_stop\_timeout 不生效。
-  **synchronous\_mode**\：开启同步复制模式。可能的值：``off``\、``on``\、``quorum``\。在这种模式下，leader 负责管理 ``synchronous_standby_names``\，并且只有最后一个已知的 leader 或某个同步 replica 被允许参与 leader 竞争。同步模式可确保已成功提交的事务在 failover 时不会丢失，代价是当 Patroni 无法保证事务持久性时，写入可用性会受到影响。详见 :ref:`replication modes documentation <replication_modes>`。
-  **synchronous\_mode\_strict**\：如果没有可用的同步 replica，则禁止禁用同步复制，从而阻止所有客户端对 primary 的写入。详见 :ref:`replication modes documentation <replication_modes>`。
-  **synchronous\_node\_count**\：如果启用了 ``synchronous_mode``\，Patroni 会使用此参数管理精确数量的同步 standby 实例，并在成员加入和离开时调整 DCS 中的状态以及 PostgreSQL 中的 ``synchronous_standby_names`` 参数。如果该参数设置的值高于合格节点的数量，它会被自动调整。默认为 ``1``\。
-  **failsafe\_mode**\：启用 :ref:`DCS Failsafe Mode <dcs_failsafe_mode>`。默认为 `false`。
-  **postgresql**\：

   -  **use\_pg\_rewind**\：是否使用 pg_rewind。默认为 `false`。请注意，集群必须使用 ``data page checksums``\（``initdb`` 的 ``--data-checksums`` 选项）初始化，并且/或者 ``wal_log_hints`` 必须设置为 ``on``\，否则 ``pg_rewind`` 将无法工作。
   -  **use\_slots**\：是否使用 replication slots。在 PostgreSQL 9.4+ 上默认为 `true`。
   -  **recovery\_conf**\：配置 follower 时写入 recovery.conf 的额外配置设置。PostgreSQL 12 中不再有 recovery.conf，但你仍可以继续使用此部分，因为 Patroni 会透明地处理它。
   -  **parameters**\：Postgres 的配置参数（GUCs），格式为 ``{max_connections: 100, wal_level: "replica", max_wal_senders: 10, wal_log_hints: "on"}``\。其中许多参数是复制正常工作所必需的。

   -  **pg\_hba**\：Patroni 将用来生成 ``pg_hba.conf`` 的行列表。如果 ``hba_file`` PostgreSQL 参数设置为非默认值，Patroni 会忽略此参数。

      -  **- host all all 0.0.0.0/0 md5**
      -  **- host replication replicator 127.0.0.1/32 md5**\：复制需要这样的一行。

   -  **pg\_ident**\：Patroni 将用来生成 ``pg_ident.conf`` 的行列表。如果 ``ident_file`` PostgreSQL 参数设置为非默认值，Patroni 会忽略此参数。

      -  **- mapname1 systemname1 pguser1**
      -  **- mapname1 systemname2 pguser2**

-  **standby\_cluster**\：如果定义了此部分，我们希望 bootstrap 一个 standby cluster。

   -  **host**\：远程节点的地址
   -  **port**\：远程节点的端口
   -  **primary\_slot\_name**\：使用远程节点上的哪个 slot 进行复制。此参数是可选的，默认值由实例名称派生而来（参见函数 `slot_name_from_member_name`）。
   -  **create\_replica\_methods**\：可用于从远程 primary bootstrap standby leader 的有序方法列表，可以不同于 :ref:`postgresql_settings` 中定义的方法列表
   -  **restore\_command**\：用于将 WAL 记录从远程 primary 恢复到 standby cluster 中节点的命令，可以不同于 :ref:`postgresql_settings` 中定义的列表
   -  **archive\_cleanup\_command**\：standby leader 的清理命令
   -  **recovery\_min\_apply\_delay**\：在 standby leader 上实际应用 WAL 记录之前需要等待多长时间

-  **member_slots_ttl**\：replica 关闭时，为其保留物理 replication slots 的保留时间。默认值：`30min`。如果你想保留旧行为（member key 从 DCS 过期时立即删除 slot），请将其设置为 `0`。该功能仅从 PostgreSQL 11 开始可用。
-  **slots**\：定义永久 replication slots。这些 slots 在 switchover/failover 期间会被保留。不存在的永久 slots 将由 Patroni 创建。从 PostgreSQL 11 开始，永久物理 slots 会在所有节点上创建，并且每隔 **loop_wait** 秒推进一次它们的位置。对于早于 11 的 PostgreSQL 版本，永久物理 replication slots 只在当前 primary 上维护。逻辑 slots 会在重启时从 primary 复制到 standby，之后每隔 **loop_wait** 秒推进一次它们的位置（如有必要）。复制逻辑 slot 文件通过 ``libpq`` 连接执行，并使用 rewind 或 superuser 凭据（参见 **postgresql.authentication** 部分）。replica 上的逻辑 slot 位置始终有可能比原 primary 略靠后，因此应用程序应做好在 failover 后可能第二次收到某些消息的准备。最简单的做法是跟踪 ``confirmed_flush_lsn``\。启用永久 replication slots 需要将 **postgresql.use_slots** 设置为 ``true``\。如果定义了永久逻辑 replication slots，Patroni 会自动启用 ``hot_standby_feedback``\。由于逻辑 replication slots 的 failover 在 PostgreSQL 9.6 及更早版本上不安全，而且 PostgreSQL 10 缺少一些重要函数，因此该功能仅适用于 PostgreSQL 11+。

   -  **my\_slot\_name**\：永久 replication slot 的名称。如果永久 slot 的名称与当前节点的名称匹配，则不会在此节点上创建它。如果你添加的永久物理 replication slot 的名称与某个 Patroni 成员的名称匹配，Patroni 将确保即使相应成员变得无响应（这种情况通常会导致 Patroni 删除该 slot），已创建的 slot 也不会被删除。虽然这在某些情况下很有用，例如当你希望成员使用的 replication slots 在临时故障期间得以保留，或者将现有成员导入新的 Patroni 集群时（详见 :ref:`Convert a Standalone to a Patroni Cluster <existing_data>`），但操作人员应谨慎行事，在不再需要该 slot 时，不要让这些名称冲突持久存在于 DCS 中，因为它会影响 Patroni 的正常运作。

      -  **type**\：slot 类型。可以是 ``physical`` 或 ``logical``\。如果 slot 是 logical 类型，你还需要定义 ``database`` 和 ``plugin``\。如果 slot 是 physical 类型，你可以选择定义 ``cluster_type``\。
      -  **database**\：应在其中创建逻辑 slots 的数据库名称。
      -  **plugin**\：逻辑 slot 的插件名称。
      -  **cluster_type**\：仅在指定类型的集群（``primary`` 或 ``standby``\）上创建该 slot，否则它不会被创建，或者已有的 slot 会被删除。

-  **ignore\_slots**\：replication slot 属性集合的列表，对于匹配的 slots，Patroni 应忽略它们。当某些 replication slots 由 Patroni 之外管理时，此配置/功能等非常有用。匹配属性的任意子集都会导致 slot 被忽略。

   -  **name**\：replication slot 的名称。
   -  **type**\：slot 类型。可以是 ``physical`` 或 ``logical``\。如果 slot 是 logical 类型，你还可以定义 ``database`` 和/或 ``plugin``\。
   -  **database**\：数据库名称（当匹配 ``logical`` slot 时）。
   -  **plugin**\：逻辑解码插件（当匹配 ``logical`` slot 时）。

注意：**slots** 是一个哈希表（hashmap），而 **ignore_slots** 是一个数组。例如：

.. code:: YAML

        slots:
          permanent_logical_slot_name:
            type: logical
            database: my_db
            plugin: test_decoding
          permanent_physical_slot_name:
            type: physical
          ...
        ignore_slots:
          - name: ignored_logical_slot_name
            type: logical
            database: my_db
            plugin: test_decoding
          - name: ignored_physical_slot_name
            type: physical
          ...

注意：当运行 PostgreSQL v11 或更新版本时，Patroni 会在所有可能成为 leader 的节点上维护物理 replication slots，这样如果 replica 节点可能被其他节点需要，它们的 WAL 段就会被保留。如果节点缺席且其 DCS 中的 member key 已过期，相应的 replication slot 会在 ``member_slots_ttl`` （默认值为 `30min`）之后被删除。你可以根据需要增加或减少保留时间。另外，如果你的集群拓扑是静态的（节点数量固定且名称永不改变），你可以配置与节点名称对应的永久物理 replication slots，以避免在 replica 暂时下线时发生 slot 删除和 WAL 文件回收：

.. code:: YAML

        slots:
          node_name1:
            type: physical
          node_name2:
            type: physical
          node_name3:
            type: physical
          ...


.. warning::
   永久 replication slots 只从 ``primary``/``standby_leader`` 同步到 replica 节点。这意味着，应用程序只应从 leader 节点使用它们。在 replica 节点上使用它们将导致集群中所有其他节点的 ``pg_wal`` 无限增长。该规则的一个例外是匹配 Patroni 成员名称的物理 slots（由 Patroni 创建和维护）。这些 slots 会在所有节点之间同步，因为它们被用于节点之间的复制。


.. warning::
   在 standby 上设置 ``nostream`` 标签会禁用该节点自身及其所有级联 replica（如果有）上永久逻辑 replication slots 的复制和同步。
