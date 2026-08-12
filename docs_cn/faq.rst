.. _faq:

FAQ
===

本章节汇总了关于 Patroni 最常见问题的答案。
每个子章节专注于不同类型的问题。

我们希望这能帮你澄清大部分疑问。
如果你仍有疑问或遇到意外问题，请参阅 :ref:`chatting` 和 :ref:`reporting_bugs`，了解如何获取帮助或报告问题。

与其他 HA 方案的对比
----------------------------------

为什么 Patroni 需要一套独立的 DCS 节点集群，而像 ``repmgr`` 这样的其他方案却不需要？
    实现 HA 方案的方式有多种，每种都有各自的优缺点。

    像 ``repmgr`` 这样的软件通过节点间的通信来决定何时应采取行动。

    而 Patroni 则依赖存储在 DCS 中的状态。DCS 作为 Patroni 决定其行为的权威数据源（source of truth）。

    虽然独立的 DCS 集群可能会让架构变得臃肿，但这种方式也降低了 Postgres 集群发生脑裂（split-brain）的概率。

在 Postgres 管理方面，Patroni 与其他 HA 方案有什么区别？
    Patroni 不仅管理 Postgres 集群的高可用性，还负责管理 Postgres 本身。

    如果 Postgres 节点尚不存在，它会负责 bootstrap primary 和 standby 节点，并管理这些节点的 Postgres 配置。如果 Postgres 节点已经存在，Patroni 将接管集群的管理。

    除此之外，Patroni 还具备自愈能力。换句话说，如果 primary 节点发生故障，Patroni 不仅会 failover 到某个 replica，还会尝试将原 primary 重新加入集群，作为新 primary 的 replica。同样，如果某个 replica 发生故障，Patroni 也会尝试将其重新加入。

    这就是我们把 Patroni 称为「HA 方案的模板」的原因。它不仅仅管理物理复制：它把 Postgres 作为一个整体来管理。

DCS
---

我可以使用同一个 ``etcd`` 集群来存储两个或多个 Patroni 集群的数据吗？
    可以！

    关于 Patroni 集群的信息存储在 DCS 中，路径以 ``namespace`` 和 ``scope`` 这两个 Patroni 设置为前缀。

    只要不同 Patroni 集群之间的 namespace 和 scope 不冲突，你就可以使用同一个 DCS 集群来存储多个 Patroni 集群的信息。

如果多个不同的 Patroni 集群指向同一个 DCS 集群，而它们使用相同的 ``namespace`` 和 ``scope`` 组合，会发生什么？
    第二个尝试使用相同 ``namespace`` 和 ``scope`` 的 Patroni 集群将无法管理 Postgres，因为它会在 DCS 中找到与该组合相关的信息，但其中包含不兼容的 Postgres system identifier。
    system identifier 不匹配会导致 Patroni 中止对第二个集群的管理，因为它认为这指向另一个集群，且用户配置错了 Patroni。

    当不同的 Patroni 集群共享同一个 DCS 集群时，请务必使用不同的 ``namespace``/ ``scope``。

如果我丢失了 DCS 集群，会发生什么？
    DCS 主要用于存储 Patroni 集群的状态和动态配置。

    最直接的后果是，所有依赖该 DCS 的 Patroni 集群都会进入 read-only 模式 —— 除非启用了 :ref:`dcs_failsafe_mode`。

如果丢失了 DCS 集群，我该怎么做？
    丢失 DCS 集群后可能有三种结果：

    1. DCS 集群完全恢复：这不需要 Patroni 侧做任何操作。一旦 DCS 集群恢复，Patroni 应该也能随之恢复；
    2. DCS 集群在原地重建，且端点保持不变。Patroni 侧无需任何变更；
    3. 使用不同端点创建了新的 DCS 集群。你需要更新每个 Patroni 节点配置中的 DCS 端点。

    如果遇到 ``2.`` 或 ``3.`` 的情形，Patroni 会根据集群当前状态重新创建状态信息，并根据存储在 Patroni 集群每个成员的 Postgres 数据目录中的备份文件 ``patroni.dynamic.json`` 在 DCS 上重建动态配置。

如果我失去了 DCS 集群的多数派，会发生什么？
    DCS 将变得不可响应，这会导致 Patroni 将当前可读写的 Postgres 节点降级（demote）。

    请记住：Patroni 依赖 DCS 中的状态来对集群采取行动。

    你可以使用 :ref:`dcs_failsafe_mode` 来缓解这种情况。

patronictl
----------

我需要在 Patroni 主机上运行 :ref:`patronictl` 吗？
    不需要。

    如果你能访问 Patroni 主机，在主机上运行 :ref:`patronictl` 会很方便，因为你可以直接复用 ``patroni`` agent 的同一个配置文件来运行 :ref:`patronictl`。

    不过，:ref:`patronictl` 本质上是一个客户端，可以从远程机器执行。你只需提供足够的配置，让它能够访问 DCS 和 Patroni 成员的 REST API。

为什么我的某个 Patroni 成员的信息从 :ref:`patronictl_list` 命令的输出中消失了？
    :ref:`patronictl_list` 显示的信息基于 DCS 中的内容。

    如果某个成员的信息从 DCS 中消失，很可能是该节点上的 Patroni agent 已不再运行，或者无法与 DCS 通信。

    由于成员无法更新信息，这些信息最终会在 DCS 中过期，因此该成员不再出现在 :ref:`patronictl_list` 的输出中。

为什么我的某个 Patroni 成员的信息在 :ref:`patronictl_list` 命令的输出中没有及时更新？
    :ref:`patronictl_list` 显示的信息基于 DCS 中的内容。

    默认情况下，Patroni 大约每隔 ``loop_wait`` 秒更新一次这些信息。
    换句话说，即使一切运行正常，你也可能看到存储在 DCS 中的信息存在最多 ``loop_wait`` 秒的「延迟」。

    不过请注意，这并不是绝对的。Patroni 执行的某些操作会触发其立即更新 DCS 信息。

配置
-------------

动态配置和本地配置有什么区别？
    动态配置（即全局配置）是存储在 DCS 中的配置，应用于 Patroni 集群的所有成员。
    这里应该是你存放配置的主要位置。

    对于特定于某个节点的设置，或你想用来覆盖全局配置的设置，只应在目标 Patroni 成员上以本地配置的形式设置。
    本地配置可以通过配置文件或环境变量来指定。

    更多内容请参阅 :ref:`patroni_configuration`。

Patroni 中有哪些配置类型，它们的优先级是怎样的？
    配置类型如下：

    * 动态配置：应用于所有成员；
    * 本地配置：应用于本地成员，覆盖动态配置；
    * 环境配置：应用于本地成员，同时覆盖动态配置和本地配置。

    **注意：** 某些 Postgres GUC 只能全局设置，即通过动态配置设置。此外，还有一部分 GUC 由 Patroni 强制使用硬编码值。

    更多内容请参阅 :ref:`patroni_configuration`。

有没有什么工具可以帮助我创建 Patroni 配置文件？
    有的。

    你可以使用 ``patroni --generate-sample-config`` 或 ``patroni --generate-config`` 命令，分别生成示例 Patroni 配置，或基于现有 Postgres 实例生成 Patroni 配置。

    更多细节请参阅 :ref:`generate_sample_config` 和 :ref:`generate_config`。

我修改了 ``bootstrap.dcs`` 配置下的参数，但 Patroni 没有将这些更改应用到集群成员。这是怎么回事？
    ``bootstrap.dcs`` 下配置的值只在 bootstrap 全新集群时使用。这些值会在 bootstrap 期间写入 DCS。

    bootstrap 阶段结束后，你只能通过 DCS 来修改动态配置。

    详情请参阅下一个问题。

如何修改我的动态配置？
    你需要修改 DCS 中的配置，可以通过以下任一方式完成：

    * 使用 :ref:`patronictl_edit_config`；或
    * 向 :ref:`config_endpoint` 发送 ``PATCH`` 请求。

如何修改我的本地配置？
    你需要修改相应 Patroni 成员的配置文件，并向 Patroni agent 发送 ``SIGHUP`` 信号。可以通过以下任一方式：

    * 向 REST API :ref:`reload_endpoint` 发送 ``POST`` 请求；或
    * 运行 :ref:`patronictl_reload`；或
    * 在本地向 Patroni 进程发送 ``SIGHUP`` 信号：

        * 如果你通过 systemd 启动 Patroni，可以使用 ``systemctl reload PATRONI_UNIT.service`` 命令，其中 ``PATRONI_UNIT`` 是 Patroni 服务的名称；或
        * 如果你通过其他方式启动 Patroni，需要找到 ``patroni`` 进程并运行 ``kill -s HUP PID``，其中 ``PID`` 是 ``patroni`` 进程的进程 ID。

    **注意：** 某些情况下，通过 :ref:`patronictl_reload` 重载可能不生效：

    * REST API 证书过期：可以通过使用 :ref:`patronictl` 的 ``-k`` 选项来缓解；
    * 凭据错误：例如在配置文件中修改了 ``restapi`` 或 ``ctl`` 的凭据，并且 Patroni 和 :ref:`patronictl` 共用同一份配置文件。

如何修改我的环境配置？
    Patroni 只在启动时读取环境配置。

    因此，如果你修改了环境配置，就需要重启相应的 Patroni agent。

    请注意不要因此导致集群发生 failover！你可能会对 :ref:`patronictl_pause` 感兴趣。

正常运行时如何减少重复的心跳日志行？
    如果日志中反复出现诸如 ``Lock owner: ...`` 和 ``no action. I am ...`` 之类的行导致噪音过多，
    可以配置 ``log.deduplicate_heartbeat_logs: true``。

    你可以在 Patroni YAML 文件（:ref:`log_settings`）中设置，
    也可以通过 ``PATRONI_LOG_DEDUPLICATE_HEARTBEAT_LOGS=true`` 设置。

    请注意，这会通过抑制重复的心跳消息来减少日志量，但同时你也会失去逐循环的心跳可见性，
    而这些信息在 failover 排查时可能很有帮助。

如果我修改了一个需要 reload 的 Postgres GUC，会发生什么？
    当你按照前面问题所述修改动态配置或本地配置时，Patroni 会自动帮你重载 Postgres 配置。

如果我修改了一个需要 restart 的 Postgres GUC，会发生什么？
    Patroni 会给受影响的成员标记 ``pending restart`` 标志。

    由你决定何时以及如何重启这些成员，可以通过以下任一方式完成：

    * 使用 :ref:`patronictl_restart`；或
    * 向 :ref:`restart_endpoint` 发送 ``POST`` 请求。

    **注意：** 某些 Postgres GUC 在重启 Postgres 节点时需要特别注意顺序。更多细节请参阅 :ref:`shared_memory_gucs`。

Patroni 配置中的 ``etcd`` 和 ``etcd3`` 有什么区别？
    ``etcd`` 使用 ``etcd`` 的 API 版本 2，而 ``etcd3`` 使用 ``etcd`` 的 API 版本 3。

    请注意，API 版本 2 存储的信息无法被 API 版本 3 管理，反之亦然。

    我们推荐配置 ``etcd3`` 而不是 ``etcd``，原因如下：

    * API 版本 2 从 Etcd v3.4 起默认被禁用；
    * API 版本 2 将在 Etcd v3.6 中被彻底移除。

我的 Patroni 配置中启用了 ``use_slots``，但当某个集群成员离线一段时间后，该成员使用的 replication slot 在上游节点上被删除了。如何避免这个问题？
    有两种选择：

    1. 你可以调优 ``member_slots_ttl``（默认值 ``30min``，自 Patroni ``4.0.0`` 及 PostgreSQL 11 起可用），当成员的停机时间短于配置的阈值时，缺席成员的 replication slots 将不会被移除。
    2. 你可以为成员配置永久的物理 replication slots。

    从 Patroni ``3.2.0`` 起，可以将成员 slot 配置为由 Patroni 管理的永久 slot。

    Patroni 会在所有节点上创建这些永久物理 slot，并确保不移除这些 slot，同时根据成员已消费的 LSN，在所有节点上推进这些 slot 的 LSN。

    之后，如果你决定移除相应的成员，调整永久 slot 配置是 **你的责任**，否则 Patroni 会永远保留这些 slot。

    **注意：** 在早于 ``3.2.0`` 的 Patroni 版本中，你仍然可以将成员 slot 配置为永久物理 slot，但它们只会在当前 leader 上被管理。也就是说，在发生 failover/switchover 时，这些 slot 会在新 leader 上被创建，但这并不能保证新 leader 拥有缺席节点所需的全部 WAL 段。

    **注意：** 即使在 Patroni ``3.2.0`` 中也可能存在细微的竞态条件。在最开始时，当 slot 在 replica 上创建时，它可能领先于 leader 上相同的 slot；如果没有人消费该 slot，failover 后仍有可能丢失一些文件。考虑到这一点，建议你配置连续归档（continuous archiving），这样可以恢复所需的 WAL 或执行 PITR。

``loop_wait``、``retry_timeout`` 和 ``ttl`` 有什么区别？
    Patroni 会定期执行我们所说的 HA 周期。在每个 HA 周期中，它会对集群执行一系列检查以判断其健康状态，并根据状态采取行动，例如 failover 到 standby。

    ``loop_wait`` 决定 Patroni 在开始新一轮 HA 检查前需要休眠的秒数。

    ``retry_timeout`` 设置 DCS 和 Postgres 上重试操作的超时时间。例如：如果 DCS 超过 ``retry_timeout`` 秒无响应，Patroni 可能会将 primary 节点降级，作为一种安全措施。

    ``ttl`` 设置 DCS 中 ``leader`` 锁的租约时间。如果集群的当前 leader 在 HA 周期内无法在 ``ttl`` 时间内续租，租约就会过期，从而在集群中触发 ``leader race``。

    **注意：** 修改这些设置时，请记住 Patroni 会强制执行文档 :ref:`dynamic_configuration` 一节中描述的规则和最小值。

Postgres 管理
-------------------

我可以直接在 Postgres 配置中修改 Postgres GUC 吗？
    可以，但你应该避免这样做。

    Postgres 配置由 Patroni 管理，尝试直接编辑配置文件很可能会被 Patroni 覆盖，因为 Patroni 最终会重写这些文件。

    有几个选项可以绕开 Patroni 的管理：

    * 通过 ``$PGDATA/postgresql.base.conf`` 修改 Postgres GUC；或
    * 定义 ``postgresql.custom_conf`` 来替代 ``postgresql.base.conf``，从而在外部管理；或
    * 使用 ``ALTER SYSTEM``/ ``ALTER DATABASE``/ ``ALTER USER`` 修改 GUC。

    更多相关信息请参阅 :ref:`important_configuration_rules` 一节。

    无论如何，我们都建议你通过 Patroni 管理所有 Postgres 配置。这样可以集中管理，并在需要时更容易排查 Patroni 的问题。

我可以直接重启 Postgres 节点吗？
    不可以，你 **不应** 尝试直接管理 Postgres！

    任何绕过 Patroni 重启 Postgres 服务器的操作都可能导致集群发生 failover。

    如果你需要管理 Postgres 服务器，请通过 Patroni 提供的方式来完成。

Patroni 能否接管已存在的 Postgres 集群的管理？
    可以！

    详细说明请参阅 :ref:`existing_data`。

Patroni 是如何管理 Postgres 的？
    Patroni 通过运行 Postgres 二进制程序（如 ``pg_ctl`` 和 ``postgres``）来负责 Postgres 的启停。

    因此你 **必须** 禁用任何其他可能管理 Postgres 集群的机制，例如 systemd 单元（如 ``postgresql.service``）。只有 Patroni 才能启动、停止和提升集群中的 Postgres 实例。否则可能导致脑裂（split-brain）。例如：如果作为 primary 运行的节点发生故障，而 ``postgresql.service`` 单元已启用，它可能会将 Postgres 重新拉起，从而引发脑裂。

概念与要求
-------------------------

Patroni 由哪些应用程序组成？
    Patroni 主要包含两个应用程序：

    * ``patroni``：这是 Patroni agent，负责管理一个 Postgres 节点；
    * ``patronictl``：这是一个命令行工具，用于与 Patroni 集群交互（执行 switchover、重启、修改配置等）。更多信息请参阅 :ref:`patronictl`。

Patroni 中的 ``standby cluster`` 是什么？
    它是一个没有任何 primary Postgres 节点运行的集群，也就是说集群中没有可读写的成员。

    这类集群的存在目的是从另一个集群复制数据，通常在需要跨数据中心复制数据时非常有用。

    集群中会有一个 leader，它是一个 standby，负责从远程 Postgres 节点复制变更。
    然后会有一组 standby 通过级联复制（cascading replication）从该 leader 成员复制数据。

    **注意：** standby cluster 对它所复制的源集群一无所知 —— 它甚至可以使用 ``restore_command`` 代替 WAL 流式复制，并且可以使用完全独立的 DCS 集群。

    更多细节请参阅 :ref:`standby_cluster`。

Patroni 中的 ``leader`` 是什么？
    Patroni 中的 ``leader`` 就像集群的协调者。

    在常规的 Patroni 集群中，``leader`` 就是可读写节点。

    在 standby Patroni 集群中，``leader``（又称 ``standby leader``）负责从远程 Postgres 节点复制数据，并将这些变更级联给 standby cluster 的其他成员。

Patroni 是否要求集群中的 Postgres 节点达到最小数量？
    不要求，你可以使用任意数量的 Postgres 节点运行 Patroni。

    请记住：Patroni 与 DCS 是解耦的。

Patroni 中的 ``pause`` 是什么意思？
    Pause 是 Patroni 提供的一种操作，让用户可以要求 Patroni 在 Postgres 管理方面暂缓行动。

    这在你希望对集群进行维护、并希望避免 Patroni 做出与 HA 相关的决策（例如在停止 primary 时 failover 到 standby）时非常有用。

    更多信息请参阅 :ref:`pause`。

自动 failover
------------------

Patroni 的自动 failover 机制是如何工作的？
    Patroni 的自动 failover 基于我们所说的 ``leader race``。

    Patroni 将集群状态存储在 DCS 中，其中包括一把 ``leader`` 锁，锁中保存着当前作为集群 ``leader`` 的 Patroni 成员名称。

    这把 ``leader`` 锁有关联的生存时间（time-to-live）。如果 leader 节点未能及时续租 ``leader`` 锁，该 key 最终会从 DCS 中过期。

    当 ``leader`` 锁过期时，会触发 Patroni 所说的 ``leader race``：所有节点开始执行检查，以确定自己是否是接管 ``leader`` 角色的最佳候选者。
    其中一些检查包括调用所有其他 Patroni 成员的 REST API。

    所有认为自己是最佳候选者、能够接管 ``leader`` 锁的 Patroni 成员都会尝试这样做。
    第一个成功获取 ``leader`` 锁的 Patroni 成员会将自己提升为可读写节点（或 ``standby leader``），其他成员则会被配置为跟随它。

我可以暂时禁用 Patroni 集群的自动 failover 吗？
    可以！

    你可以通过暂时 pause 集群来实现这一点。
    这在执行维护时尤其有用。

    当你想恢复集群的自动 failover 时，只需取消 pause 即可。

    更多信息请参阅 :ref:`pause`。

Bootstrap 与 standby 的创建
-----------------------------------

Patroni 如何创建 primary Postgres 节点？standby Postgres 节点呢？
    默认情况下，Patroni 使用 ``initdb`` 来 bootstrap 一个新集群，并使用 ``pg_basebackup`` 从 ``leader`` 成员的副本创建 standby 节点。

    你可以通过编写自定义的 bootstrap 方法和自定义的 replica 创建方法来定制这一行为。

    当你希望恢复由 pgBackRest 或 Barman 等备份工具创建的备份时，自定义方法通常非常有用。

    详细信息请参阅 :ref:`custom_bootstrap` 和 :ref:`custom_replica_creation`。

监控
----------

如何监控我的 Patroni 集群？
    Patroni 在其 :ref:`rest_api` 中提供了几个方便的端点：

    * ``/metrics``：以 Prometheus 可消费的格式暴露监控指标；
    * ``/patroni``：以 JSON 格式暴露集群状态。这里显示的信息与 ``/metrics`` 端点显示的信息非常相似。

    你可以使用这些端点来实现监控检查。

MySQL 后端
-------------

MySQL HA 文档在哪里？
    请参阅 :ref:`MySQL <mysql>` 章节：

    * :ref:`mysql_architecture`— 组件与 DCS 模型
    * :ref:`mysql_mechanisms`— failover / demote / semi-sync / MGR 流程
    * :ref:`mysql_ops`— 安装、部署、HAProxy、FAQ

MySQL 是否支持与 PostgreSQL 相同的 standby cluster 功能？
    不支持。跨站点 standby cluster 依赖 PostgreSQL 的 WAL 归档，MySQL 不支持该功能。
    请在单个 Patroni scope 内使用 async / semi-sync / MGR，或使用手动切换方案运维独立的集群。
