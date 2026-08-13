.. _releases:

发布说明
========

版本 4.1.3
----------

发布于 2026-05-05

**稳定性改进**

- 正确处理错误标注的 Etcd 错误（Ants Aasma）

  当前版本的 Etcd 在更新 lease 时若 Etcd leader 丢失会抛出 ``Unknown`` 错误。Patroni 现在会将报告的错误码覆盖为 ``Unavailable``\。

**缺陷修复**

- 当 ``PG_VERSION`` 文件不存在时使用二进制版本（Polina Bungina）

  在某些情况下，例如使用自定义 bootstrap 时，数据目录中可能不存在 ``PG_VERSION`` 文件。这种情况下，Patroni 会将该版本视为 0.0，导致一些与版本相关的逻辑出现问题。通过此修复，Patroni 会在这种情况下尝试从二进制文件获取版本。

- 重构 logger 初始化以避免丢失早期日志消息（Alexander Kukushkin）

  在加载 ``Config`` 之前创建 ``PatroniLogger``\，以捕获早期日志消息。

- 在 ``RELOADING=1`` 的 systemd 通知中包含 ``MONOTONIC_USEC`` （Alexander Kukushkin）

  systemd 257 及以上版本要求 ``Type=notify-reload`` 服务在 ``RELOADING=1`` 的同时提供 ``MONOTONIC_USEC``\。否则，``systemctl reload`` 会无限期挂起。

**改进**

- 当存在 ``backup_label`` 时跳过单用户崩溃恢复（Vadim Ponomarev）

  当启动从外部备份（未使用自定义 bootstrap 方法）恢复的 replica 时，跳过单用户崩溃恢复，让 PostgreSQL 在正常启动过程中自行处理。

- 在未安装 ``python-systemd`` 包的情况下运行于 ``systemd`` 下时发出警告（Alexander Kukushkin）

  不再在启动时记录"systemd 集成不受支持"日志，而是检查 ``NOTIFY_SOCKET``\，仅在确实运行于 ``systemd`` 之下且未安装 ``python-systemd`` 包时才发出警告。


版本 4.1.2
----------

发布于 2026-04-21

**Systemd 支持改进**

- 添加对 ``notify-reload`` systemd 单元类型的支持（Ronan Dunklau）

  允许 ``systemctl reload`` 通过向 systemd 发送 ``RELOADING=1`` 和 ``READY=1`` 通知，等待直到 Patroni 真正完成配置重载。

- 关闭时向 systemd 发送 ``STOPPING=1`` 通知（Alexander Kukushkin）

  Patroni 现在会遵循 systemd notify 协议，在关闭时正确通知 systemd 其正在停止。

- 不要让 PostgreSQL 通知 systemd（Alexander Kukushkin）

  从示例 systemd 单元文件中移除 ``NotifyAccess=all``\。在启动 PostgreSQL 时从环境中过滤 ``NOTIFY_SOCKET``\，以免其向 systemd 发送 ``READY=1`` 或 ``STOPPING=1``\。当接管一个在 Patroni 之前启动且已设置 ``NOTIFY_SOCKET`` 的 PostgreSQL 时，在 PostgreSQL 关闭期间重新断言 ``READY=1``\，以抵消其 ``STOPPING=1``\。


版本 4.1.1
----------

发布于 2026-04-08

**稳定性改进**

- 与 python 3.11+ 中的线程化变更保持兼容（Alexander Kukushkin）

  避免在运行时启动/停止线程。为 REST API 和执行异步任务引入线程池。允许配置全局的 ``thread_pool_size`` 和 ``restapi.thread_pool_size``\。

- 与 python 3.14 保持兼容（Alexander Kukushkin）

  针对 python 3.14 运行测试并修复兼容性问题。

- 与 Etcd v3.6.9、v3.5.28 和 v3.4.42 中的安全修复保持兼容（Alexander Kukushkin）

  这些 Etcd 版本修复了相关 CVE，并改变了行为，使得集群拓扑读取和 lease 保活不再允许在未认证的情况下进行。Patroni 现在通过在成员发现和 lease 保活路径中进行认证、在认证失败时重新认证并相应地重试请求来处理这种情况。

- 改进 Etcd3 错误处理（Alexander Kukushkin）

  处理损坏的 JSON 响应，灵活解析 JSON 错误，并改进对 etcd 内部错误的报告。

**缺陷修复**

- 在 Kubernetes 临时 ``403`` 错误时重试 leader 更新（Sophia Ruan、Alexander Kukushkin）

  当 Kubernetes API 临时返回 ``403 Permission Denied``\（例如 RBAC 瞬态问题时），Patroni 现在会先验证当前节点是否仍持有 leader 身份，并在 ``retry_timeout`` 内重试 leader 更新，而不是立即降级。

- 修复同步模式下重命名 leader 节点与 pause 的问题（Alexander Kukushkin）

  在 pause 状态下（不重启 Postgres）重命名 leader 节点后，``/sync`` 键未得到更新。这导致 Patroni 在解除 pause 后的下一次重启时无法提升。

- 当同一 primary 提升时间线时触发 ``pg_rewind`` 检查（Alexander Kukushkin）

  这种时间线提升可能是在取得 leader 键后、其他 replica 节点与 DCS 隔离时，以单用户模式进行崩溃恢复并提升所导致的结果。这种情况下，replica 节点不会触发 ``pg_rewind`` 状态机，因为 leader 及其 ``primary_conninfo`` 没有发生变化。

- 仅在 ``initdb`` bootstrap 期间写入非空超级用户密码（Michael Banck）

  在 ``initdb`` bootstrap 期间写入空密码会导致问题。

- 修复 ``synchronous_mode=on`` 时 ``failover_priority`` 的缺陷（Alexander Kukushkin）

  当 ``synchronous_node_count > 1`` 时，``tag.failover_priority`` 的值会被忽略。

- 修复 ``primary_conninfo`` 密码比较的缺陷（Alexander Kukushkin）

  从 PostgreSQL 10 开始，Patroni 在 ``primary_conninfo`` 中使用 passfile，但在通过重载以 yaml 文件配置更新复制密码后，未能更新 passfile。

- 在 pause 模式下不要重启带有 ``nofailover`` 标签的 replica（Alexander Kukushkin）

  此前，当 replica 设置了 ``nofailover`` 标签为 ``true`` 时，Patroni 会在 pause 模式下启动手动关闭的 PostgreSQL replica。

- 修复 PostgreSQL 处于 starting 状态时的 ``check_recovery_conf()`` （Alexander Kukushkin）

  对于 PostgreSQL v12 及更新版本，服务器仍在启动且尚未接受连接时无法查询 ``pg_settings``\。现在，在写入 ``postgresql.conf`` 时会将缺失的恢复参数添加到内部状态。此外，恢复了 ``Ha.is_healthiest_node()`` 中的 ``Postgresql.is_starting()`` 检查。

- 验证以字典格式提供的 ``initdb``/``basebackup`` 用户选项（m4rrypro）

  当 ``initdb`` 或 ``basebackup`` 选项以字典（而非列表）形式提供时，``option_is_allowed()`` 验证会被绕过，从而允许使用被阻止的选项。

- 允许 ``basebackup`` 选项使用服务器端压缩（m4rrypro）

  ``basebackup`` 的 ``compress`` 选项曾被完全阻止，但自 PostgreSQL 15 起，服务器端压缩在 plain 格式下是有用且透明工作的。客户端压缩仍会被拒绝。

- 运行自定义 bootstrap 期间不要重载 PostgreSQL 配置（Alexander Kukushkin）

  自定义 bootstrap 可能很复杂，涉及 PostgreSQL 多次启动和停止。在此过程中重载 PostgreSQL 配置可能导致意外行为。

- 检查 ``postgresql.parameters`` 是否为字典（Alexander Kukushkin）

  如果 ``postgresql.parameters`` 不是字典，则丢弃新配置。


版本 4.1.0
----------

发布于 2025-09-23

**新特性**

- 添加对 systemd "notify" 单元类型的支持（Ronan Dunklau）

  如果不使用 notify 单元类型，则有可能通过 systemd 启动 Patroni 后立即向其发送 SIGHUP 信号，从而在它还没来得及设置信号处理器之前就将其终止。

- 在 API 和 ctl 中提供接收和回放 LSN/延迟信息（Polina Bungina）

  Patroni REST API ``/cluster`` 端点和 ``patronictl list`` 命令现在为每个 replica 成员提供接收 LSN、回放 LSN、接收延迟和回放延迟信息。

- 确保干净地降级为 standby 集群（Polina Bungina）

  确保在动态配置中引入 ``standby_cluster`` 配置节会带来干净的集群降级。

- 实现 ``patronictl demote-cluster`` 和 ``promote-cluster`` 命令（Polina Bungina）

  用于集群降级和提升的新命令同时处理动态配置编辑和结果状态检查。

- 实现 ``sync_priority`` 标签（Polina Bungina）

  当 ``synchronous_mode`` 设置为 ``on`` 时，该参数控制成员在同步 replica 选择过程中的优先级。

- 为 ``--validate-config`` 实现 ``--print`` 选项（Polina Bungina）

  在本地配置（包括环境配置覆盖）成功验证后将其打印出来。

- 实现 ``kubernetes.bootstrap_labels`` （Polina Bungina）

  该特性允许您定义在成员 pod 处于 ``initializing new cluster``\、``running custom bootstrap script``\、``starting after custom bootstrap`` 或 ``creating replica`` 状态时分配给该 pod 的标签。

- 添加用于抑制重复心跳日志的配置选项（Michael Morris）

  如果设置为 ``true``\，则不再输出连续且相同的心跳日志。

- 为永久复制槽添加可选的 ``cluster_type`` 属性（Michael Banck）

  这允许您设置某个特定永久复制槽是应始终创建，还是仅在 primary 或 standby 集群上创建。

- 使 HTTP Server 头可配置（David Grierson）

  引入 ``restapi.server_tokens`` 配置参数，允许您限制 HTTP Server 头中披露的信息。

- 为 replica 成员实现复制就绪性 API 检查（Ants Aasma）

  之前的实现只要 PostgreSQL 启动就认为 replica 已就绪。通过此更改，只有当 replica pod 正在复制且与 leader 的差距不太大时，才认为其已就绪。

**改进**

- 降低 watchdog 配置失败的日志级别（Ants Aasma）

  除非 watchdog 配置为 ``required`` 模式，否则 ``Could not activate Linux watchdog device`` 日志行现在只在 debug 日志级别显示。之前它在 info 级别显示。

- 利用 ``pg_stat_wal_receiver`` 中的 ``written_lsn`` 和 ``latest_end_lsn`` （Alexander Kukushkin）

  现在优先使用实际写入 LSN ``written_lsn``\，而不是 ``pg_last_wal_receive_lsn()`` 返回的（实际上是刷新 LSN 的）值。``latest_end_lsn`` 指向源主机上的 WAL 刷新位置。对于 primary，它可以更好地计算回放延迟，因为存储在 DCS 中的值每 ``loop_wait`` 秒才更新一次。

- 避免与使用 ``failover=true`` 选项创建的槽产生交互（Alexander Kukushkin）

  此更改是让逻辑 failover 槽特性完全可用所必需的。

- 在 ``/metrics`` REST API 端点中添加 PostgreSQL 状态（Ivan Filianin）

  PostgreSQL 实例状态信息现在可通过 ``/metrics`` REST API 端点的 Prometheus 格式输出获得。


**改进**

- 降低 watchdog 配置失败的日志级别（Ants Aasma）

  除非 watchdog 配置为 ``required`` 模式，否则 ``Could not activate Linux watchdog device`` 日志行现在只在 debug 日志级别显示。之前它在 info 级别显示。

- 利用 ``pg_stat_wal_receiver`` 中的 ``written_lsn`` 和 ``latest_end_lsn`` （Alexander Kukushkin）

  现在优先使用实际写入 LSN ``written_lsn``\，而不是 ``pg_last_wal_receive_lsn()`` 返回的（实际上是刷新 LSN 的）值。``latest_end_lsn`` 指向源主机上的 WAL 刷新位置。对于 primary，它可以更好地计算回放延迟，因为存储在 DCS 中的值每 ``loop_wait`` 秒才更新一次。

- 避免与使用 ``failover=true`` 选项创建的槽产生交互（Alexander Kukushkin）

  此更改是让逻辑 failover 槽特性完全可用所必需的。

- 在 ``/metrics`` REST API 端点中添加 PostgreSQL 状态（Ivan Filianin）

  PostgreSQL 实例状态信息现在可通过 ``/metrics`` REST API 端点的 Prometheus 格式输出获得。


版本 4.0.7
----------

发布于 2025-09-22

**新特性**

- 添加对 PostgreSQL 18 RC1 的支持（Alexander Kukushkin）

  扩展了 GUC 的校验器规则。Patroni 现在可以正确处理新的后台 I/O worker。

**缺陷修复**

- 修复 Windows 上将 localhost 解析为 IPv6 时可能存在的问题（András Váczi）

  在 PostgreSQL 中配置 ``listen_addresses`` 时，使用 ``0.0.0.0`` 或 ``127.0.0.1`` 会将监听限制为仅 IPv4，排除 IPv6。然而，在典型的 Windows 系统上，``localhost`` 默认通常解析为 IPv6 地址 ``::1``\。为确保兼容性，Patroni 现在在 Windows 系统上配置 PostgreSQL 监听 ``127.0.0.1`` 而不是 ``localhost``\。

- 仅当 DCS 中存在 ``/config`` 键时才返回全局配置（Alexander Kukushkin）

  如果 DCS 中缺少 ``/config`` 键，Patroni REST API 之前会返回空配置而不是抛出错误。

- 修复 Etcd 不可用时 failsafe 模式未触发的问题（Alexander Kukushkin）

  Patroni 之前并不总能正确处理 ``etcd3`` 异常，导致 failsafe 模式无法触发。

- 修复信号处理器重入导致的死锁（Waynerv）

  在 Docker 容器中以 ``PID=1`` 运行的 Patroni 在某些特殊情况下收到 ``SIGCHLD`` 后会发生死锁。

- 当（永久）物理复制槽未保留 WAL 时重新创建它（Israel Barth Rubio）

  在 Patroni 管理范围之外创建且未保留 WAL 的永久物理复制槽会导致 ``replication slot cannot be advanced`` 错误。为避免此问题，Patroni 现在会重新创建此类槽。

- 正确处理 ``etcd3`` 的 watch 取消消息（Alexander Kukushkin）

  当 ``etcd3`` 向 watch 通道发送取消消息时，它不会关闭连接。这导致 Patroni 使用过期数据。Patroni 现在通过中断分块响应的读取循环并在 Patroni 侧关闭连接来解决此问题。

- 处理 ``HTTPConnection`` socket 被 ``pyopenssl`` 包装的情况（Alexander Kukushkin）

  Patroni 之前未能正确使用 ``python-etcd`` 强制要求的 ``pyopenssl`` 接口。

**文档改进**

- 改进 2 节点集群指南（Nikolay Samokhvalov）

  澄清 failover 期间的行为和 DCS 要求。


版本 4.0.6
----------

发布于 2025-06-06

**缺陷修复**

- 修复从更高优先级的 leader 进行 failover 时的缺陷（Alexander Kukushkin）

  确保当之前的 leader 报告与当前节点相同的 ``LSN`` 时，Patroni 忽略具有更高优先级的旧 leader。

- 修复在 ``PGDATA`` 之外创建的 ``postgresql.conf`` 文件的权限（Michael Banck）

  在 ``PGDATA`` 目录之外创建 ``postgresql.conf`` 文件时，遵循系统范围的 umask 值。

- 修复 ``synchronous_mode=quorum`` 下 switchover 的缺陷（Alexander Kukushkin）

  当指定了候选节点时，不检查 quorum 要求。

- 通过比较集群 term 来忽略过期的 Etcd 节点（Alexander Kukushkin）

  记住 Etcd 集群最后一次已知的 "raft_term"，并在执行客户端请求时与 Etcd 节点报告的 "raft_term" 进行比较。

- 在 ``SIGHUP`` 时更新 PostgreSQL 配置文件（Alexander Kukushkin）

  之前，只有当检测到全局或本地配置发生变化时，Patroni 才会替换 PostgreSQL 配置文件。

- 正确处理 ``etcd3`` 抛出的 ``Unavailable`` 异常（Alexander Kukushkin）

  Patroni 之前会在同一个 ``etcd3`` 节点上重试此类请求，而切换到另一个节点是更好的策略。

- 改进 ``etcd3`` lease 处理（Alexander Kukushkin）

  确保 Patroni 每个 HA 循环至少刷新一次 ``etcd3`` lease。

- 尝试获取 leader 锁时在 409 状态码上重新检查注解（Alexander Kukushkin）

  实现与 Patroni 4.0.3 版本中 leader 对象读取相同的处理行为。

- 推进槽时考虑 ``replay_lsn`` （Polina Bungina）

  不要在 replica 上推进超过 ``replay_lsn`` 的槽。此外，如果在 replica 上槽的位置已经超过其 ``confirmed_flush_lsn``\，但该 replica 尚未回放该槽在 primary 上的实际 ``LSN``\，则将槽推进到 ``replay_lsn`` 位置。

- 确保提升后执行 ``CHECKPOINT`` （Alexander Kukushkin）

  由于 ``CHECKPOINT`` 可能尚未完成，降级时 checkpoint 任务可能未被重置。这导致下一次提升被触发时使用了过期的 ``result``\。

- 避免并发执行 "offline" 降级（Alexander Kukushkin）

  在缓慢关闭的情况下，下一次心跳循环可能会再次命中 DCS 错误处理方法，导致出现 ``AsyncExecutor is busy, demoting from the main thread`` 警告并再次启动 offline 降级。

- 在初始化失败重命名数据目录之前规范化 ``data_dir`` 值（Waynerv）

  防止 ``data_dir`` 参数值中的尾部斜杠在初始化失败后破坏重命名过程。

- 检查 ``synchronous_standby_names`` 包含预期值（Alexander Kukushkin）

  之前，实现非 quorum 同步复制状态机的机制不检查 ``synchronous_standby_names`` 的实际值，导致当 ``pg_stat_replication`` 是 ``synchronous_standby_names`` 的子集时使用了过期的 ``synchronous_standby_names`` 值。


版本 4.0.5
----------

发布于 2025-02-20

**稳定性改进**

- 与 ``python-json-logger>=3.1`` 保持兼容（Alexander Kukushkin）

  消除旧 API 用法产生的警告。

- 与 Python 3.13 保持兼容（Alexander Kukushkin）

  针对 Python 3.13 运行测试。

- 与 ``pyinstaller>=4.4`` 保持兼容（Joe Jensen）

  如果 ``pyinstaller`` 的 ``toc`` 属性不存在，则回退到默认的 ``iter_modules``\。

- 修复 PostgreSQL 9.5 支持问题（Alexander Kukushkin）

  - 正确处理 ``pg_rewind`` 输出格式。
  - 考虑 ``synchronous_standby_names`` 格式不支持 "num" 规范的情况。

- 与 ``urlparse`` 的最新变更保持兼容（Alexander Kukushkin）

  ``urlparse`` 不再接受 URL 中包含带 ``[]`` 字符的多个主机。为缓解该问题，在可能的情况下切换到 ``libpq`` 中 ``PQconninfoParse()`` 的原生包装，仅对链接了旧版本 ``libpq`` 的较老 ``psycopg2`` 版本使用我们自己的实现。

**缺陷修复**

- 重启确认时仅显示需要重启的成员（András Váczi）

  之前，执行 ``patronictl restart <clustername> --pending`` 时，确认信息会列出所有成员，无论它们的重启是否处于 pending 状态。

- 在 Patroni 停止时取消长时间运行的作业，并在 replica bootstrap 失败时删除数据目录（Alexander Kukushkin）

  之前，Patroni 可能在执行 replica bootstrap，而 ``pg_basebackup``/ ``wal-g``/ ``pgBackRest``/ ``barman`` 或类似工具仍继续运行。

- 在 ``patronictl edit-config`` 中正确处理带斜杠的集群名称（Antoni Mur）

  将 ``cluster_name`` 中的正斜杠替换为下划线。

- 避免过早删除物理槽（Alexander Kukushkin）

  在 failover 后延迟移除包含 ``xmin`` 的物理复制槽：在新 primary 上，直到该成员被提升；在 replica 上，直到集群中存在 leader。

- 处理 ``controldata()`` 中子进程抛出的所有异常（Alexander Kukushkin）

  Patroni 之前未能正确处理调用 ``pg_controldata`` 工具时可能抛出的所有异常。

- 修复 failover 时未保留前 leader 槽位的缺陷（Alexander Kukushkin）

  避免错误地依赖成员存在于 DCS 中，因为 failover 时前 leader 的 ``/member`` 键恰好同时过期。

- 修复 quorum 状态机中的几个缺陷（Alexander Kukushkin）

  - 在评估是否存在健康节点参与 leader 竞争时，降级前需要考虑 quorum 要求。否则，前 leader 可能陷入被异步节点包围的恢复状态。
  - ``QuorumStateResolver`` 之前未正确处理 replica 节点快速加入又断开的情况。

**改进**

- 改进配置文件为空或非字典时的错误信息（Julian）

  在验证 Patroni 配置文件是否包含有效的 ``Mapping`` 对象时，抛出更明确的异常。


版本 4.0.4
----------

发布于 2024-11-22

**稳定性改进**

- 添加与 ``py-consul`` 模块的兼容性（Alexander Kukushkin）

  ``python-consul`` 模块长期无人维护，而 ``py-consul`` 是官方替代品。与 python-consul 的向后兼容性仍然保留。

- 添加与 ``prettytable>=3.12.0`` 模块的兼容性（Alexander Kukushkin）

  解决弃用警告。

- 与 ``ydiff==1.4.2`` 模块的兼容性（Alexander Kukushkin）

  修复最新版本的兼容性问题，在 ``requirements.txt`` 中约束版本，并引入最新版本兼容性测试。

**缺陷修复**

- 在失败的 primary 恢复后运行 ``on_role_change`` 回调（Polina Bungina、Alexander Kukushkin）

  对于崩溃后未能以 primary 启动的节点，额外运行 ``on_role_change`` 回调，以增加即使后续作为 replica 启动失败也能执行回调的机会。

- 修复 ``patronictl list -W`` 中的线程泄漏（Alexander Kukushkin）

  缓存 DCS 实例对象以避免线程泄漏。

- 确保只有受支持的参数才会被写入连接字符串（Alexander Kukushkin）

  Patroni 之前会把较新版本引入的参数传入连接字符串，导致连接错误。

版本 4.0.3
----------

发布于 2024-10-18

**缺陷修复**

- 创建用户时禁用 ``pgaudit`` 以免暴露密码（kviset）

  启用 ``pgaudit`` 扩展时，Patroni 在创建 ``superuser``\、``replication`` 和 ``rewind`` 用户时会记录其密码。

- 修复混合部署的问题：primary 运行 pre-Patroni v4、replica 运行 v4 以上版本（Alexander Kukushkin）

  如果 leader 上运行的 Patroni 版本低于 4.0.0，则使用从 ``/members`` 键提取的 ``xlog_location``\，而不是尝试从 ``/status`` 键获取成员的槽位置。否则会导致 replica 上的 WAL 不断累积。

- 不要忽略没有 Patroni 校验器的有效 PostgreSQL GUC（Polina Bungina）

  如果某个 GUC 没有 Patroni 校验器但实际上是有效的 GUC，仍然通过 ``postgres --describe-config`` 进行检查。

**改进**

- 在 K8s 中读取 leader 对象时，在 409 状态码上重新检查注解（Alexander Kukushkin）

  如果 ``PATCH`` 请求被 Patroni 取消，而该请求实际上已成功更新目标对象，则避免额外的更新。

- 添加对 ``sslnegotiation`` 客户端连接选项的支持（Alexander Kukushkin）

  ``sslnegotiation`` 是在最终的 PostgreSQL 17 版本中加入的。


版本 4.0.2
----------

发布于 2024-09-17

**缺陷修复**

- 在发现配置验证文件时处理异常（Alexander Kukushkin）

  跳过 Patroni 没有足够权限执行列表操作的目录。

- 确保非活跃的热物理复制槽不持有 ``xmin`` （Alexander Kukushkin、Polina Bungina）

  自 3.2.0 版本起，Patroni 会在 replica 上为所有成员创建物理复制槽，并使用 ``pg_replication_slot_advance()`` 函数定期推进它们。然而，如果由于某种原因启用了 ``hot_standby_feedback`` 且 primary 被降级为 replica，这些现在非活跃的槽会将 ``NOT NULL`` 的 ``xmin`` 值传回新的 primary。这导致 ``xmin`` 边界无法推进，vacuum 无法清理死元组。通过此修复，Patroni 会重新创建那些本应非活跃但具有 ``NOT NULL`` ``xmin`` 值的物理复制槽。

- 修复启动阶段的未处理 ``DCSError`` （Waynerv）

  在尝试检查节点名称的唯一性之前，先确保 DCS 连接可用。

- 查询 ``pg_settings`` 时显式包含 ``CMDLINE_OPTIONS`` GUC（Alexander Kukushkin）

  确保 Patroni 加入正在运行的 standby 时，所有作为命令行参数传递给 postmaster 的 GUC 都会被恢复。这是对 Patroni 3.2.2 中修复缺陷的后续改进。

- 修复 ``synchronous_standby_names`` 引用逻辑中的缺陷（Alexander Kukushkin）

  根据 PostgreSQL 文档，``ANY`` 和 ``FIRST`` 关键字应当用双引号引用，而 Patroni 之前没有这样做。

- 修复 keepalive 连接越界问题（hadizamani021）

  确保基于所设置 ``ttl`` 计算出的 ``keepalive`` 选项值不超过当前平台允许的最大值。

版本 4.0.1
----------

发布于 2024-08-30

**缺陷修复**

- Patroni 曾为自身创建多余的复制槽（Alexander Kukushkin）

  当 ``name`` 包含大写或特殊字符时会发生这种情况。


版本 4.0.0
----------

发布于 2024-08-29

.. warning::
   - 此版本完成了去除 "master" 术语、改用 "primary" 的工作。这意味着一些破坏性变更，请仔细阅读发布说明。只有当您运行的是 Patroni 3.1.0 或更新版本时，升级到 Patroni 4 以上版本才能可靠工作。从更旧的版本直接升级到 4 以上是可能的，但如果 primary 在其余节点运行其他 Patroni 版本时发生故障，可能会导致意外行为。


**破坏性变更**

- 在去除 Patroni 代码中非包容性的 "master" 术语时引入了以下破坏性变更：

  - 在 Kubernetes 上，Patroni 默认会将 ``role`` 标签设置为 ``primary``\。如果您希望保持旧行为并避免停机或冗长复杂的迁移，可以将参数 ``kubernetes.leader_label_value`` 和 ``kubernetes.standby_leader_label_value`` 配置为 ``master``\。更多信息请参见 :ref:`此处 <kubernetes_role_values>`。
  - Patroni 角色以 ``primary`` 而不是 ``master`` 写入 DCS。
  - Patroni REST API 返回的角色已从 ``master`` 改为 ``primary``\。
  - Patroni REST API 不再接受 ``/switchover``\、``/failover``\、``/restart`` 端点的请求中的 ``role=master``\。
  - ``/metrics`` REST API 端点将不再报告 ``patroni_master`` 指标。
  - ``patronictl`` 不再接受任何命令的 ``--master`` 选项。应改用 ``--leader`` 或 ``--primary`` 选项。
  - 自定义 replica 创建方法的声明式配置中的 ``no_master`` 选项不再被视为特殊选项，请改用 ``no_leader``\。
  - ``patroni_wale_restore`` 脚本不再接受 ``--no_master`` 选项。
  - ``patroni_barman`` 脚本不再接受 ``--role=master`` 选项。
  - 所有回调脚本都以 ``role=primary`` 选项执行，而非 ``role=master``\。

- ``patronictl failover`` 不再接受自 Patroni 3.2.0 起已弃用的 ``--leader`` 选项。

- 已移除自 Patroni 3.2.0 起弃用的用户创建功能（``bootstrap.users`` 配置节）。


**新特性**

- 基于 quorum 的 failover（Ants Aasma、Alexander Kukushkin）

  该特性实现了基于 quorum 的同步复制（自 PostgreSQL v10 起可用），有助于降低最坏情况下的延迟，即使在正常运行期间也是如此，因为向一个 standby 复制的高延迟可以由其他 standby 补偿。Patroni 实现了额外的保护措施，通过根据已接收的最新事务选择 failover 候选节点，来防止任何用户可见的数据丢失。

- 在 ``pg_dist_node`` 中注册 Citus secondary（Alexander Kukushkin）

  Patroni 现在维护 ``pg_dist_node`` 中 ``role==replica``\、``state==running`` 且不带 ``noloadbalance`` :ref:`标签 <tags_settings>` 的节点列表。

- 成员复制槽的可配置保留期（Alexander Kukushkin）

  实现对 ``member_slots_ttl`` 全局配置参数的支持，该参数控制成员键不存在时成员复制槽应保留多长时间。

- 使 Patroni 创建的日志文件的权限可配置（Alexander Kukushkin）

  允许为 Patroni 创建的日志文件设置特定权限。如果未指定，则根据当前的 ``umask`` 值设置权限。

- 与 PostgreSQL 17 beta3 的兼容性（Alexander Kukushkin）

  扩展了 GUC 的校验器规则。Patroni 会在关闭时处理所有新的辅助后台进程，并在 ``primary_conninfo`` 中设置 ``dbname``\，因为逻辑复制槽同步需要它。

- 为 Patroni 配置验证实现 ``--ignore-listen-port`` 选项（Sahil Naphade）

  使得运行 ``patroni --validate-config`` 时可以忽略已绑定的端口。


**改进**

- 使 ``wal_log_hints`` 可配置（Paul_Kim）

  当 ``use_pg_rewind`` 设置为 ``off`` 时，允许避免启用 ``wal_log_hints`` 配置带来的开销。

- 在 ``DEBUG`` 级别记录 ``pg_basebackup`` 命令（Waynerv）

  便于调试初始化失败。


**缺陷修复**

- 在 failsafe 模式下为级联节点推进永久槽（Alexander Kukushkin）

  确保激活 failsafe 模式时，级联 replica 的槽在 primary 上得到正确推进。这是通过在 ``POST /failsafe`` REST API 请求的 replica 响应中扩展其 ``xlog_location`` 来实现的。

- 不要让当前节点被选为同步节点（Alexander Kukushkin）

  可能有 "某些东西" 正以与当前 primary 名称匹配的 ``application_name`` 从当前 primary 节点流式复制。Patroni 之前未能正确处理这种情况，可能导致 primary 被声明为同步节点，从而阻塞 switchover。

- 对 ``POST /failsafe`` 忽略 ``restapi.allowlist_include_members`` （Alexander Kukushkin）

- 改进 GUC 验证（Polina Bungina）

  由于需要通过运行 ``postgres --describe-config`` 命令进行额外验证，之前无法通过 Patroni 配置设置其中未列出的 GUC。这一限制现已移除。

- 检测到 unix socket 时向 ``.pgpass`` 文件添加包含 ``localhost`` 的行（Alexander Kukushkin）

  如果指定的 ``host`` 参数以 ``/`` 字符开头，Patroni 将向 ``.pgpass`` 文件添加额外一行。这样可以覆盖 ``host`` 与默认 socket 目录路径匹配的边界情况。

- 修复日志记录问题（Waynerv）

  在 failsafe 处理日志中定义了正确的请求 URL，并修复了 postmaster 检查日志中的时间戳顺序。


版本 3.3.2
----------

发布于 2024-07-11

**缺陷修复**

- 修复普通 Postgres 同步复制模式（Israel Barth Rubio）

  自从 Patroni 引入 ``synchronous_mode`` 以来，普通 Postgres 同步复制一直无法正常工作。通过此缺陷修复，当 ``synchronous_mode`` 被禁用时，Patroni 会按用户配置的值设置 ``synchronous_standby_names`` （如果用户确实配置了的话）。

- 处理 standby 上逻辑槽的失效（Polina Bungina）

  自 PG16 起，standby 上的逻辑复制槽可能因边界（horizon）而失效：从现在起，Patroni 会强制复制（即重新创建）失效的槽。

- 修复逻辑槽推进与复制之间的竞态条件（Alexander Kukushkin）

  由于此缺陷，可能出现失效的逻辑复制槽在 PostgreSQL 重启时被复制多次的情况。

版本 3.3.1
----------

发布于 2024-06-17

**稳定性改进**

- 与 Python 3.12 的兼容性（Alexander Kukushkin）

  处理 ``logging.LogRecord`` 新增的属性。

**缺陷修复**

- 修复 ``replicatefrom`` 标签处理中的无限递归（Alexander Kukushkin）

  作为此修复的一部分，还改进了 ``is_physical_slot()`` 检查并调整了文档。

- 修复 standby 集群中角色报告错误的问题（Alexander Kukushkin）

  ``synchronous_standby_names`` 和同步复制只在真正的 primary 节点上工作，在级联复制的情况下会被 Postgres 直接忽略。在此修复之前，``patronictl list`` 和 ``GET /cluster`` 会错误地将某些节点报告为同步节点。

- 修复 ``allow_in_place_tablespaces`` GUC 的可用性（Polina Bungina）

  ``allow_in_place_tablespaces`` 不仅被添加到 PostgreSQL 15 中，还反向移植到了 PostgreSQL 10-14。

版本 3.3.0
----------

发布于 2024-04-04

.. warning::
   所有较旧的 Partoni 版本均与 ``ydiff>=1.3`` 不兼容。

   有以下几种可用于"修复"该问题的方案：

   1. 将 Patroni 升级到最新版本
   2. 安装 Patroni 后安装 ``ydiff<1.3``
   3. 安装 ``cdiff`` 模块


**新特性**

- 添加向 Zookeeper 客户端传递 ``auth_data`` 的能力（Aras Mumcuyan）

  它允许指定连接所使用的认证凭据。

- 添加用于 ``Barman`` 集成的 contrib 脚本（Israel Barth Rubio）

  提供一个应用程序 ``patroni_barman``\，允许远程执行 ``Barman`` 操作，可以用作自定义 bootstrap/自定义 replica 方法或作为 ``on_role_change`` 回调。更多信息请查看 :ref:`此处 <tools_integration>`。

- 支持 ``JSON`` 日志格式（alisalemmi）

  除了 ``plain``\（默认）之外，Patroni 现在还支持 ``json`` 日志格式。需要安装 ``python-json-logger>=2.0.2`` 库。

- 显示 ``pending_restart_reason`` 信息（Polina Bungina）

  提供导致设置 ``pending_restart`` 标志的 PostgreSQL 参数的扩展信息。``patronictl list`` 和 ``/patroni`` REST API 端点现在都会以 ``pending_restart_reason`` 的形式显示参数名称及其 "diff"。

- 实现 ``nostream`` 标签（Grigory Smolkin）

  如果将 ``nostream`` 标签设置为 ``true``\，该节点将不使用复制协议流式传输 WAL，而是依赖归档恢复（如果配置了 ``restore_command``\）。它还会禁用该节点自身及其所有级联 replica 上永久逻辑复制槽的复制和同步。

**改进**

- 实现对 ``log`` 配置节的验证（Alexander Kukushkin）

  在此之前，校验器不会检查所提供的日志配置的正确性。

- 改进 PostgreSQL 参数变更的日志记录（Polina Bungina）

  将旧值转换为人类可读的格式，并记录 ``pg_controldata`` 与 Patroni 全局配置不匹配的信息。

**缺陷修复**

- 正确过滤不被允许的 ``pg_basebackup`` 选项（Israel Barth Rubio）

  由于缺陷，当以 ``- setting: value`` 格式提供配置时，Patroni 未能正确过滤掉为 ``basebackup`` replica bootstrap 方法配置的不允许选项。

- 修复 ``etcd3`` 认证错误处理（Alexander Kukushkin）

  如果在执行请求前没有刚进行过认证，那么在 ``etcd3`` 认证错误时始终重试一次。此外，不要在重新认证时重启 watcher。

- 改进校验器文件的发现逻辑（Waynerv）

  在可能的情况下（Python 3.9 以上）使用 ``importlib`` 库来发现包含可用配置参数的文件。此实现更稳定，并且不会破坏基于 ``zip`` 归档的 Patroni 发行版。

- 仅当 ``standby_cluster`` 配置节中指定了多个主机时才使用 ``target_session_attrs`` （Alexander Kukushkin）

  仅当 ``standby_cluster.host`` 配置节包含多个以逗号分隔的主机时，才在 standby leader 节点的 ``primary_conninfo`` 中添加 ``target_session_attrs=read-write``\。

- 添加与 ``ydiff`` 库 1.3 以上版本的兼容性代码（Alexander Kukushkin）

  Patroni 依赖 ``ydiff`` 的某些非公开 API，因为 ``ydiff`` 本应是终端工具而非 python 模块。遗憾的是，1.3 中的 API 变更破坏了旧版本的 Patroni。


版本 3.2.2
----------

发布于 2024-01-17

**缺陷修复**

- DCS 被清空时，不要让 replica restore 初始化键（Alexander Kukushkin）

  这个问题发生在 Patroni 应该接管独立 PG 集群的方法中。

- 从 Consul 获取刚更新的 sync 键时使用一致性读取（Alexander Kukushkin）

  Consul 不提供任何接口来立即获取我们刚更新的键的 ``ModifyIndex``\，因此我们必须执行一次显式的读操作。由于默认允许过期读取，我们有时会得到键的旧版本。

- 如果需要重启的参数被重置为原始值，则重载 Postgres 配置（Polina Bungina）

  之前 Patroni 不会更新配置，只会重置 ``pending_restart``\。

- 修复同步模式下 failover 到异步候选节点时确认提示消息的错误反转逻辑（Polina Bungina）

  该问题只存在于 ``patronictl`` 中。

- 在 ``patronictl`` 中将 leader 从 failover 候选中排除（Polina Bungina）

  如果集群是健康的，failover 到现有 leader 是没有意义的操作。

- 幂等地创建 Citus 数据库和扩展（Alexander Kukushkin、Zhao Junwang）

  这样在需要为 Citus 数据库添加更多依赖时，可以在 ``post_bootstrap`` 脚本中创建它们。

- 不要过滤矛盾的 ``nofailover`` 标签（Polina Bungina）

  节点上配置的 ``{nofailover: false, failover_priority: 0}`` 不允许它参与竞争，而实际上它应该参与，因为 ``nofailover`` 标签应优先考虑。

- 修复 PyInstaller 冻结问题（Sophia Ruan）

  ``freeze_support()`` 在 ``argparse`` 之后被调用，导致 Patroni 无法启动 Postgres。

- 修复 ``patronictl`` 和 ``Citus`` 配置的配置生成器缺陷（Israel Barth Rubio）

  该缺陷导致通过环境变量设置的 ``patronictl`` 和 ``Citus`` 配置参数无法写入生成的配置。

- 加入正在运行的 standby 时恢复 recovery GUC 和某些 Patroni 管理的参数（Alexander Kukushkin）

  Patroni 之前因内部某个结构中缺少 ``port`` 而无法重启 Postgres v12 及更新版本。

- 围绕 ``pending_restart`` 标志的修复（Polina Bungina）

  当使用 ``recovery_target_action = promote`` 进行自定义 bootstrap 时，或当有人使用例如 ``ALTER SYSTEM`` 更改了 ``hot_standby`` 或 ``wal_log_hints`` 时，不暴露 ``pending_restart``\。

版本 3.2.1
----------

发布于 2023-11-30

**缺陷修复**

- 限制 ``patronictl`` 中 ``--format`` 参数的接受值（Alexander Kukushkin）

  之前它接受任意字符串，如果值无法识别则不产生任何输出。

- 在释放 leader 键之前，验证 replica 节点在关闭时已收到 checkpoint LSN（Alexander Kukushkin）

  之前在某些情况下，我们使用的是 SWITCH 记录（其后跟有 CHECKPOINT）的 LSN（如果启用了归档模式）。结果，旧 primary 有时必须执行 ``pg_rewind``\，但这不会导致数据丢失。

- 执行节点名称唯一性检查时发出真实的 HTTP 请求（Alexander Kukushkin）

  在容器中运行 Patroni 时，流量可能通过 ``docker-proxy`` 路由，它会监听端口并接受传入连接。这会导致误报。

- 修复 Etcd v2 下的 Citus 支持（Alexander Kukushkin）

  Patroni 之前无法使用 Etcd v2 部署新的 Citus 集群。

- 修复 Postgres v16 以上版本的 ``pg_rewind`` 行为（Alexander Kukushkin）

  ``pg_waldump`` 的错误消息格式在 v16 中发生了变化，导致即使不需要，Patroni 也会调用 ``pg_rewind``\。

- 修复自定义 bootstrap 的缺陷（Alexander Kukushkin）

  Patroni 之前错误地应用了 ``--command`` 参数，而该参数本身就是 bootstrap 命令。

- 修复 REST API 健康检查端点的问题（Sophia Ruan）

  之前 Postgres 重启后，由于连接未正确关闭，可能会返回 ``unknown`` 状态。

- 缓存 ``postgres --describe-config`` 输出结果（Waynerv）

  这些结果用于确定哪些 GUC 可用于验证 PostgreSQL 配置，我们不希望在 Patroni 运行期间该列表发生变化。


版本 3.2.0
----------

发布于 2023-10-25

**弃用说明**

- ``bootstrap.users`` 支持将在 4.0.0 版本中移除。如果您需要在部署新集群后创建用户，请使用 ``bootstrap.post_bootstrap`` 钩子来完成。


**破坏性变更**

- 强制 ``loop_wait + 2*retry_timeout <= ttl`` 规则并硬编码最小可能值（Alexander Kukushkin）

  最小值：``loop_wait=2``\、``retry_timeout=3``\、``ttl=20``\。如果值更小或违反规则，它们会被调整，并向 Patroni 日志写入警告。


**新特性**

- Failover 优先级（Mark Pekala）

  借助 ``tags.failover_priority``\，现在可以在 leader 竞争中使某个节点更受青睐。更多细节请参阅文档（ref tags）。

- 实现 ``patroni --generate-config [--dsn DSN]`` 和 ``patroni --generate-sample-config`` （Polina Bungina）

  它允许为正在运行的 PostgreSQL 集群生成配置文件，或为新 Patroni 集群生成示例配置文件。

- 使用专用连接让 Patroni REST API 连接到 Postgres（Alexander Kukushkin）

  这有助于在系统压力较大时避免阻塞主心跳循环。

- 用节点 ``name`` 丰富某些端点（sskserk）

  对于监控端点，在 ``scope`` 旁边添加 ``name``\；对于 metrics 端点，将 ``name`` 添加到标签中。

- 确保 failover/switchover 的严格区分（Polina Bungina）

  在日志消息中更加精确，并允许在健康的同步集群中 failover 到异步节点。

- 让永久物理复制槽的行为与永久逻辑槽类似（Alexander Kukushkin）

  在允许成为 leader 的所有节点上创建永久物理复制槽，并使用 ``pg_replication_slot_advance()`` 函数推进 standby 节点上槽的 ``restart_lsn``\。

- 添加在 ``patronictl`` 中通过 ``--dcs`` 参数指定 namespace 的能力（Israel Barth Rubio）

  当 ``patronictl`` 在没有配置文件的情况下使用时，这会很方便。

- 添加自定义 bootstrap 配置中附加参数的支持（Israel Barth Rubio）

  之前只能向 ``command`` 添加自定义参数，现在可以将它们列为映射。


**改进**

- 将 ``citus.local_hostname`` GUC 设置为与 Patroni 连接 Postgres 时使用的值相同（Alexander Kukushkin）

  有些情况下 Citus 想要与本地 Postgres 建立连接。默认情况下它使用 ``localhost``\，但这并不总是可用。


**缺陷修复**

- 在 standby 集群中忽略 ``synchronous_mode`` 设置（Polina Bungina）

  Postgres 不支持级联同步复制，不忽略 ``synchronous_mode`` 会破坏 standby 集群中的 switchover。

- 为 ``on_reload`` 回调处理 SIGCHLD（Alexander Kukushkin）

  不这样做会导致僵尸进程，只有在下一次 ``on_reload`` 执行时才会被回收。

- 处理 Etcd v3 工作中的 ``AuthOldRevision`` 错误（Alexander Kukushkin、Kenny Do）

  当 Etcd 配置为使用 JWT 且 Etcd 中的用户数据库被更新时会抛出该错误。

版本 3.1.2
----------

发布于 2023-09-26

**缺陷修复**

- 修复 ``wal_keep_size`` 检查的缺陷（Alexander Kukushkin）

  ``wal_keep_size`` 是通常带有单位的 GUC，Patroni 之前无法将其值转换为 ``int``\。结果，``bootstrap.dcs`` 的值之后没有写入 ``/config`` 键。

- 检测并解决 ``/sync`` 键与 ``synchronous_standby_names`` 之间的不一致（Alexander Kukushkin）

  通常，Patroni 以非常特定的顺序更新 ``/sync`` 和 ``synchronous_standby_names``\，但在出现缺陷或有人手动重置 ``synchronous_standby_names`` 时，Patroni 会进入不一致状态。结果可能发生 failover 到异步节点的情况。

- 加入正在运行的 Postgres 时读取 GUC 的值（Alexander Kukushkin）

  在 ``pause`` 状态下重启时，Patroni 之前会丢弃 ``postgresql.conf`` 中的 ``synchronous_standby_names`` GUC。为解决此问题并避免类似问题，Patroni 在加入已在运行的 Postgres 时会读取 GUC 的值。

- 检查节点唯一性时静默烦人的警告（Alexander Kukushkin）

  如果 Patroni 快速重启，``urllib3`` 会产生 ``WARNING`` 消息。

版本 3.1.1
----------

发布于 2023-09-20

**缺陷修复**

- 在提升时重置 failsafe 状态（ChenChangAo）

  如果在 failsafe 模式激活后不久发生 switchover/failover，新提升的 primary 会在 failsafe 变为非活跃后降级自己。

- 静默 ``patronictl`` 中无用的警告（Alexander Kukushkin）

  如果 ``patronictl`` 使用与 Patroni 相同的 patroni.yaml 文件并且可以访问 ``PGDATA`` 目录，它可能会显示有关全局配置中错误值的烦人警告。

- 针对一个边界情况显式启用同步模式（Alexander Kukushkin）

  如果没有 replica 从 primary 流式复制，同步模式实际上从未被激活。

- 修复 ``0`` 整数值验证的缺陷（Israel Barth Rubio）

  在大多数情况下，它不会引起任何问题，只是警告。

- 不为 standby 集群返回逻辑槽（Alexander Kukushkin）

  Patroni 无法在 standby 集群中创建逻辑复制槽，因此如果在全局配置中定义了它们，应被忽略。

- 避免在 ``patronictl --help`` 输出中显示 docstring（Israel Barth Rubio）

  ``click`` 模块需要为此获得特殊提示。

- 修复 ``kubernetes.standby_leader_label_value`` 的缺陷（Alexander Kukushkin）

  该特性实际上从未生效。

- 将集群系统标识符恢复到 ``patronictl list`` 输出中（Polina Bungina）

  该问题是在实现 Citus 支持时引入的，因为协调器和所有 worker 的标识符不同，我们需要隐藏它。

- 在 Kubernetes 实现中覆盖 ``write_leader_optime`` 方法（Alexander Kukushkin）

  当没有健康的 replica 可成为新的 primary 时，该方法应把关闭 LSN 写入 leader Endpoint/ConfigMap。

- 在 pause 模式下不启动已停止的 postgres（Alexander Kukushkin）

  由于竞态条件，Patroni 之前错误地认为 standby 应该重启，因为某些恢复参数（``primary_conninfo`` 或类似参数）发生了变化。

- 修复 ``patronictl query`` 命令的缺陷（Israel Barth Rubio）

  当只提供 ``-m`` 参数，或 ``-r`` 和 ``-m`` 都未提供时，它无法工作。

- 正确处理用于启动 postgres 命令行中的整型参数（Polina Bungina）

  如果值以字符串形式提供而没有转换为整数，会导致基于 ``max_connections`` 计算 ``max_prepared_transactions`` 时出错（针对 Citus 集群）。

- 决定是否 ``pg_rewind`` 时不要依赖 ``pg_stat_wal_receiver`` （Alexander Kukushkin）

  可能发生 ``pg_stat_wal_receiver`` 报告的 ``received_tli`` 领先于实际回放时间线的情况，而通过复制连接由 ``DENTIFY_SYSTEM`` 报告的时间线始终是正确的。


版本 3.1.0
----------

发布于 2023-08-03

**破坏性变更**

- 更改 ``restapi.keyfile`` 和 ``restapi.certfile`` 的语义（Alexander Kukushkin）

  之前，Patroni 将 ``restapi.keyfile`` 和 ``restapi.certfile`` 用作客户端证书，作为 ``ctl`` 配置节中没有相应配置参数时的回退方案。

.. warning::
    如果您启用了客户端证书验证（``restapi.verify_client`` 设置为 ``required``\），则**必须**\在 ``ctl.certfile``\、``ctl.keyfile``\、``ctl.keyfile_password`` 中提供**有效的客户端证书**\。如果未提供，Patroni 将无法正常工作。


**新特性**

- 使 Pod 角色标签可配置（Waynerv）

  可以使用 ``kubernetes.leader_label_value``\、``kubernetes.follower_label_value`` 和 ``kubernetes.standby_leader_label_value`` 参数自定义值。当我们把 ``master`` 角色改为 ``primary`` 时，该特性将非常有用。您可以在 :ref:`此处 <kubernetes_role_values>` 了解更多关于该特性和迁移步骤的信息。


**改进**

- ``patroni --validate-config`` 的各种改进（Alexander Kukushkin）

  改进了不同 DCS、``bootstrap.dcs``\、``ctl``\、``restapi`` 和 ``watchdog`` 配置节的参数验证。

- 如果 Postgres 在 Patroni 运行期间于恢复过程中崩溃，则以非恢复状态启动 Postgres（Alexander Kukushkin）

  这可以减少恢复时间，并有助于防止不必要的时间线递增。

- 避免对 ``/status`` 键进行不必要的更新（Alexander Kukushkin）

  当没有永久逻辑槽时，即使 primary 上的 LSN 没有前进，Patroni 也会在每个心跳循环更新 ``/status``\。

- 不允许过期的 primary 赢得 leader 竞争（Alexander Kukushkin）

  如果 Patroni 因资源不足而长时间挂起，它会在获取 leader 锁之前额外检查是否有其他节点已经提升了 Postgres。

- 实现某些 PostgreSQL 参数验证的可见性（Alexander Kukushkin、Feike Steenbergen）

  如果 ``max_connections``\、``max_wal_senders``\、``max_prepared_transactions``\、``max_locks_per_transaction``\、``max_replication_slots`` 或 ``max_worker_processes`` 的验证失败，Patroni 之前会使用某个合理的默认值。现在除此之外还会显示警告。

- 为 ``PGDATA`` 中创建的文件和目录设置权限（Alexander Kukushkin）

  Patroni 创建的所有文件只有属主读写权限。这种行为会破坏在不同用户下运行并依赖组读权限的备份工具。现在 Patroni 遵循 ``PGDATA`` 上的权限，并正确设置其在 ``PGDATA`` 内创建的所有目录和文件的权限。


**缺陷修复**

- 通过 shell 运行 ``archive_command`` （Waynerv）

  Patroni 可能在以单用户模式进行崩溃恢复之前或 ``pg_rewind`` 之前归档一些 WAL 段。如果 archive_command 包含某些 shell 运算符（如 ``&&``\），它之前无法与 Patroni 一起正常工作。

- 修复 "switchover 时" 的关闭检查（Polina Bungina）

  之前可能出现指定候选节点仍在流式复制且未收到关闭检查，但因为其他某些节点健康，leader 键被移除的情况。

- 修复 "is primary" 检查（Alexander Kukushkin）

  在 leader 竞争期间，replica 无法识别旧 leader 上的 Postgres 仍在作为 primary 运行。

- 修复 ``patronictl list`` （Alexander Kukushkin）

  ``tsv``\、``json`` 和 ``yaml`` 输出格式中缺少集群名称字段。

- 修复 pause 之后的 ``pg_rewind`` 行为（Alexander Kukushkin）

  在某些条件下，从维护模式退出后，Patroni 无法使用 ``pg_rewind`` 将假 primary 重新加入集群。

- 修复 Etcd v3 实现中的缺陷（Alexander Kukushkin）

  如果由于 revision 不匹配，使用 ``create_revision``/``mod_revision`` 字段执行键更新，则使内部 KV 缓存失效。

- 修复 pause 状态下 standby 集群中 replica 的行为（Alexander Kukushkin）

  当 leader 键过期时，standby 集群中的 replica 不会跟随远程节点，而是保持 ``primary_conninfo`` 不变。

版本 3.0.4
----------

发布于 2023-07-13

**新特性**

- 使 standby 节点的复制状态可见（Alexander Kukushkin）

  对于 PostgreSQL 9.6 以上版本，当 standby 从其他节点流式复制时，Patroni 会将复制状态报告为 ``streaming``\；当没有复制连接且设置了 ``restore_command`` 时，报告为 ``in archive recovery``\。该状态在 DCS 中的 ``member`` 键、REST API 和 ``patronictl list`` 输出中可见。


**改进**

- 改进 Etcd v3 的错误消息（Alexander Kukushkin）

  当 Etcd v3 集群不可访问时，Patroni 之前报告无法访问 ``/v2`` 端点。

- 在 ``patronictl`` 中尽可能使用 quorum 读取（Alexander Kukushkin）

  Etcd 或 Consul 集群可能已降级为只读，但从 ``patronictl`` 的角度看一切正常。现在它会以错误失败。

- 防止配置中重复名称导致的分脑（Mark Pekala）

  启动时 Patroni 会检查 DCS 中是否注册了同名节点，并尝试查询其 REST API。如果 REST API 可访问，Patroni 会以错误退出。这有助于防止人为错误。

- 如果 Postgres 在 Patroni 运行期间于恢复过程中崩溃，则以非恢复状态启动 Postgres（Alexander Kukushkin）

  这可以减少恢复时间，并有助于防止不必要的时间线递增。


**缺陷修复**

- 收到 SIGHUP 时 REST API SSL 证书未被重新加载（Israel Barth Rubio）

  回归在 3.0.3 中引入。

- 修复 ``max_connections`` 等参数的整型 GUC 验证（Feike Steenbergen）

  Patroni 之前不喜欢带引号的数值。回归在 3.0.3 中引入。

- 修复 ``synchronous_mode`` 的问题（Alexander Kukushkin）

  以 ``synchronous_commit=off`` 执行 ``txid_current()``\，以便在启用 ``synchronous_mode_strict`` 时不会意外等待不存在的同步 standby。


版本 3.0.3
----------

发布于 2023-06-22

**新特性**

- 与 PostgreSQL 16 beta1 的兼容性（Alexander Kukushkin）

  扩展了 GUC 的校验器规则。

- 使 PostgreSQL GUC 校验器可扩展（Israel Barth Rubio）

  校验器规则从位于 ``patroni/postgresql/available_parameters/`` 目录下的 YAML 文件中加载。文件按字母顺序排序并逐个应用。这使得非标准 Postgres 发行版可以拥有自定义校验器。

- 添加 ``restapi.request_queue_size`` 选项（Andrey Zhidenkov、Aleksei Sukhov）

  设置 Patroni REST API 使用的 TCP socket 的请求队列大小。一旦队列满，后续请求会收到 "Connection denied" 错误。默认值为 5。

- 初始化新集群时直接调用 ``initdb`` （Matt Baker）

  之前通过 ``pg_ctl`` 调用，这要求对传递给 ``initdb`` 的参数进行特殊引用处理。

- 添加 before stop 钩子（Le Duane）

  该钩子可通过 ``postgresql.before_stop`` 配置，并在 ``pg_ctl stop`` 之前立即执行。退出码不影响关闭过程。

- 添加自定义 Postgres 二进制名称的支持（Israel Barth Rubio、Polina Bungina）

  使用自定义 Postgres 发行版时，Postgres 二进制文件可能使用与社区 Postgres 发行版不同的名称编译。自定义二进制名称可通过 ``postgresql.bin_name.*`` 和 ``PATRONI_POSTGRESQL_BIN_*`` 环境变量配置。


**改进**

- ``patroni --validate-config`` 的各种改进（Polina Bungina）

  - 使 ``bootstrap.initdb`` 可选。它只对新集群是必需的，但之前如果配置中缺少它，``patroni --validate-config`` 会报错。
  - 当 ``postgresql.bin_dir`` 为空或未设置时不报错。先尝试在默认 PATH 中查找 Postgres 二进制文件。
  - 使 ``postgresql.authentication.rewind`` 配置节可选。如果缺少，Patroni 使用超级用户。

- 改进 ``patronictl`` 中的错误报告（Israel Barth Rubio）

  之前 ``\n`` 符号按原样渲染，而不是实际的换行符。


**缺陷修复**

- 修复 Citus 支持中的问题（Alexander Kukushkin）

  如果在 switchover 期间，已提升 worker 对协调器的 REST API 调用失败，会使给定的 Citus 组无限期处于阻塞状态。

- 允许在 ``patronictl`` 的 ``--dcs-url`` 选项中使用 `etcd3` URL（Israel Barth Rubio）

  如果用户尝试通过 ``patronictl`` 的 ``--dcs-url`` 选项传递 `etcd3` URL，之前会遇到异常。

版本 3.0.2
----------

发布于 2023-03-24

.. warning::
    版本 3.0.2 放弃了对 Python 3.6 以下旧版本的支持。


**新特性**

- 在 ``/metrics`` 端点中添加同步 standby replica 状态（Thomas von Dein、Alexander Kukushkin）

  之前只报告 ``primary``/``standby_leader``/``replica``\。

- ``patronictl`` 中用户友好的 ``PAGER`` 处理（Israel Barth Rubio）

  现在可以通过 ``PAGER`` 环境变量配置分页器，它会覆盖默认的 ``less`` 和 ``more``\。

- 使 K8s 可重试 HTTP 状态码可配置（Alexander Kukushkin）

  在某些托管平台上，可能会得到 ``401 Unauthorized`` 状态码，有时经过几次重试后会得到解决。


**改进**

- 仅当 ``recovery_target_action`` 设置为 ``promote`` 时，在自定义 bootstrap 期间将 ``hot_standby`` 设置为 ``off`` （Alexander Kukushkin）

  这是使 ``recovery_target_action=pause`` 正常工作所必需的。

- 不允许 ``on_reload`` 回调杀死其他回调（Alexander Kukushkin）

  ``on_start``/``on_stop``/``on_role_change`` 通常用于添加/移除虚拟 IP，``on_reload`` 不应干扰它们。

- 在 aws 回调示例脚本中改用 ``IMDSFetcher`` （Polina Bungina）

  ``IMDSv2`` 需要 token 才能工作，而 ``IMDSFetcher`` 可以透明地处理。


**缺陷修复**

- 修复运行在 Kubernetes 上的 Citus 集群的 ``patronictl switchover`` （Lukáš Lalinský）

  对于 ``default`` 之外的 namespace，它之前无法工作。

- 如果不知道主版本，则不向 ``PGDATA`` 写入（Alexander Kukushkin）

  如果启动后 ``PGDATA`` 为空（可能尚未挂载），Patroni 之前会对 PostgreSQL 版本做出错误假设，即使实际主版本是 v10 以上，也会错误地创建 ``recovery.conf`` 文件。

- 修复协调器 failover 后 Citus 元数据的缺陷（Alexander Kukushkin）

  ``citus_set_coordinator_host()`` 调用不会引起元数据同步，而且该更改在 worker 节点上不可见。通过改用 ``citus_update_node()`` 解决了该问题。

- 当所有 etcd 节点"失败"时，使用配置文件中列出的 etcd 主机作为回退（Alexander Kukushkin）

  etcd 集群的拓扑可能随时间变化，Patroni 会尝试跟随它。如果在某个时刻所有节点都无法访问，Patroni 会在尝试重新连接时使用配置中的节点与最后一次已知拓扑的组合。

版本 3.0.1
----------

发布于 2023-02-16

**缺陷修复**

- 向 ``on_role_change`` 回调脚本传递正确的角色名称（Alexander Kukushkin、Polina Bungina）

  Patroni 之前在提升时错误地向 ``on_role_change`` 回调脚本传递 ``promoted`` 角色。传递的角色名称已改回 ``master``\。此回归在 3.0.0 中引入。


版本 3.0.0
----------

发布于 2023-01-30

此版本增加了与 `Citus <https://www.citusdata.com>`__ 的集成，并使得在临时 DCS 故障期间无需降级 primary 即可存活。

.. warning::
   - 3.0.0 是支持 Python 2.7 的最后一个版本。即将发布的版本将放弃对 Python 3.7 以下旧版本的支持。

   - RAFT 支持已弃用。我们会尽最大努力维护它，但对可能出现的问题不承担任何保证或责任。

   - 此版本是去除 "master"、改用 "primary" 的第一步。只有您运行至少 3.0.0 版本时，升级到下一个主版本才能可靠工作。


**新特性**

- DCS failsafe 模式（Alexander Kukushkin、Polina Bungina）

  如果启用该特性，Patroni 集群将能在临时 DCS 故障期间存活。您可以在 :ref:`文档 <dcs_failsafe_mode>` 中找到更多细节。

- Citus 支持（Alexander Kukushkin、Polina Bungina、Jelte Fennema）

  Patroni 支持轻松部署和管理具有 HA 的 `Citus <https://www.citusdata.com>`__ 集群。请查看 :ref:`此处 <citus>` 页面了解更多信息。


**改进**

- 删除未知但活跃的复制槽时抑制重复错误（Michael Banck）

  Patroni 仍会写入这些日志，但只在 DEBUG 级别。

- 每个 HA 循环只运行一次监控查询（Alexander Kukushkin）

  如果启用了同步复制，之前则不是这样。

- 只保留最新失败的数据目录（William Albertus Dembo）

  如果 bootstrap 失败，Patroni 之前会以时间戳后缀重命名 $PGDATA 文件夹。从现在起，后缀将是 ``.failed``\，如果此类文件夹已存在，会在重命名前将其移除。

- 改进同步复制连接的检查（Alexander Kukushkin）

  当新主机被添加到 ``synchronous_standby_names`` 时，只有它赶上 primary 且 ``pg_stat_replication.sync_state = 'sync'`` 时，才会在 DCS 中被设置为同步。


**移除的功能**

- 移除 ``patronictl scaffold`` （Alexander Kukushkin）

  保留它的唯一原因是运行 standby 集群的一种 hacky 方式。


版本 2.1.7
----------

发布于 2023-01-04

**缺陷修复**

- 修复与旧版 python 模块的小型不兼容问题（Alexander Kukushkin）

  它们阻止了在 Debian buster/Ubuntu bionic 上构建/运行 Patroni。

版本 2.1.6
----------

发布于 2022-12-30

**改进**

- 修复 ssl socket 关闭时恼人的异常（Alexander Kukushkin）

  HAProxy 一旦收到 HTTP 状态码就会关闭连接，不给 Patroni 正确关闭 SSL 连接的时间。

- 为 arm64 调整示例 Dockerfile（Polina Bungina）

  移除显式的 ``amd64`` 和 ``x86_64``\，不要删除 ``libnss_files.so.*``\。

**安全改进**

- 为非复制连接强制 ``search_path=pg_catalog`` （Alexander Kukushkin）

  由于 Patroni 重度依赖超级用户连接，我们希望保护它免受利用 ``public`` schema 中与 ``pg_catalog`` 中对应对象同名的用户定义函数和/或运算符进行的攻击。为此，Patroni 创建的所有连接（复制连接除外）都强制使用 ``search_path=pg_catalog``\。

- 防止密码被记录到 ``pg_stat_statements`` （Feike Steenbergen）

  这通过在创建用户时设置 ``pg_stat_statements.track_utility=off`` 来实现。


**缺陷修复**

- 将 ``proxy_address`` 声明为可选（Denis Laxalde）

  因为它实际上是一个非必填选项。

- 改进 insecure 选项的行为（Alexander Kukushkin）

  Ctl 的 ``insecure`` 选项在使用客户端证书进行 REST API 请求时无法正常工作。

- 新集群 bootstrap 时从 ``bootstrap.dcs`` 获取 watchdog 配置（Matt Baker）

  Patroni 之前在 bootstrap 新集群时使用默认值初始化 watchdog 配置，而不是使用 bootstrap DCS 时所用的配置。

- 修复 WIN32 上查找可执行文件时文件扩展名的处理方式（Martín Marqués）

  仅当文件名还没有扩展名时才添加 ``.exe``\。

- 修复 Consul TTL 设置（Alexander Kukushkin）

  我们在 HTTPClient 上设置值时使用了 ``ttl/2.0``\，但忘记在类的属性中把当前值乘以 2。这导致 Consul TTL 偏差两倍。


**移除的功能**

- 移除 ``patronictl configure`` （Polina Bungina）

  不再需要单独的 ``patronictl`` 配置创建。

版本 2.1.5
----------

发布于 2022-11-28

此版本增强了与 PostgreSQL 15 的兼容性，并宣布 Etcd v3 支持已可用于生产环境。Raft 上的 Patroni 仍处于 Beta 阶段。

**新特性**

- 改进 ``patroni --validate-config`` （Denis Laxalde）

  如果配置无效则以退出码 1 退出，并将错误打印到 stderr。

- 在 pause 模式下不删除复制槽（Alexander Kukushkin）

  成员加入/离开集群时，Patroni 会自动创建/删除物理复制槽。在 pause 模式下，槽将不再被删除。

- 监控端点支持 ``HEAD`` 请求方法（Robert Cutajar）

  如果使用 ``HEAD`` 代替 ``GET``\，Patroni 将只返回 HTTP 状态码。

- 支持在 Windows 上运行 behave 测试（Alexander Kukushkin）

  通过引入新的 REST API 端点 ``POST /sigterm``\，在 Windows 上模拟优雅的 Patroni 关闭（``SIGTERM``\）。

- 引入 ``postgresql.proxy_address`` （Alexander Kukushkin）

  它将作为 ``proxy_url`` 写入 DCS 中的成员键，可用于服务发现。


**稳定性改进**

- 从线程中调用 ``pg_replication_slot_advance()`` （Alexander Kukushkin）

  在具有许多逻辑复制槽的繁忙集群上，``pg_replication_slot_advance()`` 调用会影响主 HA 循环，并可能导致成员键过期。

- 在旧 primary 上调用 ``pg_rewind`` 之前归档可能缺失的 WAL（Polina Bungina）

  如果 primary 崩溃并长时间停机，一些 WAL 文件可能从归档和新 primary 中缺失。``pg_rewind`` 有可能从旧 primary 上移除这些 WAL 文件，使其无法作为 standby 启动。通过归档 ``ready`` 状态的 WAL 文件，我们不仅缓解了此问题，而且总体上改善了持续归档体验。

- 尝试创建 Kubernetes Service 时忽略 ``403`` 错误（Nick Hudson、Polina Bungina）

  Patroni 之前会因尝试创建实际上可能已存在的 service 而刷屏日志。

- 改进存活探针（Alexander Kukushkin）

  如果心跳循环运行时间超过 primary 上的 ``ttl`` 或 replica 上的 ``2*ttl``\，存活探针将开始失败。这将允许我们在 Kubernetes 上将其用作 :ref:`watchdog <watchdog>` 的替代方案。

- 确保 switchover 时只有同步节点尝试获取锁（Alexander Kukushkin、Polina Bungina）

  之前，如果在未指定目标节点的情况下执行手动 switchover，存在一点小小的机会让最新的异步成员成为 leader。

- 在 bootstrap 运行期间避免克隆（Ants Aasma）

  不允许在集群 bootstrap 运行时触发不需要 leader 的创建 replica 方法。

- 与 kazoo-2.9.0 的兼容性（Alexander Kukushkin）

  取决于 python 版本，如果在关闭的 socket 上调用 ``select()``\，``SequentialThreadingHandler.select()`` 方法可能抛出 ``TypeError`` 和 ``IOError`` 异常。

- 在 socket 关闭之前显式关闭 SSL 连接（Alexander Kukushkin）

  不这样做会在 OpenSSL 3.0 下导致 ``unexpected eof while reading`` 错误。

- 与 `prettytable>=2.2.0` 的兼容性（Alexander Kukushkin）

  由于内部 API 变更，集群名称标题显示在了错误的行上。


**缺陷修复**

- 处理 Etcd lease_grant 的过期 token（monsterxx03）

  出错时获取新 token 并重试请求。

- 修复 ``GET /read-only-sync`` 端点中的缺陷（Alexander Kukushkin）

  它是在上一版本中引入的，实际上从未正常工作。

- 处理数据目录存储消失的情况（Alexander Kukushkin）

  Patroni 会定期检查 PGDATA 是否存在且非空，但在存储出现问题的情况下，``os.listdir()`` 会抛出 ``OSError`` 异常，破坏心跳循环。

- 等待用户后端关闭时应用 ``master_stop_timeout`` （Alexander Kukushkin）

  看起来像用户后端的东西实际上可能是无法停止的后台 worker（例如 Citus 维护守护进程）。

- 接受 ``postgresql.listen`` 的 ``*:<port>`` （Denis Laxalde）

  ``patroni --validate-config`` 之前会抱怨该值无效。

- 修复 Raft 中的超时问题（Alexander Kukushkin）

  当 Patroni 或 patronictl 启动时，它们会尝试从已知成员获取 Raft 集群拓扑。这些调用之前没有适当的超时。

- token 更改时强制更新 consul service（John A. Lotoski）

  不这样做会报错 "rpc error making call: rpc error making call: ACL not found"。


版本 2.1.4
----------

发布于 2022-06-01

**新特性**

- 改进典型 Debian/Ubuntu 系统上的 ``pg_rewind`` 行为（Gunnar "Nick" Bluth）

  在将 `postgresql.conf` 保存在数据目录之外的 Postgres 环境（例如 Ubuntu/Debian 软件包）中，``pg_rewind --restore-target-wal`` 无法推算出 ``restore_command`` 的值。

- 允许在 Consul service 检查中设置 ``TLSServerName`` （Michael Gmelin）

  当检查通过 IP 执行且 Consul ``node_name`` 不是 FQDN 时非常有用。

- 在 watchdog 中添加 ``ppc64le`` 支持（Jean-Michel Scheiwiler）

  并修复了某些非 x86 平台上的 watchdog 支持。

- 将 aws.py 回调从 ``boto`` 切换到 ``boto3`` （Alexander Kukushkin）

 ``boto``  2.x 自 2018 年起已被弃用，且与 python 3.9 不兼容。

- 在 K8s 上定期刷新 service account token（Haitao Li）

  自 Kubernetes v1.21 起，service account token 会在 1 小时后过期。

- 添加 ``/read-only-sync`` 监控端点（Dennis4b）

  它与 ``/read-only`` 类似，但只包含同步 replica。


**稳定性改进**

- 如果逻辑解码配置与 primary 不匹配，则不要将逻辑复制槽复制到 replica（Alexander Kukushkin）

  如果槽与 ``plugin`` 或 ``database`` 配置选项不匹配，replica 将不再从 primary 复制逻辑复制槽。之前，检查槽是否匹配这些配置选项是在 replica 复制槽并启动之后才执行的，导致不必要的重复重启。

- 对 PostgreSQL v12 以上版本的恢复配置参数进行特殊处理（Alexander Kukushkin）

  作为 replica 启动时，Patroni 应能够通过缓存当前参数值（而不是从 ``pg_settings`` 查询）来更新 ``postgresql.conf``\，并在 leader 地址改变时重启/重载。

- 更好地处理 ``postgresql.listen`` 参数中的 IPv6 地址（Alexander Kukushkin）

  由于 ``listen`` 参数带有端口，人们会尝试将 IPv6 地址放入方括号中，当列表中有多个 IP 时，这些方括号没有被正确剥离。

- 仅在 PostgreSQL v10 及更早版本上执行发散检查时使用 ``replication`` 凭据（Alexander Kukushkin）

  如果启用了 ``rewind``\，在较新的 Postgres 版本上 Patroni 将再次使用 ``superuser`` 或 ``rewind`` 凭据。


**缺陷修复**

- 修复缺失的 ``dateutil.parser`` 导入（Wesley Mendes）

  测试之前没有失败只是因为其他模块也导入了它。

- 确保 ``optime`` 注解是字符串（Sebastian Hasler）

  在某些情况下 Patroni 会尝试以数值形式传递它。

- 更好地处理失败的 ``pg_rewind`` 尝试（Alexander Kukushkin）

  如果在 ``pg_rewind`` 期间 primary 变得不可用，``$PGDATA`` 将处于损坏状态。之后，即使配置不允许，Patroni 也会删除数据目录。

- 当 PostgreSQL 未就绪时，不删除 leader ``ConfigMap``/``Endpoint`` 上的 ``slots`` 注解（Alexander Kukushkin）

  如果未传递 ``slots`` 值，注解将保持当前值。

- 处理 K8s API watcher 的并发问题（Alexander Kukushkin）

  在某些（未知的）条件下，watcher 可能会变得过期；结果，``attempt_to_acquire_leader()`` 方法可能因 HTTP 状态码 409 而失败。在这种情况下，我们重置 watcher 连接并从头开始。

版本 2.1.3
----------

发布于 2022-02-18

**新特性**

- 为 ``patronictl`` 添加加密 TLS 密钥的支持（Alexander Kukushkin）

  可通过 ``ctl.keyfile_password`` 或 ``PATRONI_CTL_KEYFILE_PASSWORD`` 环境变量配置。

- 为 /metrics 端点添加更多指标（Alexandre Pereira）

  具体而言，添加了 ``patroni_pending_restart`` 和 ``patroni_is_paused``\。

- 使 standby 集群配置中可以指定多个主机（Michael Banck）

  如果 standby 集群从 Patroni 集群复制数据，依赖 ``libpq`` 自 PostgreSQL v10 起提供的客户端侧 failover 可能会很好。也就是说，standby leader 上的 ``primary_conninfo`` 和 ``pg_rewind`` 在连接字符串中设置 ``target_session_attrs=read-write``\。``pgpass`` 文件将生成多行（每个主机一行），并且 standby 集群将等待 ``pg_control`` 更新，而不是在 primary 集群节点上调用 ``CHECKPOINT``\。

**稳定性改进**

- 与旧版 ``psycopg2`` 的兼容性（Alexander Kukushkin）

  例如，从 Ubuntu 18.04 软件包安装的 ``psycopg2`` 还没有 ``UndefinedFile`` 异常。

- 如果所有 Etcd 节点都不响应，则重启 ``etcd3`` watcher（Alexander Kukushkin）

  如果 watcher 仍然存活，即使所有 Etcd 节点都失败，``get_cluster()`` 方法也会继续返回过期信息。

- 在 pause 状态下不删除 standby 集群中的 leader 锁（Alexander Kukushkin）

  之前，锁只由作为 primary 运行的节点维护，而不是 standby leader。

**缺陷修复**

- 修复 standby-leader bootstrap 中的缺陷（Alexander Kukushkin）

  如果 Postgres 在 60 秒后没有开始接受连接，Patroni 会认为 bootstrap 失败。该缺陷在 2.1.2 版本中引入。

- 修复 failover 到级联 standby 的缺陷（Alexander Kukushkin）

  在确定级联 standby 上应创建哪些槽时，我们忘记考虑 leader 可能不存在。

- 修复 Postgres 配置校验器中的小问题（Alexander Kukushkin）

  PostgreSQL v14 引入的整型参数因 validator.py 中 min 和 max 值带引号而无法通过验证。

- 检查 leader 状态时使用复制凭据（Alexander Kukushkin）

  可能设置了 ``remove_data_directory_on_diverged_timelines``\，但没有定义 ``rewind_credentials``\，且节点之间不允许超级用户访问。

- 修复 REST API 证书替换时的 "port in use" 错误（Ants Aasma）

  切换证书时，与并发 API 请求存在竞态条件。如果替换期间有活跃请求，替换会以端口占用错误失败，Patroni 会陷入没有活跃 API 服务器的状态。

- 修复密码包含 ``%`` 字符时集群 bootstrap 的缺陷（Bastien Wirtz）

  bootstrap 方法会执行 ``DO`` 块，所有参数都已正确引用，但 ``cursor.execute()`` 方法不喜欢传递空列表参数。

- 修复 "AttributeError: no attribute 'leader'" 异常（Hrvoje Milković）

  如果启用了同步模式且 DCS 内容被清空，就可能发生。

- 修复时间线发散检查中的缺陷（Alexander Kukushkin）

  Patroni 之前错误地假设时间线已发散。对于 pg_rewind 这不会造成问题，但如果不允许 pg_rewind 且设置了 ``remove_data_directory_on_diverged_timelines``\，会导致重新初始化前 leader。


版本 2.1.2
----------

发布于 2021-12-03

**新特性**

- 与 ``psycopg>=3.0`` 的兼容性（Alexander Kukushkin）

  默认优先使用 ``psycopg2``\。仅当 ``psycopg2`` 不可用或其版本过旧时，才使用 `psycopg>=3.0`。

- 在 REST API 中添加 ``dcs_last_seen`` 字段（Michael Banck）

  该字段记录集群成员最后一次成功与 DCS 通信的时间（以 unix 纪元时间计）。这对于识别和/或分析网络分区非常有用。

- 当 ``pg_controldata`` 报告 "shut down" 时释放 leader 锁（Alexander Kukushkin）

  为了解决在 ``archive_command`` 缓慢/失败时 switchover/关闭缓慢的问题，Patroni 会在 ``pg_controldata`` 开始报告 PGDATA 已干净 "shut down" 且验证至少有一个 replica 已接收所有更改之后，立即移除 leader 键。如果没有满足此条件的 replica，则不移除 leader 键并保留旧行为，即 Patroni 会继续更新锁。

- 添加 ``sslcrldir`` 连接参数支持（Kostiantyn Nemchenko）

  该新连接参数在 PostgreSQL v14 中引入。

- 允许在 Zookeeper 中设置 ZNode 的 ACL（Alwyn Davis）

  引入新的配置选项 ``zookeeper.set_acls``\，使 Kazoo 为其创建的每个 ZNode 应用默认 ACL。


**稳定性改进**

- 将下一次恢复尝试延迟到下一个 HA 循环（Alexander Kukushkin）

  如果 Postgres 因磁盘空间不足（例如）而崩溃并因此无法启动，Patroni 会过于急切地尝试恢复它，导致日志刷屏。

- 在可能耗时较长的降级之前添加日志（Michael Banck）

  降级完成可能需要一些时间，仅从日志中可能看不出究竟发生了什么。

- 改进 "I am" 状态消息（Michael Banck）

  ``no action. I am a secondary ({0})`` 对比 ``no action. I am ({0}), a secondary``

- 转换为 ``wal_keep_size`` 时将 ``wal_keep_segments`` 转为 int（Jorge Solórzano）

  可以在全局 :ref:`动态配置 <dynamic_configuration>` 中以字符串形式指定 ``wal_keep_segments``\，由于 Python 是动态类型语言，字符串会被简单地重复相乘。例如：``wal_keep_segments: "100"`` 被转换成了 ``100100100100100100100100100100100100100100100100MB``\。

- 启用同步复制时只允许 switchover 到同步节点（Alexander Kukushkin）

  此外，leader 竞争也只针对已知的同步节点进行。

- Postgres 缓慢时使用缓存的角色作为回退（Alexander Kukushkin）

  在某些极端情况下，Postgres 可能慢到正常的监控查询在几秒内无法完成。``statement_timeout`` 异常如果处理不当，可能导致 leader 键过期或更新失败时 Postgres 没有及时降级。遇到此类异常时，Patroni 将使用缓存的 ``role`` 来确定 Postgres 是否作为 primary 运行。

- 避免对成员 ZNode 进行不必要的更新（Alexander Kukushkin）

  如果成员数据中的值没有变化，就不应发生更新。

- 优化提升后的 checkpoint（Alexander Kukushkin）

  如果最新时间线已经存储在 ``pg_control`` 中，则避免执行 ``CHECKPOINT``\。这有助于避免用 ``initdb`` 初始化新集群后立即执行不必要的 ``CHECKPOINT``\。

- 选择同步节点时优先考虑不带 ``nofailover`` 的成员（Alexander Kukushkin）

  之前，同步节点仅根据复制延迟来选择，因此带 ``nofailover`` 标签的节点与任何其他节点有相同机会成为同步节点。这种行为既令人困惑又危险，因为在 primary 失败时无法自动进行 failover。

- 从 etcd 机器缓存中移除重复主机（Michael Banck）

  etcd 集群中广播的客户端 URL 可能配置错误。在这种情况下，在 Patroni 中移除重复项是举手之劳。


**缺陷修复**

- 进行槽管理时跳过临时复制槽（Alexander Kukushkin）

  从 v10 开始，``pg_basebackup`` 会为 WAL 流式传输创建一个临时复制槽，而 Patroni 会因为槽名称看起来陌生而试图删除它。为修复此问题，在查询 ``pg_stat_replication_slots`` 视图时，我们跳过所有临时槽。

- 确保 ``pg_replication_slot_advance()`` 不会超时（Alexander Kukushkin）

  Patroni 在这种情况下使用了默认的 ``statement_timeout``\，一旦调用失败，极有可能永远无法恢复，导致 ``pg_wal`` 增大和 ``pg_catalog`` 膨胀。

- 降级时 ``/status`` 未被更新（Alexander Kukushkin）

  降级 PostgreSQL 后，旧 leader 会更新 DCS 中的最后 LSN。自 ``2.1.0`` 起引入了新的 ``/status`` 键，但 optime 仍被写入 ``/optime/leader``\。

- 降级时处理 DCS 异常（Alexander Kukushkin）

  在因更新 leader 锁失败而降级 master 时，DCS 可能完全宕机，``get_cluster()`` 调用会抛出异常。如果处理不当，会导致 Postgres 一直保持停止状态，直到 DCS 恢复。

- ``use_unix_socket_repl`` 在某些情况下不生效（Alexander Kukushkin）

  具体来说，当未设置 ``postgresql.unix_socket_directories`` 时。这种情况下，Patroni 应使用 ``libpq`` 的默认值。

- 修复 Patroni REST API 的几个问题（Alexander Kukushkin）

  ``clusters_unlocked`` 有时可能未定义，导致 ``GET /metrics`` 端点出现异常。此外，错误处理方法假设 ``connect_address`` 元组总是有两个元素，而实际上在 IPv6 情况下可能有更多。

- 决定是否 rewind 前等待新提升的节点完成恢复（Alexander Kukushkin）

  实际提升发生并创建新时间线可能需要一些时间。如果不等待，replica 可能得出不需要 rewind 的结论。

- 决定是否 rewind 时处理历史文件中缺失的时间线（Alexander Kukushkin）

  如果当前 replica 时间线在 primary 的历史文件中缺失，replica 之前会错误地认为不需要 rewind。

版本 2.1.1
----------

发布于 2021-08-19

**新特性**

- 支持 ETCD SRV 名称后缀（David Pavlicek）

  Etcd 允许在同一域名下区分多个 Etcd 集群，从现在起 Patroni 也支持这一点。

- 用新 leader 丰富历史记录（huiyalin525）

  它在 ``patronictl history`` 输出中添加了新列。

- 使集群内 Kubernetes 配置的 CA bundle 可配置（Aron Parsons）

  默认情况下，Patroni 使用 ``/var/run/secrets/kubernetes.io/serviceaccount/ca.crt``\，此新特性允许指定自定义的 ``kubernetes.cacert``\。

- 支持动态注册/注销为 Consul service 并更改标签（Tommy Li）

  之前这需要重启 Patroni。

**缺陷修复**

- 避免不必要的 REST API 重载（Alexander Kukushkin）

  上一版本添加了在磁盘上的 REST API 证书变更时重载证书的功能。遗憾的是，重载在启动后无条件地进行。

- 设置 ``etcd.use_proxies`` 时不解析集群成员（Alexander Kukushkin）

  启动时，Patroni 通过查询成员列表来检查 Etcd 集群的健康状况。此外，它还尝试解析其主机名，这在通过代理使用 Etcd 时不是必需的，并会导致不必要的警告。

- 跳过 ``pg_stat_replication`` 中值为 NULL 的行（Alexander Kukushkin）

  即使 ``state = 'streaming'``\，``pg_stat_replication`` 视图的 ``replay_lsn``\、``flush_lsn`` 或 ``write_lsn`` 字段似乎也可能包含 NULL 值。


版本 2.1.0
----------

发布于 2021-07-06

此版本增加了与 PostgreSQL v14 的兼容性，使逻辑复制槽能够在 failover/switchover 后存活，实现了 REST API 的 allowlist 支持，并将日志数量减少为每个心跳一行。

**新特性**

- 与 PostgreSQL v14 的兼容性（Alexander Kukushkin）

  如果 Patroni 本身不处于 "pause" 模式，则取消暂停 WAL 回放。它可能因某些参数的变化（例如 primary 上的 ``max_connections``\）而 "暂停"。

- Failover 逻辑槽（Alexander Kukushkin）

  使逻辑复制槽在 PostgreSQL v11 以上的 failover/switchover 后存活。复制槽通过重启从 primary 复制到 replica，随后使用 `pg_replication_slot_advance() <https://www.postgresql.org/docs/11/functions-admin.html#id-1.5.8.31.8.5.2.2.8.1.1>`__ 函数将其向前推进。结果，槽在 failover 之前就已经存在，不会丢失事件，但某些事件有可能被重复投递。

- 实现 Patroni REST API 的 allowlist（Alexander Kukushkin）

  如果配置了 allowlist，只有 IP 匹配规则的客户端才被允许调用不安全的端点。此外，还可以自动将集群成员的 IP 包含到列表中。

- 添加通过 unix socket 进行复制连接的支持（Mohamad El-Rifai）

  之前，Patroni 总是使用 TCP 进行复制连接，这可能引起 SSL 验证方面的问题。使用 unix socket 可以免除复制用户的 SSL 验证。

- 对用户自定义标签的健康检查（Arman Jafari Tehrani）

  除了 :ref:`预定义标签：<tags_settings>` 之外，还可以指定任意数量的自定义标签，这些标签会出现在 ``patronictl list`` 输出和 REST API 中。从现在起，可以在健康检查中使用自定义标签。

- 添加 Prometheus ``/metrics`` 端点（Mark Mercado、Michael Banck）

  该端点暴露与 ``/patroni`` 相同的指标。

- 减少 Patroni 日志的琐碎信息（Alexander Kukushkin）

  当一切正常时，每次运行 HA 循环只写入一行。


**破坏性变更**

- 旧的 ``永久逻辑复制槽`` 特性将不再适用于 PostgreSQL v10 及更早版本（Alexander Kukushkin）

  在执行提升之后创建逻辑槽的策略无法保证不丢失逻辑事件，因此已禁用。

- 如果节点持有锁，``/leader`` 端点始终返回 200（Alexander Kukushkin）

  提升 standby 集群需要更新负载均衡器健康检查，这不太方便且容易忘记。为解决此问题，我们更改了 ``/leader`` 健康检查端点的行为。它将返回 200，而不考虑集群是普通集群还是 ``standby_cluster``\。


**Raft 支持的改进**

- 可靠的 Raft 流量加密支持（Alexander Kukushkin）

  由于 ``PySyncObj`` 中的各种问题，加密支持非常不稳定。

- 处理 Raft 实现中的 DNS 问题（Alexander Kukushkin）

  如果 ``self_addr`` 和/或 ``partner_addrs`` 使用 DNS 名称而不是 IP 配置，``PySyncObj`` 实际上只在对象创建时解析一次。这导致同一节点以不同 IP 重新上线时出现问题。


**稳定性改进**

- 与 ``psycopg2-2.9+`` 的兼容性（Alexander Kukushkin）

  在 ``psycopg2`` 中，``with connection`` 块内会忽略 ``autocommit = True``\，这会破坏复制协议连接。

- 修复 Zookeeper 下 HA 循环运行过多的问题（Alexander Kukushkin）

  成员 ZNode 的更新引起连锁反应，导致 HA 循环连续运行多次。

- 磁盘上 REST API 证书变更时重载（Michael Todorovic）

  如果 REST API 证书文件在原位置被更新，Patroni 之前不会执行重载。

- 使用 kerberos 认证时不创建 pgpass 目录（Kostiantyn Nemchenko）

  Kerberos 和密码认证是互斥的。

- 修复自定义 bootstrap 的小问题（Alexander Kukushkin）

  仅当执行 PITR 时才以 ``hot_standby=off`` 启动 Postgres，并在 PITR 完成后重启它。


**缺陷修复**

- 与 ``kazoo-2.7+`` 的兼容性（Alexander Kukushkin）

  由于 Patroni 自己处理重试，它依赖 ``kazoo`` 的旧行为：当没有可用连接时，对 Zookeeper 集群的请求会立即被丢弃。

- 当已知通过代理连接时，显式请求 Etcd v3 集群的版本（Alexander Kukushkin）

  Patroni 通过 gRPC-gateway 与 Etcd v3 集群通信，根据集群版本不同，必须使用不同的端点（``/v3``\、``/v3beta`` 或 ``/v3alpha``\）。该版本只随集群拓扑一起解析，但由于通过代理连接时从未解析拓扑。


版本 2.0.2
----------

发布于 2021-02-22

**新特性**

- 能够忽略外部管理的复制槽（James Coleman）

  Patroni 会尝试移除任何它不知道的复制槽，但肯定存在复制槽应由外部管理的情况。从现在起，可以配置不应被移除的槽。

- 添加 REST API 密码套件限制的支持（Gunnar "Nick" Bluth）

  可通过 ``restapi.ciphers`` 或 ``PATRONI_RESTAPI_CIPHERS`` 环境变量配置。

- 添加 REST API 加密 TLS 密钥的支持（Jonathan S. Katz）

  可通过 ``restapi.keyfile_password`` 或 ``PATRONI_RESTAPI_KEYFILE_PASSWORD`` 环境变量配置。

- REST API 认证凭据的恒定时间比较（Alex Brasetvik）

  使用 ``hmac.compare_digest()`` 而不是容易受到时序攻击的 ``==``\。

- 基于复制延迟选择同步节点（Krishna Sarabu）

  如果同步节点上的复制延迟开始超过配置的阈值，它可能被降级为异步和/或被其他节点替换。该行为由 ``maximum_lag_on_syncnode`` 控制。


**稳定性改进**

- 进行自定义 bootstrap 时以 ``hot_standby = off`` 启动 postgres（Igor Yanchenko）

  在自定义 bootstrap 期间，Patroni 恢复 basebackup、启动 Postgres 并等待恢复完成。standby 上的某些 PostgreSQL 参数不能小于 primary 上的值，如果（从 WAL 恢复的）新值高于配置值，Postgres 会 panic 并停止。为避免此类行为，我们将在不启用 ``hot_standby`` 模式的情况下进行自定义 bootstrap。

- 如果必需的 watchdog 不健康则警告用户（Nicolas Thauvin）

  当 watchdog 设备不可写或在 required 模式下缺失时，成员无法被提升。添加了一个警告，告知用户去哪里查找此错误配置。

- 更好的单用户模式恢复详细输出（Alexander Kukushkin）

  如果 Patroni 发现 PostgreSQL 未干净关闭，在某些情况下会通过以单用户模式启动 Postgres 来执行崩溃恢复。恢复可能失败（例如由于磁盘空间不足），但错误被吞掉了。

- 添加与 ``python-consul2`` 模块的兼容性（Alexander Kukushkin、Wilfried Roset）

  老旧的 ``python-consul`` 已经几年没有维护了，因此有人创建了带有新特性和缺陷修复的分支。

- 运行 ``patronictl`` 时不使用 ``bypass_api_service`` （Alexander Kukushkin）

  当 K8s pod 在非 ``default`` namespace 中运行时，它不一定有足够的权限查询 ``kubernetes`` 端点。这种情况下，Patroni 会显示警告并忽略 ``bypass_api_service`` 设置。在 ``patronictl`` 的情况下，该警告有点烦人。

- 如果 ``raft.data_dir`` 不存在则创建它，或确保其可写（Mark Mercado）

  改善用户友好性和可用性。


**缺陷修复**

- pause 中丢失 leader 锁时不中断重启或提升（Alexander Kukushkin）

  在 pause 模式下，允许在没有锁的情况下以 primary 运行 postgres。

- 修复 REST API 中 ``shutdown_request()`` 的问题（Nicolas Limage）

  为了改进 SSL 连接处理并将握手延迟到线程启动之后，Patroni 在 ``HTTPServer`` 中覆盖了几个方法。``shutdown_request()`` 方法被遗漏了。

- 修复使用 Zookeeper 时睡眠时间的问题（Alexander Kukushkin）

  之前，Patroni 在运行 HA 代码之间的睡眠时间可能长达两倍。

- 修复 bootstrap 失败后移动数据目录时无效的 ``os.symlink()`` 调用（Andrew L'Ecuyer）

  如果 bootstrap 失败，Patroni 会重命名数据目录、pg_wal 和所有表空间。之后它会更新符号链接以保持文件系统一致。由于 ``src`` 和 ``dst`` 参数被交换，符号链接创建失败。

- 修复 post_bootstrap() 方法中的缺陷（Alexander Kukushkin）

  如果未配置超级用户密码，Patroni 无法调用 ``post_init`` 脚本，因此整个 bootstrap 都会失败。

- 修复 standby 集群中 pg_rewind 的问题（Alexander Kukushkin）

  如果超级用户名与 Postgres 不同，standby 集群中的 ``pg_rewind`` 会因连接字符串不包含数据库名称而失败。

- 仅当与 Etcd v3 的认证明确失败时才退出（Alexander Kukushkin）

  启动时 Patroni 会执行 Etcd 集群拓扑发现，并在必要时进行认证。可能其中一个 etcd 服务器不可访问，Patroni 会尝试在该服务器上进行认证并失败，而不是用下一个节点重试。

- 处理 psutil cmdline() 返回空列表的情况（Alexander Kukushkin）

  僵尸进程仍然是 postmaster 的子进程，但它们没有 cmdline()。

- 将 ``PATRONI_KUBERNETES_USE_ENDPOINTS`` 环境变量视为布尔值（Alexander Kukushkin）

  不这样做将导致无法通过环境禁用 ``kubernetes.use_endpoints``\。

- 改进并发端点更新错误的处理（Alexander Kukushkin）

  Patroni 将显式查询当前端点对象，验证当前 pod 仍持有 leader 锁，然后重复更新。


版本 2.0.1
----------

发布于 2020-10-01

**新特性**

- ``less`` 不可用时在 ``patronictl edit-config`` 中使用 ``more`` 作为分页器（Pavel Golub）

  在 Windows 上将是 ``more.com``\。此外，``requirements.txt`` 中的 ``cdiff`` 已被改为 ``ydiff``\，但为兼容起见，``patronictl`` 仍然支持两者。

- 添加对 ``raft`` ``bind_addr`` 和 ``password`` 的支持（Alexander Kukushkin）

  ``raft.bind_addr`` 在 NAT 后面运行时可能很有用。``raft.password`` 启用流量加密（需要 ``cryptography`` 模块）。

- 添加 ``sslpassword`` 连接参数支持（Kostiantyn Nemchenko）

  该连接参数在 PostgreSQL 13 中引入。

**稳定性改进**

- 更改 pause 模式下的行为（Alexander Kukushkin）

  1. 如果 ``PGDATA`` 目录缺失/为空，Patroni 将不会调用 ``bootstrap`` 方法。
  2. 在 pause 模式下，Patroni 不会因 sysid 不匹配而退出，只记录警告。
  3. 在 pause 模式下，如果 Postgres 不以恢复状态运行（接受写入）但 sysid 与 initialize 键不匹配，节点将不会尝试获取 leader 键。

- 执行崩溃恢复时应用 ``master_start_timeout`` （Alexander Kukushkin）

  如果 Postgres 在 leader 节点上崩溃，Patroni 会通过以单用户模式启动 Postgres 进行崩溃恢复。在崩溃恢复期间，leader 锁会被更新。如果崩溃恢复在 ``master_start_timeout`` 秒内未完成，Patroni 将强制停止它并释放 leader 锁。

- 从 ``urllib3`` 依赖中移除 ``secure`` extra（Alexander Kukushkin）

  添加它的唯一原因是 python 2.7 的 ``ipaddress`` 依赖。

**缺陷修复**

- 修复 ``Kubernetes.update_leader()`` 中的缺陷（Alexander Kukushkin）

  未处理的异常导致 leader 对象更新失败时无法降级 primary。

- 修复使用 RAFT 时 ``patronictl`` 挂起的问题（Alexander Kukushkin）

  将 ``patronictl`` 与 Patroni 配置一起使用时，``self_addr`` 应添加到 ``partner_addrs``\。

- 修复 ``get_guc_value()`` 中的缺陷（Alexander Kukushkin）

  Patroni 在 PostgreSQL 12 上无法获取 ``restore_command`` 的值，因此为 ``pg_rewind`` 获取缺失 WAL 的功能无法工作。


版本 2.0.0
----------

发布于 2020-09-02

此版本增强了与 PostgreSQL 13 的兼容性，添加了对多个同步 standby 的支持，在处理 ``pg_rewind`` 方面有显著改进，添加了对 Etcd v3 和纯 RAFT（无需 Etcd、Consul 或 Zookeeper）上 Patroni 的支持，并使得可以可选地调用 ``pre_promote`` （fencing）脚本。

**PostgreSQL 13 支持**

- 在 PostgreSQL 13 以上版本提升为 ``standby_leader`` 时不触发 ``on_reload`` （Alexander Kukushkin）

  提升为 ``standby_leader`` 时，我们更改 ``primary_conninfo``\、更新角色并重载 Postgres。由于 ``on_role_change`` 和 ``on_reload`` 实际上相互重复，Patroni 将只调用 ``on_role_change``\。

- 添加对 ``gssencmode`` 和 ``channel_binding`` 连接参数的支持（Alexander Kukushkin）

  PostgreSQL 12 引入了 ``gssencmode``\，13 引入了 ``channel_binding`` 连接参数，现在如果它们定义在 ``postgresql.authentication`` 配置节中，就可以使用。

- 处理 ``wal_keep_segments`` 更名为 ``wal_keep_size`` （Alexander Kukushkin）

  在配置错误的情况下（13 上配置 ``wal_keep_segments``\、旧版本上配置 ``wal_keep_size``\），Patroni 会自动调整配置。

- 在 13 上尽可能使用带 ``--restore-target-wal`` 的 ``pg_rewind`` （Alexander Kukushkin）

  在 PostgreSQL 13 上，Patroni 检查是否配置了 ``restore_command``\，并告诉 ``pg_rewind`` 使用它。


**新特性**

- [BETA] 实现对纯 RAFT 上 Patroni 的支持（Alexander Kukushkin）

  这使得无需 Etcd、Consul 或 Zookeeper 等第三方依赖即可运行 Patroni。要实现 HA，您需要运行三个 Patroni 节点，或两个 Patroni 节点加一个 ``patroni_raft_controller`` 节点。更多信息请查看 :ref:`文档 <raft_settings>`。

- [BETA] 实现通过 gRPC-gateway 对 Etcd v3 协议的支持（Alexander Kukushkin）

  Etcd 3.0 发布于四年多前，Etcd 3.4 默认禁用了 v2。v2 也有可能被完全从 Etcd 中移除，因此我们在 Patroni 中实现了对 Etcd v3 的支持。要开始使用它，您必须在 Patroni 配置文件中显式创建 ``etcd3`` 配置节。

- 支持多个同步 standby（Krishna Sarabu）

  它允许运行具有多个同步 replica 的集群。同步 replica 的最大数量由新参数 ``synchronous_node_count`` 控制。默认设置为 1，当 ``synchronous_mode`` 设置为 ``off`` 时不起作用。

- 添加调用 ``pre_promote`` 脚本的可能性（Sergey Dudoladov）

  与回调不同，``pre_promote`` 脚本在获取 leader 锁之后、提升 Postgres 之前同步调用。如果脚本失败或以非零退出码退出，当前节点将释放 leader 锁。

- 添加配置目录的支持（Floris van Nee）

  目录中的 YAML 文件按字母顺序加载并应用。

- PostgreSQL 参数的高级验证（Alexander Kukushkin）

  如果特定参数不受当前 PostgreSQL 版本支持或其值不正确，Patroni 将完全移除该参数或尝试修正该值。

- 提升后强制 checkpoint 完成时唤醒主线程（Alexander Kukushkin）

  Replica 通过 DCS 中 leader 的成员键等待 checkpoint 指示。该键通常每个 HA 循环只更新一次。如果不唤醒主线程，replica 将不得不比必要时间多等待最多 ``loop_wait`` 秒。

- 在 9.6 以上版本使用 ``pg_stat_wal_receiver`` 视图（Alexander Kukushkin）

  该视图包含 ``primary_conninfo`` 和 ``primary_slot_name`` 的最新值，而 ``recovery.conf`` 的内容可能是过期的。

- 改进 Patroni 配置文件中 IPv6 地址的处理（Mateusz Kowalski）

  IPv6 地址应该用方括号括起来，但 Patroni 之前期望得到不带括号的地址。现在两种格式都受支持。

- 添加 Consul ``service_tags`` 配置参数（Robert Edström）

  它们对动态服务发现很有用，例如供负载均衡器使用。

- 实现 Zookeeper 的 SSL 支持（Kostiantyn Nemchenko）

  这需要 ``kazoo>=2.6.0``\。

- 为自定义 bootstrap 方法实现 ``no_params`` 选项（Kostiantyn Nemchenko）

  它允许直接调用 ``wal-g``\、``pgBackRest`` 和其他备份工具，而无需将它们包装到 shell 脚本中。

- init 失败后移动 WAL 和表空间（Feike Steenbergen）

  执行 ``reinit`` 时，Patroni 之前不仅移除 ``PGDATA``\，还移除符号链接的 WAL 目录和表空间。现在 ``move_data_directory()`` 方法将做类似的工作，即重命名 WAL 目录和表空间并更新 PGDATA 中的符号链接。


**pg_rewind 支持的改进**

- 改进时间线发散检查（Alexander Kukushkin）

  当 replica 上的回放位置没有超过切换点，或旧 primary 上 checkpoint 记录的结束位置与切换点相同时，我们不需要 rewind。为了获得 checkpoint 记录的结束位置，我们使用 ``pg_waldump`` 并解析其输出。

- 如果 ``pg_rewind`` 抱怨缺失 WAL，尝试获取缺失的 WAL（Alexander Kukushkin）

  可能发生 ``pg_rewind`` 所需的 WAL 段已不存在于 ``pg_wal`` 目录中，因此 ``pg_rewind`` 无法在发散点之前找到 checkpoint 位置。从 PostgreSQL 13 开始，``pg_rewind`` 可以使用 ``restore_command`` 获取缺失的 WAL。对于较旧的 PostgreSQL 版本，Patroni 会解析失败 rewind 尝试的错误，并尝试自行调用 ``restore_command`` 来获取缺失的 WAL。

- 检测 standby 集群中的新时间线，并在必要时触发 rewind/重新初始化（Alexander Kukushkin）

  ``standby_cluster`` 与 primary 集群解耦，因此不会立即知道 leader 选举和时间线切换。为检测这一事实，``standby_leader`` 会定期检查 ``pg_wal`` 中的新历史文件。

- 缩短并美化历史日志输出（Alexander Kukushkin）

  当 Patroni 试图判断是否需要 ``pg_rewind`` 时，它可能把 primary 中历史文件的内容写入日志。历史文件随每次 failover/switchover 增长，最终会占据太多行，其中大部分并不那么有用。Patroni 将不再显示原始数据，而只显示当前 replica 时间线之前的 3 行和之后的 2 行。


**K8s 上的改进**

- 摆脱 ``kubernetes`` python 模块（Alexander Kukushkin）

  官方的 python kubernetes 客户端包含大量自动生成的代码，因此非常笨重。Patroni 只使用 K8s API 端点的一小部分，实现对其的支持并不困难。

- 使绕过 ``kubernetes`` service 成为可能（Alexander Kukushkin）

  在 K8s 上运行时，Patroni 通常通过 ``kubernetes`` service 与 K8s API 通信，该 service 的地址暴露在 ``KUBERNETES_SERVICE_HOST`` 环境变量中。与其他任何 service 一样，``kubernetes`` service 由 ``kube-proxy`` 处理，而 ``kube-proxy`` 又根据配置依赖于用户空间程序或 ``iptables`` 进行流量路由。跳过中间组件、直接连接到 K8s master 节点，使我们能够实现更好的重试策略，并降低 K8s master 节点升级时降级 Postgres 的风险。

- 同步 Patroni 集群所有 pod 的 HA 循环（Alexander Kukushkin）

  不这样做会把故障检测时间从 ``ttl`` 增加到 ``ttl + loop_wait``\。

- 在 K8s 上填充 subsets 地址中的 ``references`` 和 ``nodename`` （Alexander Kukushkin）

  某些负载均衡器依赖这些信息。

- 修复 ``update_leader()`` 中可能的竞态条件（Alexander Kukushkin）

  在 Patroni 之外并发更新 leader configmap 或 endpoint 可能导致 ``update_leader()`` 调用失败。这种情况下，Patroni 会重新检查当前节点是否仍拥有 leader 锁，并重复更新。

- 显式禁止 patch 不存在的配置（Alexander Kukushkin）

  对于 ``kubernetes`` 之外的 DCS，PATCH 调用会因 ``cluster.config`` 为 ``None`` 而以异常失败，但在 Kubernetes 上它会愉快地创建配置注解，并在 bootstrap 完成后阻止写入 bootstrap 配置。

- 修复 ``pause`` 中的缺陷（Alexander Kukushkin）

  当 leader 键不存在时，replica 会移除 ``primary_conninfo`` 并重启 Postgres，但它们应该什么都不做。


**REST API 的改进**

- 将 TLS 握手延迟到 worker 线程启动之后（Alexander Kukushkin、Ben Harris）

  如果 TLS 握手在 API 线程中完成且客户端没有发送任何数据，API 线程会被阻塞（存在 DoS 风险）。

- 在 REST API 中独立于客户端证书检查 ``basic-auth`` （Alexander Kukushkin）

  之前只验证客户端证书。独立执行两项检查是绝对有效的用例。

- 在 ``OPTIONS`` 请求的 HTTP 头之后写入双重 ``CRLF`` （Sergey Burladyan）

  HAProxy 对单个 ``CRLF`` 感到满意，而 Consul 健康检查抱怨连接损坏和意外 EOF。

- ``GET /cluster`` 对 Zookeeper 显示过期的成员信息（Alexander Kukushkin）

  该端点使用 Patroni 内部集群视图。对 Patroni 本身没有造成问题，但当暴露给外部世界时，我们需要显示最新信息，尤其是复制延迟。

- 修复 standby 集群的健康检查（Alexander Kukushkin）

  对 master 的 ``GET /standby-leader`` 和对 ``standby_leader`` 的 ``GET /master`` 之前错误地以 200 响应。

- 实现 ``DELETE /switchover`` （Alexander Kukushkin）

  该 REST API 调用删除已计划的 switchover。

- 创建 ``/readiness`` 和 ``/liveness`` 端点（Alexander Kukushkin）

  当 K8s service 与标签选择器一起使用时，它们可用于从 subsets 地址中排除 "不健康" 的 pod。

- 增强 ``GET /replica`` 和 ``GET /async`` REST API 健康检查（Krishna Sarabu、Alexander Kukushkin）

  检查现在支持可选的 ``?lag=<max-lag>`` 关键字，并且仅当延迟小于提供的值时才以 200 响应。如果依赖此特性，请记住 leader 上的 WAL 位置信息每 ``loop_wait`` 秒才更新一次！

- 添加 REST API 响应中用户定义 HTTP 头的支持（Yogesh Sharma）

  如果从浏览器发出请求，此特性可能很有用。


**patronictl 的改进**

- 在 ``patronictl pause`` 中不要尝试调用不存在的 leader（Alexander Kukushkin）

  在 K8s 上暂停没有 leader 的集群时，``patronictl`` 之前会显示无法访问成员 "None" 的警告。

- 处理成员 ``conn_url`` 缺失的情况（Alexander Kukushkin）

  在 K8s 上，由于 Patroni 尚未运行，pod 可能没有必要的注解。这会导致 ``patronictl`` 失败。

- 添加打印 ASCII 集群拓扑的能力（Maxim Fedotov、Alexander Kukushkin）

  这对于概览具有级联复制的集群非常有用。

- 实现 ``patronictl flush switchover`` （Alexander Kukushkin）

  在此之前，``patronictl flush`` 只支持取消计划中的重启。


**缺陷修复**

- 使用现有 PGDATA bootstrap 集群时出现属性错误（Krishna Sarabu）

  尝试创建/更新 ``/history`` 键时，Patroni 访问了 DCS 中尚未创建的 ``ClusterConfig`` 对象。

- 改进 Consul 中的异常处理（Alexander Kukushkin）

  ``touch_member()`` 方法中未处理的异常导致整个 Patroni 进程崩溃。

- 为 ``post_init`` 脚本强制 ``synchronous_commit=local`` （Alexander Kukushkin）

  Patroni 在创建用户（``replication``\、``rewind``\）时已经这样做，但在 ``post_init`` 情况下遗漏是一个疏忽。结果，如果脚本没有在内部自行处理，``synchronous_mode`` 下的 bootstrap 无法完成。

- 增加 Consul 池管理器中的 ``maxsize`` （ponvenkates）

  使用默认的 ``size=1`` 会产生一些警告。

- Patroni 之前错误地将 Postgres 报告为正在运行（Alexander Kukushkin）

  例如，当 Postgres 因磁盘空间不足错误而崩溃时，状态没有被更新。

- 将 ``*`` 放入 ``pgpass`` 而不是缺失或空值（Alexander Kukushkin）

  例如，如果未指定 ``standby_cluster.port``\，``pgpass`` 文件之前会生成错误。

- 跳过在名称带特殊字符的 leader 节点上创建物理复制槽（Krishna Sarabu）

  当名称包含 '-' 等特殊字符（例如 "abc-us-1"）时，Patroni 之前似乎会为 leader 节点创建一个休眠槽（当定义了 ``slots`` 时）。

- 避免在自定义 bootstrap 中删除不存在的 ``pg_hba.conf`` （Krishna Sarabu）

  如果自定义 bootstrap 后 ``pg_hba.conf`` 恰好位于 ``pgdata`` 目录之外，Patroni 之前会失败。


版本 1.6.5
----------

发布于 2020-08-23

**新特性**

- Master 停止超时（Krishna Sarabu）

  Patroni 停止 Postgres 时允许等待的秒数。仅在启用 ``synchronous_mode`` 时生效。当设置为大于 0 的值且启用了 ``synchronous_mode`` 时，如果停止操作运行时间超过 ``master_stop_timeout`` 设置的值，Patroni 会向 postmaster 发送 ``SIGKILL``\。请根据您的持久性/可用性权衡来设置该值。如果参数未设置或设置为非正值，``master_stop_timeout`` 不起作用。

- 不要创建以 primary 名称命名的永久物理槽（Alexander Kukushkin）

  replica 停机时 primary 回收 WAL 段是一个常见问题。现在，对于节点数量和名称固定不变的静态集群，我们有了一个很好的解决方案。您只需在 ``slots`` 中列出所有节点的名称，这样当节点停机（未注册在 DCS 中）时，primary 不会移除该槽。

- 配置校验器的首个草案（Igor Yanchenko）

  使用 ``patroni --validate-config patroni.yaml`` 来验证 Patroni 配置。

- 可配置时间线历史的最大长度（Krishna Sarabu）

  Patroni 将 failover/switchover 的历史写入 DCS 中的 ``/history`` 键。随着时间推移，该键会变得很大，但在大多数情况下只有最后几行比较重要。``max_timelines_history`` 参数允许指定 DCS 中保留的最大时间线历史条目数。

- Kazoo 2.7.0 兼容性（Danyal Prout）

  Kazoo 中的某些非公开方法更改了签名，但 Patroni 依赖它们。


**patronictl 的改进**

- 显示成员标签（Kostiantyn Nemchenko、Alexander Kukushkin）

  标签是为每个节点单独配置的，以前没有简单的方法来概览它们。

- 改进成员输出（Alexander Kukushkin）

  冗余的集群名称不再显示在每行上，只显示在表头中。

.. code-block:: bash

    $ patronictl list
    + Cluster: batman (6813309862653668387) +---------+----+-----------+---------------------+
    |    Member   |      Host      |  Role  |  State  | TL | Lag in MB | Tags                |
    +-------------+----------------+--------+---------+----+-----------+---------------------+
    | postgresql0 | 127.0.0.1:5432 | Leader | running |  3 |           | clonefrom: true     |
    |             |                |        |         |    |           | noloadbalance: true |
    |             |                |        |         |    |           | nosync: true        |
    +-------------+----------------+--------+---------+----+-----------+---------------------+
    | postgresql1 | 127.0.0.1:5433 |        | running |  3 |       0.0 |                     |
    +-------------+----------------+--------+---------+----+-----------+---------------------+

- 显式指定但找不到配置文件时失败（Kaarel Moppel）

  之前 ``patronictl`` 只报告 ``DEBUG`` 消息。

- 解决未初始化的 K8s pod 破坏 patronictl 的问题（Alexander Kukushkin）

  Patroni 在 K8s 上依赖某些 pod 注解。当一个 Patroni pod 正在停止或启动时，还没有有效注解，``patronictl`` 之前会因异常而失败。


**稳定性改进**

- K8s API 服务器的 LIST 调用失败时应用 1 秒退避（Alexander Kukushkin）

  这主要是为了避免刷屏日志，但也助于防止主线程饥饿。

- K8s API 返回 ``retry-after`` HTTP 头时重试（Alexander Kukushkin）

  如果 K8s API 服务器请求过载，它可能会要求重试。

- 从 postmaster 环境剔除 ``KUBERNETES_`` 环境变量（Feike Steenbergen）

  PostgreSQL 不需要 ``KUBERNETES_`` 环境变量，但将它们暴露给 postmaster 也会把它们暴露给后端和普通数据库用户（例如使用 pl/perl）。

- 重新初始化时清理表空间（Krishna Sarabu）

  在 reinit 期间，Patroni 之前只移除 ``PGDATA``\，而留下用户定义的表空间目录。这导致 Patroni 在 reinit 中循环。之前解决该问题的变通方法是实现 :ref:`自定义 bootstrap <custom_bootstrap>` 脚本。

- 提升发生后显式执行 ``CHECKPOINT`` （Alexander Kukushkin）

  这有助于缩短新 primary 可用于 ``pg_rewind`` 之前的时间。

- 智能刷新 Etcd 成员（Alexander Kukushkin）

  如果 Patroni 无法在 Etcd 集群的所有成员上执行请求，它会在下次重试前重新检查 ``A`` 或 ``SRV`` 记录是否发生变化（IP/主机）。

- 跳过 ``pg_controldata`` 中缺失的值（Feike Steenbergen）

  当尝试使用与 PGDATA 版本不匹配的二进制文件时，值会缺失。Patroni 仍会尝试启动 Postgres，而 Postgres 会抱怨主版本不匹配并以错误中止。


**缺陷修复**

- 需要时禁用 Consul 的 SSL 验证（Julien Riou）

  从某个版本的 ``urllib3`` 开始，必须显式设置 ``cert_reqs = ssl.CERT_NONE`` 才能有效禁用 SSL 验证。

- 避免在 HA 循环的每次循环中都打开复制连接（Alexander Kukushkin）

  回归在 1.6.4 中引入。

- 在失败的 primary 上调用 ``on_role_change`` 回调（Alexander Kukushkin）

  在某些情况下，这可能导致虚拟 IP 一直保留在旧 primary 上。回归在 1.4.5 中引入。

- 成功的 pg_rewind 后 postgres 启动时重置 rewind 状态（Alexander Kukushkin）

  由于此缺陷，Patroni 会在 pause 模式下启动手动关闭的 postgres。

- 检查 ``recovery.conf`` 时将 ``recovery_min_apply_delay`` 转换为 ``ms``

  如果在 PostgreSQL 12 之前版本的节点上配置了 ``recovery_min_apply_delay``\，Patroni 会无限期重启 replica。

- PyInstaller 兼容性（Alexander Kukushkin）

  PyInstaller 将 Python 应用程序冻结（打包）为独立可执行文件。当我们为 ``multiprocessing`` 改用 ``spawn`` 方法而不是 ``fork`` 时，兼容性被破坏。

版本 1.6.4
----------

发布于 2020-01-27

**新特性**

- 为 ``patronictl reinit`` 实现 ``--wait`` 选项（Igor Yanchenko）

  如果使用 ``--wait`` 选项，Patronictl 将等待 ``reinit`` 完成。

- Windows 支持的进一步改进（Igor Yanchenko、Alexander Kukushkin）

  1. 所有用于集成测试的 shell 脚本都改写为 python
  2. 在非 posix 系统上使用 ``pg_ctl kill`` 停止 postgres
  3. 不尝试使用 unix-domain socket


**稳定性改进**

- 确保 ``unix_socket_directories`` 和 ``stats_temp_directory`` 存在（Igor Yanchenko）

  Patroni 和 Postgres 启动时，确保 ``unix_socket_directories`` 和 ``stats_temp_directory`` 存在或尝试创建它们。如果创建失败，Patroni 将退出。

- 确保 ``postgresql.pgpass`` 位于 Patroni 具有写权限的位置（Igor Yanchenko）

  如果它没有写权限，Patroni 将以异常退出。

- 默认禁用 Consul ``serfHealth`` 检查（Kostiantyn Nemchenko）

  即使出现轻微网络问题，失败的 ``serfHealth`` 也会导致与节点关联的所有 session 失效。因此，leader 键会远早于 ``ttl`` 丢失，导致 replica 不必要地重启，甚至可能降级 primary。

- 为到 K8s API 的连接配置 tcp keepalive（Alexander Kukushkin）

  如果在 TTL 秒后 socket 上没有任何数据，可以认为连接已死。

- 创建用户时避免记录密码（Alexander Kukushkin）

  如果密码被拒绝，或日志配置为 verbose，或根本没有配置日志，密码可能会被写入 postgres 日志。为避免这种情况，Patroni 会在尝试创建/更新用户之前，将 ``log_statement``\、``log_min_duration_statement`` 和 ``log_min_error_statement`` 改为一些安全值。


**缺陷修复**

- 在级联 replica 上使用 ``standby_cluster`` 配置中的 ``restore_command`` （Alexander Kukushkin）

  ``standby_leader`` 从该特性存在之初就一直在这样做。在 replica 上不做同样的事情可能会阻止它们赶上 standby leader。

- 更新 standby 集群报告的时间线（Alexander Kukushkin）

  在时间线切换的情况下，standby 集群正确地从 primary 复制，但 ``patronictl`` 报告的是旧时间线。

- 允许在 custom_conf 中定义某些恢复参数（Alexander Kukushkin）

  在 replica 上验证恢复参数时，如果 ``archive_cleanup_command``\、``promote_trigger_file``\、``recovery_end_command``\、``recovery_min_apply_delay`` 和 ``restore_command`` 未在 patroni 配置中定义，而是定义在 ``postgresql.auto.conf`` 或 ``postgresql.conf`` 之外的文件中，Patroni 将跳过它们。

- 改进名称中带句点的 postgresql 参数的处理（Alexander Kukushkin）

  此类参数可能由扩展定义，其单位不一定是字符串。更改值可能需要重启（例如 ``pg_stat_statements.max``\）。

- 改进关闭期间的异常处理（Alexander Kukushkin）

  关闭期间，Patroni 会尝试更新其在 DCS 中的状态。如果 DCS 不可访问，可能抛出异常。缺少异常处理会阻止 logger 线程停止。


版本 1.6.3
----------

发布于 2019-12-05

**缺陷修复**

- 运行 ``pg_rewind`` 时不暴露密码（Alexander Kukushkin）

  该缺陷在 `#1301 <https://github.com/patroni/patroni/pull/1301>`__ 中引入。

- 将 ``postgresql.authentication`` 中指定的连接参数应用于 ``pg_basebackup`` 和自定义 replica 创建方法（Alexander Kukushkin）

  它们之前依赖类似 URL 的连接字符串，因此参数从未生效。


版本 1.6.2
----------

发布于 2019-12-05

**新特性**

- 实现 ``patroni --version`` （Igor Yanchenko）

  它打印 Patroni 的当前版本并退出。

- 为所有 http 请求设置 ``user-agent`` http 头（Alexander Kukushkin）

  Patroni 通过 http 协议与 Consul、Etcd 和 Kubernetes API 通信。拥有精心构造的 ``user-agent``\（例如：``Patroni/1.6.2 Python/3.6.8 Linux``\）可能对调试和监控很有用。

- 使异常回溯的日志级别可配置（Igor Yanchenko）

  如果设置 ``log.traceback_level=DEBUG``\，则只有 ``log.level=DEBUG`` 时才能看到回溯。默认行为保持不变。


**稳定性改进**

- 搜索配置文件所需模块时避免导入所有 DCS 模块（Alexander Kukushkin）

  如果只需要例如 Zookeeper，则无需导入 Etcd、Consul 和 Kubernetes 的模块。这有助于减少内存使用，并解决出现 ``Failed to import smth`` INFO 消息的问题。

- 从显式依赖中移除 python ``requests`` 模块（Alexander Kukushkin）

  它没有用于任何关键用途，但在新版本 ``urllib3`` 发布时会引发很多问题。

- 改进对以逗号分隔字符串（而非 YAML 数组）形式编写的 ``etcd.hosts`` 的处理（Igor Yanchenko）

  之前，当以 ``host1:port1, host2:port2`` （逗号后带空格字符）格式编写时会失败。


**可用性改进**

- 不要让用户从 ``patronictl`` 中的空列表里选择成员（Igor Yanchenko）

  如果用户提供了错误的集群名称，我们将抛出异常，而不是要求从空列表中选择成员。

- 如果 REST API 无法绑定，使错误消息更有帮助（Igor Yanchenko）

  对于经验不足的用户，从 Python 堆栈跟踪中找出问题所在可能很困难。


**缺陷修复**

- 修复 ``wal_buffers`` 的计算（Alexander Kukushkin）

  PostgreSQL 11 中基本单位从 8 kB 块改为字节。

- 仅在 PostgreSQL 10 以上版本在 ``primary_conninfo`` 中使用 ``passfile`` （Alexander Kukushkin）

  在较旧版本上，除非安装了最新版本的 ``libpq``\，否则无法保证 ``passfile`` 能正常工作。


版本 1.6.1
----------

发布于 2019-11-15

**新特性**

- 添加 ``PATRONICTL_CONFIG_FILE`` 环境变量（msvechla）

  它允许从环境配置 ``patronictl`` 的 ``--config-file`` 参数。

- 实现 ``patronictl history`` （Alexander Kukushkin）

  它显示 failover/switchover 的历史记录。

- 执行 ``pg_rewind`` 时在 ``PGOPTIONS`` 中传递 ``-c statement_timeout=0`` （Alexander Kukushkin）

  这可以防止服务器上的 ``statement_timeout`` 设置为较小的值而取消 pg_rewind 执行的某个语句。

- 允许更低的 PostgreSQL 配置值（Soulou）

  Patroni 之前不允许某些 PostgreSQL 配置参数设置为小于某些硬编码值的值。现在允许的最小值更小，默认值没有改变。

- 允许基于证书的认证（Jonathan S. Katz）

  此特性为 superuser、replication、rewind 帐户启用基于证书的认证，并允许用户指定希望连接的 ``sslmode``\。

- 在 ``primary_conninfo`` 中使用 ``passfile`` 而不是密码（Alexander Kukushkin）

  这可以避免对 postgresql.conf 设置 ``600`` 权限。

- 无论配置是否变化都执行 ``pg_ctl reload`` （Alexander Kukushkin）

  某些配置文件可能不受 Patroni 控制。当有人通过 REST API 重载或向 Patroni 进程发送 SIGHUP 时，通常期望 Postgres 也会被重载。之前，当 Patroni 配置的 ``postgresql`` 配置节没有变化时，这不会发生。

- 比较所有恢复参数，而不只是 ``primary_conninfo`` （Alexander Kukushkin）

  之前，``check_recovery_conf()`` 方法只检查 ``primary_conninfo`` 是否发生了变化，从不考虑所有其他恢复参数。

- 使某些恢复参数无需重启即可应用（Alexander Kukushkin）

  从 PostgreSQL 12 开始，以下恢复参数可以无需重启而更改：``archive_cleanup_command``\、``promote_trigger_file``\、``recovery_end_command`` 和 ``recovery_min_apply_delay``\。在未来的 Postgres 版本中，此列表会扩展，Patroni 将自动支持。

- 使 ``use_slots`` 可以在线更改（Alexander Kukushkin）

  之前需要重启 Patroni 并手动删除槽。

- 启动 Postgres 时只移除带 ``PATRONI_`` 前缀的环境变量（Cody Coons）

  这将解决运行不同 Foreign Data Wrapper 时的许多问题。


**稳定性改进**

- 使用 K8s API 时使用 LIST + WATCH（Alexander Kukushkin）

  它可以高效地接收对象变更（pod、endpoint/configmap），并减少对 K8s master 节点的压力。

- 改进 bootstrap 期间 PGDATA 非空时的工作流程（Alexander Kukushkin）

  根据 ``initdb`` 源码，如果 PGDATA 中只有 ``lost+found`` 和 ``.dotfiles``\，它可能认为 PGDATA 为空。现在 Patroni 也这样做。如果 ``PGDATA`` 非空，但从 ``pg_controldata`` 的角度看无效，Patroni 将报错并退出。

- 避免在每个 HA 循环中调用昂贵的 ``os.listdir()`` （Alexander Kukushkin）

  当系统处于 IO 压力下时，``os.listdir()`` 可能需要几秒（甚至几分钟）才能执行完毕，严重影响 Patroni 的 HA 循环。这甚至可能导致 leader 键因缺少更新而从 DCS 中消失。有一种更好、更廉价的方法来检查 PGDATA 是否为空。现在，我们检查 PGDATA 中是否存在 ``global/pg_control`` 文件。

- 日志基础设施的一些改进（Alexander Kukushkin）

  之前由于日志线程是 ``daemon`` 线程，在关闭时可能丢失最后几行日志。

- 在 python 3.4 以上版本使用 ``spawn`` multiprocessing 启动方法（Maciej Kowalczyk）

  这是 Python 中一个已知的 `问题 <https://bugs.python.org/issue6721>`__：threading 和 multiprocessing 不能很好地混用。从默认的 ``fork`` 方法切换到 ``spawn`` 是推荐的解决方法。否则，Postmaster 启动进程可能挂起，Patroni 无限期报告 ``INFO: restarting after failure in progress``\，而 Postgres 实际上已经启动并运行。

**REST API 的改进**

- 使 REST API 可以检查客户端证书（Alexander Kukushkin）

  如果将 ``verify_client`` 设置为 ``required``\，Patroni 将检查所有 REST API 调用的客户端证书。当设置为 ``optional`` 时，会检查所有不安全 REST API 端点的客户端证书。

- 如果 Postgres 未运行，为 ``GET /replica`` 健康检查请求返回 503 响应码（Alexander Anikin）

  Postgres 在开始接受客户端连接之前，可能在恢复上花费大量时间。

- 实现 ``/history`` 和 ``/cluster`` 端点（Alexander Kukushkin）

  ``/history`` 端点显示 DCS 中 ``history`` 键的内容。``/cluster`` 端点显示所有集群成员以及一些服务信息，例如 pending 和计划中的重启或 switchover。


**Etcd 支持的改进**

- 在 Etcd RAFT 内部错误时重试（Alexander Kukushkin）

  当 Etcd 节点正在关闭时，它会发送 ``response code=300, data='etcdserver: server stopped'``\，这曾导致 Patroni 降级 primary。

- 不要太早放弃 Etcd 请求重试（Alexander Kukushkin）

  当存在一些网络问题时，Patroni 之前会很快耗尽 Etcd 节点列表并放弃，而不使用完整的 ``retry_timeout``\，可能导致 primary 被降级。


**缺陷修复**

- 授予 ``pg_rewind`` 用户执行权限时禁用 ``synchronous_commit`` （kremius）

  如果使用 ``synchronous_mode_strict: true`` 进行 bootstrap，由于非同步节点不可用，`GRANT EXECUTE` 语句会无限期等待。

- 修复 python 3.7 上的内存泄漏（Alexander Kukushkin）

  Patroni 使用 ``ThreadingMixIn`` 处理 REST API 请求，而 python 3.7 使每个请求生成的线程默认为非 daemon。

- 修复异步操作中的竞态条件（Alexander Kukushkin）

  之前存在 ``patronictl reinit --force`` 可能被恢复已停止 Postgres 的尝试覆盖的风险。这导致 Patroni 在 basebackup 运行时尝试启动 Postgres。

- 修复 ``postmaster_start_time()`` 方法中的竞态条件（Alexander Kukushkin）

  如果从 REST API 线程执行该方法，需要创建单独的 cursor 对象。

- 修复不提升名称包含大写字母的同步 standby 的问题（Alexander Kukushkin）

  我们将名称转换为小写，因为 Postgres 在将 ``application_name`` 与 ``synchronous_standby_names`` 中的值比较时也是这样做的。

- 启动新回调进程前，连同其所有子进程一起杀掉旧回调（Alexander Kukushkin）

  不这样做会使得难以在 bash 中实现回调，并最终可能导致两个回调同时运行。

- 修复 'start failed' 问题（Alexander Kukushkin）

  在某些条件下，尽管 Postgres 已经启动并运行，其状态可能被设置为 'start failed'。


版本 1.6.0
----------

发布于 2019-08-05

此版本增加了与 PostgreSQL 12 的兼容性，使 pg_rewind 可以在 PostgreSQL 11 及更新版本上无需超级用户即可运行，并启用了 IPv6 支持。


**新特性**

- Psycopg2 已从依赖中移除，必须单独安装（Alexander Kukushkin）

  从 2.8.0 开始，``psycopg2`` 被拆分为两个不同的软件包：``psycopg2`` 和 ``psycopg2-binary``\，它们可以同时安装到文件系统的同一位置。为减少依赖地狱问题，我们让用户选择如何安装。有几种可用选项，请参阅 :ref:`文档 <psycopg2_install_options>`。

- 与 PostgreSQL 12 的兼容性（Alexander Kukushkin）

  从 PostgreSQL 12 开始不再有 ``recovery.conf``\，所有以前的恢复参数都被转换为 `GUC <https://www.enterprisedb.com/blog/what-is-a-guc-variable>`_。为防止 ``ALTER SYSTEM SET primary_conninfo`` 或类似操作，Patroni 将解析 ``postgresql.auto.conf`` 并从中移除所有 standby 和恢复参数。Patroni 配置保持向后兼容。例如，尽管 ``restore_command`` 是 GUC，您仍然可以在 ``postgresql.recovery_conf.restore_command`` 配置节中指定它，Patroni 会为 PostgreSQL 12 将其写入 ``postgresql.conf``\。

- 使 pg_rewind 可以在 PostgreSQL 11 及更新版本上无需超级用户使用（Alexander Kukushkin）

  如果您想使用此特性，请在 Patroni 配置文件的 ``postgresql.authentication.rewind`` 配置节中定义 ``username`` 和 ``password``\。对于已经存在的集群，您需要手动创建用户并授予几个函数的 ``GRANT EXECUTE`` 权限。您可以在 PostgreSQL `文档 <https://www.postgresql.org/docs/11/app-pgrewind.html#id-1.9.5.8.8>`__ 中找到更多细节。

- 对 replica 上实际和期望的 ``primary_conninfo`` 值进行智能比较（Alexander Kukushkin）

  当您将已经存在的 primary-standby 集群转换为 Patroni 管理时，这有助于避免 replica 重启。

- IPv6 支持（Alexander Kukushkin）

  有两个主要问题。Patroni REST API 服务之前只监听 ``0.0.0.0``\，且 ``api_url`` 和 ``conn_url`` 中使用的 IPv6 IP 地址没有被正确引用。

- Kerberos 支持（Ajith Vilas、Alexander Kukushkin）

  它使得可以在 Postgres 节点之间使用 Kerberos 认证，而无需在 Patroni 配置文件中定义密码。

- 管理 ``pg_ident.conf`` （Alexander Kukushkin）

  此功能与 ``pg_hba.conf`` 类似：如果 ``postgresql.pg_ident`` 定义在配置文件或 DCS 中，Patroni 会将其值写入 ``pg_ident.conf``\；但如果定义了 ``postgresql.parameters.ident_file``\，Patroni 将假定 ``pg_ident`` 由外部管理，不更新该文件。


**REST API 的改进**

- 添加 ``/health`` 端点（Wilfried Roset）

  仅当 PostgreSQL 正在运行时才返回 HTTP 状态码。

- 添加 ``/read-only`` 和 ``/read-write`` 端点（Julien Riou）

  ``/read-only`` 端点允许读取在 replica 和 primary 之间平衡。``/read-write`` 端点是 ``/primary``\、``/leader`` 和 ``/master`` 的别名。

- 使用 ``SSLContext`` 包装 REST API socket（Julien Riou）

  使用 ``ssl.wrap_socket()`` 已弃用，且它仍允许像 TLS 1.1 这样即将弃用的协议。


**日志改进**

- 两步日志记录（Alexander Kukushkin）

  所有日志消息先写入内存队列，稍后从单独的线程异步刷新到 stderr 或文件。最大队列大小有限制（可配置）。如果达到限制，Patroni 将开始丢失日志，但这仍然比阻塞 HA 循环要好。

- 为 GET/OPTIONS API 调用启用 debug 日志记录及延迟信息（Jan Tomsa）

  这将有助于调试 HAProxy、Consul 或其他决定哪个节点是 primary/replica 的工具执行的健康检查。

- 记录 Retry 中捕获的异常（Daniel Kucera）

  当达到尝试次数或超时时，记录最终异常。这有望帮助调试与 DCS 通信失败时的某些问题。


**patronictl 的改进**

- 增强计划 switchover 和重启的对话框（Rafia Sabih）

  之前的对话框不考虑计划的操作，因此具有误导性。

- 检查配置文件是否存在（Wilfried Roset）

  当给定文件名不存在时，对配置文件进行详细说明，而不是静默忽略（这可能导致误解）。

- 为 ``EDITOR`` 添加回退值（Wilfried Roset）

  当 ``EDITOR`` 环境变量未定义时，``patronictl edit-config`` 之前会以 `PatroniCtlException` 失败。新策略是先尝试 ``editor``\，然后尝试 ``vi``\，这在大多数系统上应该都可用。


**Consul 支持的改进**

- 允许指定 Consul 一致性模式（Jan Tomsa）

  您可以在此 `链接 <https://www.consul.io/api/features/consistency.html>`__ 了解更多关于一致性模式的信息。

- 在 SIGHUP 时重载 Consul 配置（Cameron Daniel Kucera、Alexander Kukushkin）

  当有人更改 ``token`` 的值时尤其有用。


**缺陷修复**

- 修复 switchover/failover 中的边界情况（Sharoon Thomas）

  如果 REST API 不可访问且我们使用 DCS 作为回退，变量 ``scheduled_at`` 可能未定义。

- 自定义 bootstrap 期间在 ``pg_hba.conf`` 中向 localhost 开放 trust（Alexander Kukushkin）

  之前只向 unix_socket 开放，这导致大量错误：``FATAL:  no pg_hba.conf entry for replication connection from host "127.0.0.1", user "replicator"``\。

- 即使旧 leader 领先，也将同步节点视为健康（Alexander Kukushkin）

  如果 primary 失去对 DCS 的访问，它会以只读模式重启 Postgres，但其他节点可能仍能通过 REST API 访问旧 primary。这种情况会导致同步 standby 无法提升，因为旧 primary 报告的 WAL 位置领先于同步 standby。

- Standby 集群缺陷修复（Alexander Kukushkin）

  使 standby 集群中的 replica 在 standby_leader 不可访问时也能 bootstrap，以及一些其他小的修复。


版本 1.5.6
----------

发布于 2019-08-03

**新特性**

- 支持通过一组代理与 etcd 集群协作（Alexander Kukushkin）

  可能无法直接访问 etcd 集群，但可以通过一组代理访问。这种情况下，Patroni 不会执行 etcd 拓扑发现，而是通过代理主机进行轮询。该行为由 `etcd.use_proxies` 控制。

- 节点角色变化时更改回调行为（Alexander Kukushkin）

  如果角色从 `master` 或 `standby_leader` 变为 `replica`，或从 `replica` 变为 `standby_leader`，将不再调用 `on_restart` 回调，改用 `on_role_change` 回调。

- 更改启动 postgres 的方式（Alexander Kukushkin）

  使用 `multiprocessing.Process` 而不是执行自身，并使用 `multiprocessing.Pipe` 将 postmaster pid 传输给 Patroni 进程。之前我们使用管道，这会使 postmaster 进程的 stdin 保持关闭。

**缺陷修复**

- 修复 REST API 为 standby leader 返回的角色（Alexander Kukushkin）

  之前错误地返回 `replica` 而不是 `standby_leader`。

- 如果回调无法被杀掉则等待其结束（Julien Tachoires）

  Patroni 没有足够的权限终止在 `sudo` 下运行的回调脚本，这导致新回调被取消。如果运行中的脚本无法被杀掉，Patroni 将等待其完成，然后运行下一个回调。

- 减少 dcs.get_cluster 方法占用的锁时间（Alexander Kukushkin）

  由于锁被持有，DCS 的缓慢会影响 REST API 健康检查，导致误报。

- 当 `pg_wal`/`pg_xlog` 是符号链接时改进 PGDATA 的清理（Julien Tachoires）

  这种情况下，Patroni 将显式地从目标目录中删除文件。

- 移除 os.path.relpath 的不必要使用（Ants Aasma）

  它依赖能够解析工作目录，如果 Patroni 在后来从文件系统取消链接的目录中启动，这将失败。

- 与 Etcd 通信时不强制 ssl 版本（Alexander Kukushkin）

  由于某种未知原因，debian 和 ubuntu 上的 python3-etcd 不是基于该软件包的最新版本，因此它强制使用 Etcd v3 不支持的 TLSv1。我们在 Patroni 侧解决了这个问题。

版本 1.5.5
----------

发布于 2019-02-15

此版本引入了自动 reinit 前 master 的可能性，改进了 patronictl list 输出，并修复了若干缺陷。

**新特性**

- 添加对 `PATRONI_ETCD_PROTOCOL`、`PATRONI_ETCD_USERNAME` 和 `PATRONI_ETCD_PASSWORD` 环境变量的支持（Étienne M）

  之前只能在配置文件中或作为 `PATRONI_ETCD_URL` 的一部分配置它们，这并不总是方便。

- 使自动 reinit 前 master 成为可能（Alexander Kukushkin）

  如果 pg_rewind 被禁用或无法使用，前 master 可能因时间线发散而无法作为新 replica 启动。这种情况下，唯一的修复方法是清空数据目录并重新初始化。此行为可以通过设置 `postgresql.remove_data_directory_on_diverged_timelines` 来改变。设置后，Patroni 将自动清空数据目录并重新初始化前 master。

- 在 patronictl list 中显示时间线信息（Alexander Kukushkin）

  这有助于检测过期的 replica。此外，如果端口值不是默认值或同一主机上运行了多个成员，`Host` 将包含 ':{port}'。

- 创建与 $SCOPE-config 端点关联的 headless service（Alexander Kukushkin）

  "config" 端点保存集群范围的 Patroni 和 Postgres 配置、历史文件，以及最重要的一点——它持有 `initialize` 键。当 Kubernetes master 节点重启或升级时，它会移除没有 service 的端点。headless service 将防止它被移除。

**缺陷修复**

- 调整 leader watch 阻塞查询的读取超时（Alexander Kukushkin）

  根据 Consul 文档，实际响应超时会在提供的最大等待时间上增加一小段随机额外等待时间，以分散任何并发请求的唤醒时间。它最多增加 `wait / 16` 的额外时间。在我们的情况下，我们根据较大的那个添加 `wait / 15` 或 1 秒。

- 通过复制协议连接 postgres 时始终使用 replication=1（Alexander Kukushkin）

  从 Postgres 10 开始，pg_hba.conf 中 database=replication 的行不接受带有 replication=database 参数的连接。

- 不为仅 WAL 的 standby 集群将 primary_conninfo 写入 recovery.conf（Alexander Kukushkin）

  尽管 `standby_cluster` 配置中既没有定义 `host` 也没有定义 `port`，Patroni 之前还是把 `primary_conninfo` 放进了 `recovery.conf`，这毫无用处并产生大量错误。


版本 1.5.4
----------

发布于 2019-01-15

此版本实现了灵活的日志记录，并修复了若干缺陷。

**新特性**

- 日志基础设施的改进（Alexander Kukushkin、Lucas Capistrant、Alexander Anikin）

  日志配置不仅可以通过环境变量配置，还可以从 Patroni 配置文件配置。这使得可以通过更新配置并执行重载或向 Patroni 进程发送 SIGHUP 来在运行时更改日志配置。默认情况下，Patroni 将日志写入 stderr，但现在可以直接写入文件并在达到一定大小时轮转。此外，还支持自定义日期格式以及为每个 python 模块微调日志级别的可能性。

- 使 leader 选举可以考虑当前时间线（Alexander Kukushkin）

  可能发生节点认为自己是健康的，尽管它当前不在最新的已知时间线上。在某些情况下，我们希望避免提升这样的节点，这可以通过设置 `check_timeline` 参数为 `true` 来实现（默认行为保持不变）。

- 放宽对超级用户凭据的要求

  Libpq 允许在不显式指定用户名或密码的情况下打开连接。根据情况，它要么依赖 pgpass 文件，要么依赖 pg_hba.conf 中的 trust 认证方法。由于 pg_rewind 也使用 libpq，它将以相同方式工作。

- 实现通过环境变量配置 Consul Service 注册和检查间隔的可能性（Alexander Kukushkin）

  Consul 中的服务注册是在 1.5.0 中添加的，但到目前为止只能通过 patroni.yaml 开启。

**稳定性改进**

- 在自定义 bootstrap 期间将 archive_mode 设置为 off（Alexander Kukushkin）

  我们希望在集群完全可用之前避免归档 wals 和历史文件。如果自定义 bootstrap 涉及 pg_upgrade，这非常有帮助。

- 启动时加载全局配置时应用五秒退避（Alexander Kukushkin）

  这有助于避免 Patroni 刚启动时对 DCS 的过度请求。

- 减少关闭时生成的错误消息数量（Alexander Kukushkin）

  它们无害但相当烦人，有时还有点吓人。

- 创建时显式保护 recovery.conf 的 rw 权限（Lucas Capistrant）

  我们不希望除 patroni/postgres 用户之外的任何人读取此文件，因为它包含复制用户和密码。

- 将 HTTPServer 异常重定向到 logger（Julien Riou）

  默认情况下，此类异常记录到标准输出，与常规日志混在一起。

**缺陷修复**

- 移除 pg_ctl 进程上的 stderr 到 stdout 管道（Cody Coons）

  从主 Patroni 进程继承 stderr 允许与所有 patroni 日志一起看到所有 Postgres 日志。这在容器环境中非常有用，因为 Patroni 和 Postgres 日志可以使用标准工具（docker logs、kubectl 等）消费。此外，此更改修复了当 postgres 向 stderr 写入一些警告时 Patroni 无法捕获 postmaster pid 的缺陷。

- 以 Go 时间格式设置 Consul service 检查注销超时（Pavel Kirillov）

  如果没有显式的时间单位，注册会失败。

- 放宽 standby_cluster 集群配置的检查（Dmitry Dolgov、Alexander Kukushkin）

  它之前只接受字符串作为有效值，因此无法将端口指定为整数或将 create_replica_methods 指定为列表。

版本 1.5.3
----------

发布于 2018-12-03

兼容性和缺陷修复版本。

- 在 python3 下与 zookeeper 一起运行时提高稳定性（Alexander Kukushkin）

  更改 `loop_wait` 之前会导致 Patroni 与 zookeeper 断开连接并永不重新连接。

- 修复与 postgres 9.3 的兼容性（Alexander Kukushkin）

  打开复制连接时我们应指定 replication=1，因为 9.3 不理解 replication='database'。

- 确保每个 HA 循环至少刷新一次 Consul session，并改进 consul session 异常的处理（Alexander Kukushkin）

  重启本地 consul agent 会使与节点相关的所有 session 失效。不及时调用 session 刷新且不妥善处理 session 错误之前会导致 primary 降级。

版本 1.5.2
----------

发布于 2018-11-26

兼容性和缺陷修复版本。

- 与 kazoo-2.6.0 的兼容性（Alexander Kukushkin）

  为确保请求以适当的超时执行，Patroni 重新定义了 python-kazoo 模块中的 create_connection 方法。kazoo 的最新版本略微改变了 create_connection 方法的调用方式。

- 修复 Consul 集群失去 leader 时 Patroni 崩溃的问题（Alexander Kukushkin）

  崩溃是由 touch_member 方法的错误实现引起的，它应返回布尔值且不抛出任何异常。

版本 1.5.1
----------

发布于 2018-11-01

此版本实现了对永久复制槽的支持，添加了 pgBackRest 支持，并修复了若干缺陷。

**新特性**

- 永久复制槽（Alexander Kukushkin）

  永久复制槽在 failover/switchover 时被保留，也就是说，新 primary 上的 Patroni 会在提升后立即创建配置的复制槽。可以通过 `patronictl edit-config` 配置槽。初始配置也可以在 :ref:`bootstrap.dcs <yaml_configuration>` 中完成。

- 添加 pgbackrest 支持（Yogesh Sharma）

  pgBackrest 可以在现有的 $PGDATA 文件夹中恢复，这允许快速恢复，因为自上次备份以来未变化的文件会被跳过。为支持此特性，引入了新参数 `keep_data`。更多示例请参见 :ref:`replica 创建方法 <custom_replica_creation>` 部分。

**缺陷修复**

- "standby cluster" 工作流中的几个缺陷修复（Alexander Kukushkin）

  更多细节请参见 https://github.com/patroni/patroni/pull/823。

- 集群管理暂停且 DCS 不可访问时修复 REST API 健康检查（Alexander Kukushkin）

  回归在 https://github.com/patroni/patroni/commit/90cf930036a9d5249265af15d2b787ec7517cf57 中引入。

版本 1.5.0
----------

发布于 2018-09-20

此版本使 Patroni HA 集群能够在 standby 模式下运行，引入了在 Windows 上运行的实验性支持，并提供一个新的配置参数来在 Consul 中注册 PostgreSQL service。

**新特性**

- Standby 集群（Dmitry Dolgov）

  一个或多个 Patroni 节点可以组成 standby 集群，与 primary 集群并行运行（即在另一个数据中心），由从 primary 集群的 master 复制的 standby 节点组成。standby 集群中的所有 PostgreSQL 节点都是 replica；其中一个 replica 会选举自己直接从远程 master 复制，而其他 replica 以级联方式从它复制。关于此特性的更详细描述和一些配置示例可以在 :ref:`此处 <standby_cluster>` 找到。

- 在 Consul 中注册 Services（Pavel Kirillov、Alexander Kukushkin）

  如果在 consul :ref:`配置 <consul_settings>` 中启用了 `register_service` 参数，节点将注册一个名为 `scope` 且标签为 `master`、`replica` 或 `standby-leader` 的 service。

- 实验性 Windows 支持（Pavel Golub）

  从现在起可以在 Windows 上运行 Patroni，尽管 Windows 支持是全新的，尚未像 Linux 版本那样经过大量真实世界测试。我们欢迎您的反馈！

**patronictl 的改进**

- 添加 patronictl -k/--insecure 标志和对 restapi 证书的支持（Wilfried Roset）

  过去，如果 REST API 受自签名证书保护，`patronictl` 会验证失败。没有办法禁用该验证。现在可以配置 `patronictl` 完全跳过证书验证，或在配置的 :ref:`ctl: <patronictl_settings>` 配置节中提供 CA 和客户端证书。

- 从 patronictl switchover/failover 输出中排除带 nofailover 标签的成员（Alexander Anikin）

  之前，这些成员在通过 patronictl 进行交互式 switchover 或 failover 时被错误地作为候选节点提出。

**稳定性改进**

- 避免解析 pg_controldata 中非键值格式的输出行（Alexander Anikin）

  在某些情况下，pg_controldata 会输出不带冒号字符的行。这会在解析 pg_controldata 输出的 Patroni 代码中触发错误，从而掩盖实际问题；此类行通常在 pg_controldata 在常规输出之前显示的警告中发出，即二进制主版本与 PostgreSQL 数据目录的主版本不匹配时。

- 在 leader 选举期间向错误消息添加成员名称（Jan Mussler）

  leader 选举期间，Patroni 连接集群的所有已知成员并请求其状态。该状态写入 Patroni 日志并包含成员名称。之前，如果成员不可访问，错误消息不指明其名称，只包含 URL。

- 创建复制槽后立即保留 WAL 位置（Alexander Kukushkin）

  从 9.6 开始，`pg_create_physical_replication_slot` 函数提供了额外的布尔参数 `immediately_reserve`。当其设置为 `false` （也是默认值）时，槽在收到第一个客户端连接之前不会保留 WAL 位置，从而可能丢失槽创建到初始客户端连接之间时间窗口内客户端所需的某些段。

- 修复严格同步复制中的缺陷（Alexander Kukushkin）

  当使用 `synchronous_mode_strict: true` 运行时，在某些情况下 Patroni 会把 `*` 放入 `synchronous_standby_names`，将大多数复制连接的同步状态更改为 `potential`。之前，Patroni 在这种环境下无法选择同步候选节点，因为它只考虑状态为 `async` 的节点。


版本 1.4.6
----------

发布于 2018-08-14

**缺陷修复和稳定性改进**

此版本修复了 Patroni API /master 端点对非 master 节点返回 200 的关键问题。这是一个报告问题，不是真正的分脑，但在某些情况下客户端可能被引导到只读节点。

- 降级时重置 is_leader 状态（Alexander Kukushkin、Oleksii Kliukin）

  确保降级的集群成员不再在 /master API 调用上以 200 响应。

- 向 API 输出添加新的 "cluster_unlocked" 字段（Dmitry Dolgov）

  该字段指示集群是否正在运行 master。当除某个 replica 外无法查询任何其他节点时，可以使用它。

版本 1.4.5
----------

发布于 2018-08-03

**新特性**

- 应用新的 postgres 配置时改进日志记录（Don Seiler）

  Patroni 记录已更改的参数名称和值。

- Python 3.7 兼容性（Christoph Berg）

  async 是 python3.7 中的保留关键字。

- 成员关闭时在 DCS 中将状态设置为 "stopped"（Tony Sorrentino）

  这会在 "patronictl list" 命令中显示成员状态为 "stopped"。

- 过期的 postmaster.pid 与运行中的进程匹配时改进日志消息（Ants Aasma）

  之前的那条消息让人完全摸不着头脑。

- 实现 patronictl reload 功能（Don Seiler）

  在此之前，只能通过调用 REST API 或向 Patroni 进程发送 SIGHUP 信号来重载配置。

- 作为 replica 启动时从 controldata 获取并应用一些参数（Alexander Kukushkin）

  全局配置中设置的 `max_connections` 和其他一些参数的值可能低于 primary 实际使用的值；发生这种情况时，replica 无法启动，需要手动修复。Patroni 现在通过读取和应用 `pg_controldata` 中的值、启动 postgres 并设置 `pending_restart` 标志来处理此事。

- 如果设置了 LD_LIBRARY_PATH，启动 postgres 时使用它（Chris Fraser）

  启动 Postgres 时，如果设置了 PATH、LC_ALL 和 LANG 环境变量，Patroni 会传递它们。现在它对 LD_LIBRARY_PATH 也做同样的事情。如果有人在非标准位置安装了 PostgreSQL，这应该会有所帮助。

- 将 create_replica_method 重命名为 create_replica_methods（Dmitry Dolgov）

  以明确它实际上是一个数组。旧名称仍受支持以保持向后兼容。

**缺陷修复和稳定性改进**

- 修复 paused 状态下因 pg_rewind 启动 replica 的条件（Oleksii Kliukin）

  避免启动之前已执行过 pg_rewind 的 replica。

- 仅当 update_lock 成功时才以 200 响应 master 健康检查（Alexander Kukushkin）

  防止 Patroni 在 DCS 分区时在前（已降级的）master 上报告自己是 master。

- 修复与新 consul 模块的兼容性（Alexander Kukushkin）

  从 v1.1.0 开始，python-consul 更改了内部 API，并开始使用 `list` 而不是 `dict` 传递查询参数。

- 关闭时捕获 Patroni REST API 线程的异常（Alexander Kukushkin）

  这些未捕获的异常在关闭时使 PostgreSQL 保持运行。

- 仅当 Postgres 作为 master 运行时才进行崩溃恢复（Alexander Kukushkin）

  要求 `pg_controldata` 报告 'in production' 或 'shutting down' 或 'in crash recovery'。在所有其他情况下，不需要崩溃恢复。

- 改进配置错误的处理（Henning Jacobs、Alexander Kukushkin）

  可以通过更新 Patroni 配置文件并向 Patroni 进程发送 SIGHUP，在运行时更改许多参数（包括 `restapi.listen`）。此修复消除了当某些参数收到无效值时的 "restapi" 线程中晦涩难懂的异常。


版本 1.4.4
----------

发布于 2018-05-22

**稳定性改进**

- 修复 poll_failover_result 中的竞态条件（Alexander Kukushkin）

  它不直接影响 failover 或 switchover，但在某些罕见情况下，当旧 leader 释放锁时它过早报告成功，产生 'Failed over to "None"' 而不是 'Failed over to "desired-node"' 消息。

- 将 Postgres 参数名称视为不区分大小写（Alexander Kukushkin）

  大多数 Postgres 参数名称是 snake_case，但此规则有三个例外：DateStyle、IntervalStyle 和 TimeZone。Postgres 接受以不同大小写编写的这些参数（例如 timezone = 'some/tzn'）；然而，Patroni 无法在 pg_settings 中找到这些参数名称的不区分大小写匹配，因此忽略了此类参数。

- 附加到运行中的 postgres 且集群未初始化时中止启动（Alexander Kukushkin）

  Patroni 可以附加到已在运行的 Postgres 实例。必须在访问 replica 之前先在 master 节点上启动 Patroni。

- 修复 patronictl scaffold 的行为（Alexander Kukushkin）

  将 dict 对象而不是 json 编码字符串传递给 touch_member，DCS 实现将负责编码。

- pause 中更新 leader 键失败时不降级 master（Alexander Kukushkin）

  在维护期间，DCS 可能开始拒绝写请求，同时继续响应读请求。这种情况下，Patroni 之前在 DCS 中更新 leader 锁失败后会将 Postgres master 节点置于只读模式。

- Patroni 注意到新的 postmaster 进程时同步复制槽（Alexander Kukushkin）

  如果 Postgres 已重启，Patroni 必须确保复制槽列表与其预期一致。

- 退出 pause 后验证 sysid 和同步复制槽（Alexander Kukushkin）

  在 `maintenance` 模式下，数据目录可能被完全重写，因此我们必须确保 `Database system identifier` 仍属于我们的集群，且复制槽与 Patroni 的预期同步。

- 修复在带有 postmaster 锁文件的数据目录上启动未运行的 Postgres 可能失败的问题（Alexander Kukushkin）

  检测 postmaster 锁文件中的 PID 复用。如果您在 docker 容器中运行 Patroni 和 Postgres，更可能遇到此问题。

- 改进对 DCS 被意外清空的保护（Alexander Kukushkin）

  Patroni 有很多逻辑来防止这种情况下的 failover；它还可以恢复所有键；然而，在此更改之前，意外删除 /config 键会在 1 个 HA 循环周期内关闭 pause 模式。

- 遇到无效系统 ID 时不退出（Oleksii Kliukin）

  当集群系统 ID 为空或未通过验证检查时不要退出。这种情况下，集群很可能需要 reinit；在结果消息中提到这一点。避免终止 Patroni，否则 reinit 无法进行。

**与 Kubernetes 1.10+ 的兼容性**

- 添加空 subsets 检查（Cody Coons）

  Kubernetes 1.10.0+ 开始将 `Endpoints.subsets` 设置为 `None` 而不是 `[]`。

**Bootstrap 改进**

- 使删除 recovery.conf 可选（Brad Nicholson）

  如果定义了 `bootstrap.<custom_bootstrap_method_name>.keep_existing_recovery_conf` 并设置为 ``True``\，Patroni 将不移除现有的 ``recovery.conf`` 文件。当使用 pgBackRest 等工具从备份 bootstrap 时，这会生成适合您的 `recovery.conf`，非常有用。

- 允许向 basebackup 内置方法提供选项（Oleksii Kliukin）

  现在可以通过在配置中定义 `basebackup` 配置节来向内置 basebackup 方法提供选项，类似于为自定义 replica 创建方法定义的方式。区别在于 `basebackup` 配置节接受的格式：由于 pg_basebackup 同时接受 `--key=value` 和 `--key` 选项，该配置节的内容可以是键值对字典，也可以是由单元素字典组成的列表，或者只是键的列表（用于不接受值的选项）。更多示例请参见 :ref:`replica 创建方法 <custom_replica_creation>` 部分。


版本 1.4.3
----------

发布于 2018-03-05

**日志改进**

- 使日志级别可通过环境变量配置（Andy Newton、Keyvan Hedayati）

  `PATRONI_LOGLEVEL`- 设置总体日志级别
  `PATRONI_REQUESTS_LOGLEVEL`- 为所有 HTTP 请求（例如 Kubernetes API 调用）设置日志级别
  请参阅 `Python 日志文档 <https://docs.python.org/3.6/library/logging.html#levels>`_ 了解可能的日志级别名称

**稳定性改进和缺陷修复**

- watch 超时时不重新发现 etcd 集群拓扑（Alexander Kukushkin）

  如果 etcd 配置中只有一个主机且恰好这个主机不可访问，Patroni 之前会开始集群拓扑发现并永远无法成功。相反，它应该直接切换到下一个可用节点。

- 自定义 bootstrap 后将 bootstrap.pg_hba 的内容写入 pg_hba.conf（Alexander Kukushkin）

  现在它的行为与使用 `initdb` 的常规 bootstrap 类似。

- 单用户模式等待用户输入而永不完成（Alexander Kukushkin）

  回归在 https://github.com/patroni/patroni/pull/576 中引入。


版本 1.4.2
----------

发布于 2018-01-30

**patronictl 的改进**

- 将计划 failover 重命名为计划 switchover（Alexander Kukushkin）

  Failover 和 switchover 功能在 1.4 版本中被分离，但 `patronictl list` 之前仍报告 `Scheduled failover` 而不是 `Scheduled switchover`。

- 显示 pending 重启信息（Alexander Kukushkin）

  为应用某些配置更改，有时需要重启 postgres。Patroni 已在 REST API 和向 DCS 写入节点状态时给出提示，但没有简单的方法来显示它。

- 使 show-config 与配置文件中的 cluster_name 一起工作（Alexander Kukushkin）

  它的工作方式类似于 `patronictl edit-config`。

**稳定性改进**

- 避免在 bootstrap 期间调用 pg_controldata（Alexander Kukushkin）

  在 initdb 或自定义 bootstrap 期间，存在 pgdata 非空但 pg_controldata 尚未写入的时间窗口。这种情况下，pg_controldata 调用会以错误消息失败。

- 处理 psutil 抛出的异常（Alexander Kukushkin）

  每次调用 `cmdline()` 方法时都会读取并解析 cmdline。被检查的进程可能已经消失，这种情况下会抛出 `NoSuchProcess`。

**Kubernetes 支持改进**

- 不吞掉 k8s API 的错误（Alexander Kukushkin）

  对 Kubernetes API 的调用可能因多种原因失败。某些情况下应重试此类调用，其他情况下我们应记录错误消息和异常堆栈跟踪。此更改将有助于调试 Kubernetes 权限问题。

- 更新 Kubernetes 示例 Dockerfile 以从 master 分支安装 Patroni（Maciej Szulik）

  之前它使用 `feature/k8s`，这已过时。

- 添加适当的 RBAC 以在 k8s 上运行 patroni（Maciej Szulik）

  添加分配给集群 pod 的 Service account、只持有必要权限的 role，以及连接 Service account 和 Role 的 rolebinding。


版本 1.4.1
----------

发布于 2018-01-17

**patronictl 中的修复**

- 在建议的 failover 目标成员列表中不显示当前 leader（Alexander Kukushkin）

  集群中存在 leader 时 patronictl failover 仍可工作，且它应被排除在可以进行 failover 的成员列表之外。

- 使 patronictl switchover 与旧版 Patroni api 兼容（Alexander Kukushkin）

  如果 POST /switchover REST API 调用以状态码 501 失败，它将再执行一次，但针对 /failover 端点。


版本 1.4
--------

发布于 2018-01-10

此版本添加了使用 Kubernetes 作为 DCS 的支持，允许 Patroni 作为云原生 agent 在 Kubernetes 中运行，而无需额外部署 Etcd、Zookeeper 或 Consul。

**升级须知**

通过 pip 安装 Patroni 将不再附带依赖项（例如 Etcd、Zookeper、Consul 或 Kubernetes 的库，或 AWS 支持）。要启用它们，需要在 pip install 命令中显式列出，例如 `pip install patroni[etcd,kubernetes]`。

**Kubernetes 支持**

实现基于 Kubernetes 的 DCS。使用端点的元数据来存储配置和 leader 键。pod 定义中的元数据字段用于存储成员相关数据。
除了使用 Endpoints，Patroni 还支持 ConfigMaps。您可以在文档的 :ref:`Kubernetes 章节 <kubernetes>` 中找到关于此特性的更多信息。

**稳定性改进**

- 将 postmaster 进程提取到单独的对象中（Ants Aasma）

  该对象通过 pid 和启动时间来标识运行中的 postmaster 进程，并简化了对 postmaster 在背后被重启或 postgres 目录从文件系统消失等情况的检测（和解决）。

- 最小化 Patroni 在每个 HA 循环周期内发出的 SELECT 数量（Alexander Kukushkin）

  每次 HA 循环迭代，Patroni 都需要知道恢复状态和绝对 wal 位置。从现在起，Patroni 将只运行一个 SELECT 来获取此信息，而不是在 replica 上运行两个、在 master 上运行三个。

- 仅当我们拥有锁时才在关闭时移除 leader 键（Ants Aasma）

  无条件移除之前会产生不必要且具有误导性的异常。

**patronictl 的改进**

- 向 patronictl 添加 version 命令（Ants Aasma）

  它将显示已安装 Patroni 的版本和正在运行的 Patroni 实例的版本（如果指定了集群名称）。

- 使某些 patronictl 命令的 cluster_name 参数可选（Alexander Kukushkin、Ants Aasma）

  如果 patronictl 使用定义了 ``scope`` 的常规 Patroni 配置文件，它就能工作。

- 显示计划 switchover 和维护模式的信息（Alexander Kukushkin）

  在此之前，只能从 Patroni 日志或直接从 DCS 获取此信息。

- 改进 ``patronictl reinit`` （Alexander Kukushkin）

  有时当 Patroni 忙于其他操作（即尝试启动 postgres）时，``patronictl reinit`` 拒绝继续。`patronictl` 不提供任何命令来取消此类长时间运行的操作，唯一（危险的）变通方法是手动删除数据目录。新的 `reinit` 实现会先强制取消其他长时间运行的操作，然后再进行 reinit。

- 在 ``patronictl pause`` 和 ``patronictl resume`` 中实现 ``--wait`` 标志（Alexander Kukushkin）

  它将使 ``patronictl`` 等待，直到集群中的所有节点确认所请求的操作。
  这种行为的实现方式是：在 DCS 中为每个节点暴露 ``pause`` 标志，并通过 REST API 暴露。

- 将 ``patronictl failover`` 重命名为 ``patronictl switchover`` （Alexander Kukushkin）

  之前的 ``failover`` 实际上只能执行 switchover；在没有 leader 的集群中它拒绝继续。

- 改变 ``patronictl failover`` 的行为（Alexander Kukushkin）

  即使没有 leader，它也能工作，但那样您必须显式指定一个应成为新 leader 的节点。

**暴露时间线和历史信息**

- 在 DCS 中并通过 API 暴露当前时间线（Alexander Kukushkin）

  为集群的每个成员存储当前时间线信息。此信息可通过 API 访问并存储在 DCS 中。

- 在 DCS 的 /history 键中存储提升历史（Alexander Kukushkin）

  此外，在 DCS 的 /history 键中存储带有相应提升时间戳的时间线历史，并在每次提升时更新它。

**添加获取同步和异步 replica 的端点**

- 添加新的 /sync 和 /async 端点（Alexander Kukushkin、Oleksii Kliukin）

 这些端点（也可以作为 /synchronous 和 /asynchronous 访问）只对同步和异步 replica 返回 200（排除标记为 `noloadbalance` 的节点）。

**允许 Etcd 使用多个主机**

- 向 Etcd 配置添加新的 `hosts` 参数（Alexander Kukushkin）

  该参数应包含用于发现和填充正在运行的 etcd 集群成员列表的初始主机列表。如果由于某种原因工作中发现的主机列表耗尽（该列表中没有可用主机），Patroni 将回到 `hosts` 参数中的初始列表。


版本 1.3.6
----------

发布于 2017-11-10

**稳定性改进**

- 检查 postgres 是否运行时验证进程启动时间（Ants Aasma）

  在不清理 postmaster.pid 的崩溃之后，可能存在具有相同 pid 的新进程，导致 is_running() 出现误报，进而引发各种不良行为。

- 丢失数据目录时在 bootstrap 前关闭 postgresql（ainlolcat）

  当 master 上的数据目录被强制移除时，postgres 进程可能仍会存活一段时间，阻止在该前 master 位置创建的 replica 启动或复制。
  此修复使 Patroni 缓存 postmaster pid 及其启动时间，如果对应的数据目录被移除后旧 postmaster 仍在运行，则终止它。

- postgres master 死亡时以单用户模式进行崩溃恢复（Alexander Kukushkin）

  如果 postgres 没有干净关闭，立即以 standby 启动是不安全的，也无法运行 ``pg_rewind``\。
  单用户崩溃恢复仅在启用 ``pg_rewind`` 或当前没有 master 时触发。

**Consul 改进**

- 使可以为 Consul 提供 datacenter 配置（Vilius Okockis、Alexander Kukushkin）

  之前，Patroni 总是与其所在主机的 datacenter 通信。

- 始终在 X-Consul-Token http 头中发送 token（Alexander Kukushkin）

  如果在 Patroni 配置中定义了 ``consul.token``\，我们将始终在 'X-Consul-Token' http 头中发送它。
  python-consul 模块试图与 Consul REST API "保持一致"，而 REST API 不接受 token 作为 `session API <https://www.consul.io/api/session.html>`__ 的查询参数，但它仍然可以与 'X-Consul-Token' 头一起工作。

- 如果提供的 session TTL 值小于可能的最小值则进行调整（Stas Fomin、Alexander Kukushkin）

  可能发生 Patroni 配置中提供的 TTL 小于 Consul 支持的最小值。这种情况下，Consul agent 无法创建新 session。
  没有 session，Patroni 无法在 Consul KV store 中创建成员和 leader 键，导致集群不健康。

**其他改进**

- 通过环境变量 ``PATRONI_LOGFORMAT`` 定义自定义日志格式（Stas Fomin）

  如果时间戳和其他类似字段已由系统 logger 添加（通常在 Patroni 作为服务运行时），允许在 Patroni 日志中禁用它们。

版本 1.3.5
----------

发布于 2017-10-12

**缺陷修复**

- 如果数据目录被移除，将角色设置为 'uninitialized'（Alexander Kukushkin）

  如果节点之前作为 master 运行，这会阻止 failover。

**稳定性改进**

- 如果尝试启动 postgres 失败，尝试以单用户模式运行 postmaster（Alexander Kukushkin）

  通常此类问题发生在作为 master 运行的节点被终止且时间线发散时。
  如果 ``recovery.conf`` 定义了 ``restore_command``\，postgres 极有可能中止启动并保持 controldata 不变。
  这使得无法使用需要干净关闭的 ``pg_rewind``\。

**Consul 改进**

- 使创建 session 时可以指定健康检查（Alexander Kukushkin）

  如果未指定，Consul 将使用 "serfHealth"。一方面它允许快速检测隔离的 master，但另一方面它使 Patroni 无法容忍短暂的网络延迟。

**缺陷修复**

- 修复 Python 3 上的 watchdog（Ants Aasma）

  对 ioctl() 调用接口的误解。如果 mutable=False，fcntl.ioctl() 实际上会把 arg buffer 返回回来。
  这在 Python2 上偶然正常工作，因为 int 和 str 比较不会返回错误。
  错误报告实际上是通过在 Python2 上抛出 IOError、在 Python3 上抛出 OSError 来完成的。

版本 1.3.4
----------

发布于 2017-09-08

**不同的 Consul 改进**

- 将 consul token 作为头传递（Andrew Colin Kissa）

  头现在是向 consul `API <https://www.consul.io/api/index.html#authentication>`__ 传递 token 的首选方式。


- Consul 的高级配置（Alexander Kukushkin）

  可以指定 ``scheme``\、``token``\、客户端和 ca 证书 :ref:`详情 <consul_settings>`。

- 与 python-consul-0.7.1 及更高版本的兼容性（Alexander Kukushkin）

  新的 python-consul 模块更改了一些方法的签名。

- "Could not take out TTL lock" 消息从未被记录（Alexander Kukushkin）

  不是严重缺陷，但缺少适当的日志记录会在出现问题时使排查复杂化。


**使用 quote_ident 引用 synchronous_standby_names**

- 将 ``synchronous_standby_names`` 写入 ``postgresql.conf`` 时，其值必须被引用（Alexander Kukushkin）

  如果引用不当，PostgreSQL 将有效地禁用同步复制并继续工作。


**围绕 pause 状态的各种缺陷修复，大多与 watchdog 有关** （Alexander Kukushkin）

- watchdog 未激活时不发送 keepalive
- 避免在 pause 模式下激活 watchdog
- 在 pause 模式下设置正确的 postgres 状态
- postgres 停止时不尝试从 API 运行查询


版本 1.3.3
----------

发布于 2017-08-04

**缺陷修复**

- 即使启用了 synchronous_mode_strict，提升后不久同步复制也会被禁用（Alexander Kukushkin）
- 从备份恢复后缺少 ``pg_ident.conf`` 时创建空文件（Alexander Kukushkin）
- 在 ``pg_hba.conf`` 中向所有数据库开放访问，而不仅仅是 postgres（Franco Bellagamba）


版本 1.3.2
----------

发布于 2017-07-31

**缺陷修复**

- patronictl edit-config 与 ZooKeeper 不兼容（Alexander Kukushkin）


版本 1.3.1
----------

发布于 2017-07-28

**缺陷修复**

- 由于 ``_MemberStatus`` 的更改，通过 API 的 failover 被破坏（Alexander Kukushkin）


版本 1.3
--------

发布于 2017-07-27

版本 1.3 添加了自定义 bootstrap 的可能性，显著改进了 pg_rewind 的支持，增强了同步模式支持，向 patronictl 添加了配置编辑功能，并实现了 Linux 上的 watchdog 支持。
此外，这是第一个能正确与 PostgreSQL 10 配合的版本。

**升级须知**

新版本 Patroni 没有已知的兼容性问题。1.2 版本的配置应该无需任何更改即可工作。可以通过安装新软件包并重新启动 Patroni（将导致 PostgreSQL 重启），或者先将 Patroni 置于 :ref:`pause 模式 <pause>`，然后在集群的所有节点上重启 Patroni（处于 pause 模式的 Patroni 不会尝试停止/启动 PostgreSQL），最后在结束时解除 pause 模式来升级。

**自定义 Bootstrap**

- 使集群 bootstrap 过程可配置（Alexander Kukushkin）

  初始化集群中的第一个节点时，允许使用自定义 bootstrap 脚本而不是 ``initdb``\。
  bootstrap 命令接收集群名称和数据目录路径。生成的集群可以配置为执行恢复，从而可以从备份 bootstrap 并执行时间点恢复。关于此特性的更详细描述请参阅 :ref:`文档页面 <custom_bootstrap>`。

**更智能的 pg_rewind 支持**

-  通过查看与当前 master 的时间线差异来决定是否运行 pg_rewind（Alexander Kukushkin）

  之前，Patroni 有一组固定的条件来触发 pg_rewind，即在启动前 master 时、对集群中每个其他节点切换到指定节点时，或存在带 nofailover 标签的 replica 时。所有这些情况都有一个共同点：某些 replica 可能领先于新 master。在某些情况下，pg_rewind 什么都没做；在另一些情况下，需要时它却没有运行。Patroni 不再依赖这个有限的规则列表，而是比较 master 和 replica 的 WAL 位置（使用流式复制协议），以可靠地决定 replica 是否需要 rewind。

**同步复制严格模式**

-  通过添加严格模式增强同步复制支持（James Sewell、Alexander Kukushkin）

  通常，当启用 ``synchronous_mode`` 且 master 上没有连接 replica 时，Patroni 会禁用同步复制以保持 master 可写。``synchronous_mode_strict`` 选项改变了这一点：设置后，在没有 replica 的情况下 Patroni 不会禁用同步复制，从而有效地阻塞所有向 master 写入数据的客户端。除了同步模式防止自动 failover 导致数据丢失的保证之外，严格模式还确保每次写入要么持久存储在两个节点上，要么在集群只有一个节点时根本不发生。

**使用 patronictl 编辑配置**

- 向 patronictl 添加配置编辑功能（Ants Aasma、Alexander Kukushkin）

  为 patronictl 添加编辑存储在 DCS 中的动态集群配置的能力。支持从命令行指定参数/值、调用 $EDITOR，或从 yaml 文件应用配置。

**Linux watchdog 支持**

- 为 Linux 实现 watchdog 支持（Ants Aasma）

  支持 Linux 软件 watchdog，以便在 Patroni 未运行或不响应（例如由于高负载）时重启节点。Linux 软件 watchdog 会重启不响应的节点。可以从 Patroni 配置的 watchdog 配置节配置要使用的 watchdog 设备（默认 `/dev/watchdog`）和模式（on、automatic、off）。您可以从 :ref:`watchdog 文档 <watchdog>` 获取更多信息。

**添加对 PostgreSQL 10 的支持**

- Patroni 与目前发布的所有 PostgreSQL 10 beta 版本兼容，我们期望它在 PostgreSQL 10 发布时也兼容。

**与 PostgreSQL 相关的次要改进**

- 通过 Patroni 配置文件或 DCS 中的动态配置定义 pg_hba.conf（Alexander Kukushkin）

  允许在配置的 ``postgresql`` 配置节的 ``pg_hba`` 子配置节中定义 ``pg_hba.conf`` 的内容。这简化了在多个节点上管理 ``pg_hba.conf`` 的过程，因为只需在 DCS 中定义一次，而不必登录到每个节点手动更改并重载配置。

  定义后，此配置节的内容将完全替换当前的 ``pg_hba.conf``\。如果设置了 PostgreSQL 的 ``hba_file`` 参数，Patroni 将忽略它。

- 支持通过 UNIX socket 连接到本地 PostgreSQL 集群（Alexander Kukushkin）

  在 Patroni 配置的 ``postgresql`` 配置节中添加 ``use_unix_socket`` 选项。当设置为 true 且 PostgreSQL 的 ``unix_socket_directories`` 选项非空时，Patroni 使用其第一个值连接到本地 PostgreSQL 集群。如果未定义 ``unix_socket_directories``\，Patroni 将假定其默认值，并完全省略 PostgreSQL 连接字符串中的 ``host`` 参数。

- 支持在重载时更改 superuser 和 replication 凭据（Alexander Kukushkin）

- 支持将配置文件存储在 PostgreSQL 数据目录之外（@jouir）

  在 ``postgresql`` 配置中添加新的配置指令 ``config_dir``\。
  它默认为数据目录，并且必须可由 Patroni 写入。

**缺陷修复和稳定性改进**

- 处理 EtcdEventIndexCleared 和 EtcdWatcherCleared 异常（Alexander Kukushkin）

  当 watch 操作被 Etcd 结束时，通过避免无用的重试来更快地恢复。

- 消除 Etcd 失败时的错误空转并减少日志刷屏（Ants Aasma）

  避免在第二次及后续 Etcd 连接失败时立即重试并在日志中输出堆栈跟踪。

- 派生 PostgreSQL 进程时导出 locale 变量（Oleksii Kliukin）

  对于使用 NLS 构建的 PostgreSQL，避免非英语 locale 下的 `postmaster became multithreaded during startup` 致命错误。

- 删除复制槽时的额外检查（Alexander Kukushkin）

  在某些情况下，WAL sender 会阻止 Patroni 删除复制槽。

- 将复制槽名称截断为 63（NAMEDATALEN - 1）个字符以符合 PostgreSQL 命名规则（Nick Scott）

- 修复导致 Patroni 向 PostgreSQL 集群打开多余连接的竞态条件（Alexander Kukushkin）

- 节点以空数据目录重启时释放 leader 键（Alex Kerney）

- 在没有 leader 的情况下运行 bootstrap 时设置异步执行器为忙（Alexander Kukushkin）

  如果不这样做，当 Patroni 被一个不要求集群中存在 leader 的 bootstrap 方法 bootstrap 时继续正常业务，可能会产生声称节点属于不同集群的错误。

- 改进 WAL-E replica 创建方法（Joar Wandborg、Alexander Kukushkin）。

  - 解析 WAL-E 基础备份时使用 csv.DictReader，接受带空格分隔日期和时间的 ISO 日期。
  - 支持从 replica 获取当前 WAL 位置以估算需要恢复的 WAL 量。之前，代码调用只在 master 节点上可用的系统信息函数。


版本 1.2
--------

发布于 2016-12-13

此版本在同步复制的处理上引入了显著改进，使启动过程和 failover 更加可靠，添加了 PostgreSQL 9.6 支持，并修复了大量缺陷。
此外，包括这些发布说明在内的文档已移至 https://patroni.readthedocs.io。

**同步复制**

- 添加同步复制支持。（Ants Aasma）

  添加新的配置变量 ``synchronous_mode``\。启用后，只要有健康的 standby 可用，Patroni 就会管理 ``synchronous_standby_names`` 以启用同步复制。启用同步模式后，Patroni 只会在 master 故障时自动 failover 到当时正在同步复制的 standby。这实际上意味着在这种情况下不会丢失用户可见的事务。详细描述和实现细节请参见
  :ref:`特性文档 <synchronous_mode>`。

**可靠性改进**

- 当 PostgreSQL 不完全健康时，不尝试更新存储在 ``leader optime`` 键中的 leader 位置。leader 键更新失败时立即降级。（Alexander Kukushkin）

- 将不健康的节点从克隆新 replica 的目标列表排除。（Alexander Kukushkin）

- 为 Consul 实现类似 Etcd 的重试和超时策略。（Alexander Kukushkin）

- 使 ``--dcs`` 和 ``--config-file`` 适用于 ``patronictl`` 中的所有选项。（Alexander Kukushkin）

- 将所有 postgres 参数写入 postgresql.conf。（Alexander Kukushkin）

  它允许仅用 ``pg_ctl`` 启动由 Patroni 配置的 PostgreSQL。

- 配置中没有用户时避免异常。（Kirill Pushkin）

- 允许暂停不健康的集群。在此修复之前，如果 ``patronictl`` 尝试执行 pause 的节点不健康，它会退出。（Alexander Kukushkin）

- 改进 leader watch 功能。（Alexander Kukushkin）

  之前，replica 总是 watch leader 键（睡眠直到超时或 leader 键变化）。通过此更改，它们只在 replica 的 PostgreSQL 处于 ``running`` 状态时 watch，而不是在停止/启动或重启 PostgreSQL 时。

- 作为 PID 1 处理 SIGCHILD 时避免竞态条件。（Alexander Kukushkin）

  之前在 Docker 容器中运行时可能发生竞态条件，因为 Patroni 中的同一个进程既产生了新进程又处理了它们的 SIGCHILD。此更改对 Patroni 使用 fork/exec，并让原来的 PID 1 进程负责处理子进程的信号。

- 修复 WAL-E restore。（Oleksii Kliukin）

  之前，WAL-E restore 使用 ``no_master`` 标志来完全避免咨询 master，使 Patroni 总是选择从 WAL 恢复而不是 ``pg_basebackup``\。此更改将其恢复为 ``no_master`` 的原始含义，即 master 未运行时可以选择 Patroni WAL-E restore 作为复制方法。
  后者通过检查传递给方法的连接字符串来验证。此外，它使重试机制更健壮，并处理了其他细节。

- 实现异步 DNS 解析器缓存。（Alexander Kukushkin）

  避免在 DNS 临时不可用时（例如由于节点收到过多流量）失败。

- 实现 starting 状态和 master 启动超时。（Ants Aasma、Alexander Kukushkin）

  之前 ``pg_ctl`` 等待一个超时，然后愉快地继续，认为 PostgreSQL 在运行。这导致 PostgreSQL 在列表中显示为运行而实际上并未运行，并引起竞态条件，导致 failover、崩溃恢复，或被 failover 中断的崩溃恢复以及错过的 rewind。
  此更改添加了 ``master_start_timeout`` 参数，并为 HA 主循环引入了一个新状态：``starting``\。当 ``master_start_timeout`` 为 0 时，master 崩溃后只要存在 failover 候选节点，我们就会立即 failover。否则，Patroni 会在尝试在 master 上启动 PostgreSQL 后等待超时时间；超时到期时，如果可能则进行 failover。在 master 崩溃期间，即使在超时到期之前，手动 failover 请求也会被处理。

  为 ``restart`` API 端点和 ``patronictl`` 引入 ``timeout`` 参数。设置后，如果重启时间超过超时值，PostgreSQL 被视为不健康，其他节点有资格获取 leader 锁。

- 修复 pause 模式下 ``pg_rewind`` 的行为。（Ants Aasma）

  当 Patroni 认为需要 rewind 但 rewind 不可能（即不存在 ``pg_rewind``\）时，避免在 pause 模式下不必要地重启。如果 ``pg_rewind`` 相关的 Patroni 配置节中缺少 ``superuser`` 认证，则回退到 ``superuser``\（默认 OS 用户）的默认 ``libpq`` 值。

- 序列化回调执行。新回调即将运行时杀掉前一个同类型回调。修复运行回调时产生僵尸进程的问题。（Alexander Kukushkin）

- 当 DCS 中设置了 leader 键但更新此 leader 键失败时，避免提升前 master。（Alexander Kukushkin）

  这避免了当前 master 与 Etcd 及其他允许 "不一致读取" 的 DCS 中的少数节点分区时继续保留其角色的问题。

**其他**

- 在 bootstrap 上添加 ``post_init`` 配置选项。（Alejandro Martínez）

  Patroni 将在为新集群运行 ``initdb`` 并启动 PostgreSQL 后立即调用此选项的脚本参数。脚本接收带有 ``superuser`` 的连接 URL，
  并将 ``PGPASSFILE`` 设置为指向包含密码的 ``.pgpass`` 文件。如果脚本失败，Patroni 初始化也会失败。它对于在
  新集群中添加新用户或创建扩展很有用。

- 实现 PostgreSQL 9.6 支持。（Alexander Kukushkin）

  使用 ``wal_level = replica`` 作为 ``hot_standby`` 的同义词，避免在两者之间切换时出现 pending_restart 标志。（Alexander Kukushkin）

**文档改进**

- 添加 Patroni 主 `循环工作流图 <https://raw.githubusercontent.com/patroni/patroni/master/docs/ha_loop_diagram.png>`__。（Alejandro Martínez、Alexander Kukushkin）

- 改进 README，添加 Helm chart 和发布说明的链接。（Lauri Apple）

- 将 Patroni 文档移至 ``Read the Docs``\。最新文档可在 https://patroni.readthedocs.io 获取。（Oleksii Kliukin）

  使文档易于从不同设备（包括智能手机）查看和搜索。

- 将软件包移至语义化版本控制。（Oleksii Kliukin）

  Patroni 将遵循 major.minor.patch 版本模式，避免为小的但关键的缺陷修复发布新的 minor 版本。我们将只为 minor 版本发布发布说明，其中包括所有 patch。


版本 1.1
--------

发布于 2016-09-07

此版本通过引入 pause 模式改进了 Patroni 集群的管理，通过计划重启和条件重启简化维护，使 Patroni 与 Etcd 或 ZooKeeper 的交互更加健壮，并大幅增强了 patronictl。

**升级须知**

从 1.0 以下版本升级时，请阅读 1.0 发布说明中关于凭据和配置格式变更的内容。

**Pause 模式**

- 引入 pause 模式，以暂时将 Patroni 与 PostgreSQL 实例的管理分离（Murat Kabilov、Alexander Kukushkin、Oleksii Kliukin）。

  之前，必须向 Patroni 发送 SIGKILL 信号才能在不终止 PostgreSQL 的情况下停止它。新的 pause 模式在不终止 Patroni 的情况下，让 Patroni 在整个集群范围内与 PostgreSQL 分离。它类似于 Pacemaker 中的维护模式。Patroni 仍然负责更新 DCS 中的 member 和 leader 键，但在此过程中不会启动、停止或重启 PostgreSQL 服务器。有少数例外，例如，手动 failover、重新初始化和重启仍然被允许。您可以阅读 :ref:`此特性的详细描述 <pause>`。

此外，patronictl 支持新的 ``pause`` 和 ``resume`` 命令来切换 pause 模式。

**计划重启和条件重启**

- 为重启 API 命令添加条件（Oleksii Kliukin）

  此更改增强了 Patroni 重启，添加了几个可以验证以决定是否执行重启的条件。这些条件包括仅在 PostgreSQL 角色为 master 或 replica 时重启、检查 PostgreSQL 版本号，或仅在需要重启以应用配置更改时重启。

- 添加计划重启（Oleksii Kliukin）

  现在可以安排在将来某个时间重启。每个节点只支持一个计划重启。如果不再需要计划重启，可以将其清除。支持计划重启和条件重启的组合，例如，可以安排在夜间进行 PostgreSQL 次要版本升级，只重启运行过时次要版本的实例，而无需在管理脚本中添加 postgres 特定的逻辑。

- 为 patronictl 添加条件重启和计划重启支持（Murat Kabilov）。

  patronictl restart 支持几个新选项。还有 patronictl flush 命令用于清理计划的操作。

**健壮的 DCS 交互**

- 根据 loop_wait 设置 Kazoo 超时（Alexander Kukushkin）

  最初，ping_timeout 和 connect_timeout 值是根据协商的会话超时计算出来的。没有考虑 Patroni 的 loop_wait。结果，单次重试可能花费比会话超时更长的时间，迫使 Patroni 释放锁并降级。

  此更改将 ping 和 connect 超时设置为 loop_wait 值的一半，加快了连接问题的检测速度，并在失去锁之前留出足够的时间重试连接尝试。

- 仅在原始请求成功后更新 Etcd 拓扑（Alexander Kukushkin）

  将对客户端已知的 Etcd 拓扑的更新推迟到原始请求之后。在检索集群拓扑时，根据已知的 Etcd 集群节点数量实现重试超时。这使我们的客户端更倾向于获取请求的结果，而不是获得最新的节点列表。

  这两项更改使 Patroni 在网络问题面前与 DCS 的连接更加健壮。

**Patronictl、监控和配置**

- 通过 API 返回流式复制的 replica 信息（Feike Steenbergen）

  之前，没有可靠的方法让 Patroni 查询无法流式传输更改的 PostgreSQL 实例（例如由于连接问题）。此更改通过 /patroni 端点公开 pg_stat_replication 的内容。

- 添加 patronictl scaffold 命令（Oleksii Kliukin）

  添加一个在 Etcd 中创建集群结构的命令。集群使用用户指定的 sysid 和 leader 创建，并且 leader 和 member 键都设置为持久化。此命令可用于创建所谓的无 master 配置，即仅由 replica 组成的 Patroni 集群从不知晓 Patroni 的外部 master 节点复制数据。随后，可以删除 leader 键，提升其中一个 Patroni 节点，并用基于 Patroni 的 HA 集群替换原始 master。

- 添加配置选项 ``bin_dir`` 来定位 PostgreSQL 二进制文件（Ants Aasma）

  当 Linux 发行版支持同时安装多个 PostgreSQL 版本时，能够显式指定 PostgreSQL 二进制文件的位置是很有用的。

- 允许使用 ``custom_conf`` 覆盖配置文件路径（Alejandro Martínez）

  允许自定义配置文件路径，该文件将不受 Patroni 管理，:ref:`详情 <postgresql_settings>`。

**缺陷修复和代码改进**

- 使 Patroni 兼容 PostgreSQL 10 及以上版本的新版本号格式（Feike Steenbergen）

  确保 Patroni 在根据 PostgreSQL 版本执行条件重启时能够理解两位数的版本号。

- 使用 pkgutil 查找 DCS 模块（Alexander Kukushkin）

  使用专用的 python 模块而不是手动遍历目录来查找 DCS 模块。

- 启动 Patroni 时始终调用 on_start 回调（Alexander Kukushkin）

  之前，Patroni 在附加到已以正确角色运行的节点时不会调用任何回调。由于回调通常用于路由客户端连接，这可能导致运行中的节点无法注册到连接路由方案中。通过此修复，即使附加到已运行的节点，Patroni 也会调用 on_start 回调。

- 不删除活动的复制槽（Murat Kabilov、Oleksii Kliukin）

  避免删除 master 上活动的物理复制槽。PostgreSQL 无论如何都无法删除此类槽。此更改使得可以在 master 上运行不受 Patroni 管理的 replica/消费者。

- 在 PostgreSQL 实例启动期间关闭 Patroni 连接（Alexander Kukushkin）

  当 PostgreSQL 节点启动时，强制 Patroni 关闭所有以前的连接。避免在 postmaster 被 SIGKILL 杀死时重用旧连接的陷阱。

- 从 member 名称构造槽名称时替换无效字符（Ants Aasma）

  确保不符合槽命名规则的 standby 名称不会导致槽创建和 standby 启动失败。将槽名称中的短横线替换为下划线，将槽名称中不允许的所有其他字符替换为其 unicode 码点。

版本 1.0
--------

发布于 2016-07-05

此版本引入了全局动态配置，允许对整个 HA 集群的 PostgreSQL 和 Patroni 配置参数进行动态更改。它还带来了大量的缺陷修复。

**升级须知**

从 v0.90 或更低版本升级时，请始终在所有 master 之前升级所有 replica。由于我们不再在 DCS 中存储复制凭据，旧的 replica 将无法连接到新的 master。

**动态配置**

- 实现动态全局配置（Alexander Kukushkin）

  引入新的 REST API 端点 /config，以提供应针对整个 HA 集群（master 和所有 replica）全局设置的 PostgreSQL 和 Patroni 配置参数。这些参数在 DCS 中设置，在许多情况下无需中断 PostgreSQL 或 Patroni 即可应用。当某些值需要重启 PostgreSQL 时，Patroni 会设置一个称为 "pending restart" 的特殊标志，可通过 API 看到。在这种情况下，应通过 API 手动发出重启。

  Patroni 收到 SIGHUP 或向 /reload 发送 POST 将使其重新读取配置文件。

  关于哪些参数可以更改以及不同配置源的处理顺序，请参阅 :ref:`Patroni 配置 <patroni_configuration>`。

  配置文件格式与 v0.90 相比 *已更改*。Patroni 仍然兼容旧配置文件，但为了利用 bootstrap 参数，需要更改它。建议用户参考 :ref:`动态配置文档页面 <dynamic_configuration>` 进行更新。

**更灵活的配置**

- 使 Patroni 连接的 postgresql 配置和数据库名称可配置（Misja Hoebe）

  引入 `database` 和 `config_base_name` 配置参数。除其他外，这使得可以运行 PipelineDB 和其他 PostgreSQL 分支的 Patroni。

- 实现通过环境配置某些 Patroni 配置参数的可能性（Alexander Kukushkin）

  这些参数包括 scope、node 名称和 namespace，以及 secrets，使在动态环境（即 Kubernetes）中运行 Patroni 更加容易。更多详情请参阅 :ref:`受支持的环境变量 <environment>`。

- 更新内置的 Patroni docker 容器以利用基于环境的配置（Feike Steenbergen）。

- 为 Patroni docker 镜像添加 ZooKeeper 支持（Alexander Kukushkin）

- 拆分 ZooKeeper 和 Exhibitor 配置选项（Alexander Kukushkin）

- 让 patronictl 复用 Patroni 的代码来读取配置（Alexander Kukushkin）

  这使 patronictl 能够利用基于环境的配置。

- 在 primary_conninfo 中将应用名称设置为节点名称（Alexander Kukushkin）

  这简化了给定节点的同步复制的识别和配置。

**稳定性、安全性和可用性改进**

- 备份恢复进行中时重置 sysid 且不调用 pg_controldata（Alexander Kukushkin）

  此更改减少了在从备份对该节点进行耗时初始化期间由 Patroni API 健康检查产生的噪音量。

- 修复一系列 pg_rewind 边界情况（Alexander Kukushkin）

  如果源集群不是 master，则避免运行 pg_rewind。

  此外，除非新参数 *remove_data_directory_on_rewind_failure* 设置为 true，否则避免在 rewind 失败时删除数据目录。默认情况下它为 false。

- 从 DCS 中的复制连接字符串中移除密码（Alexander Kukushkin）

  之前，Patroni 总是使用 DCS 中 Postgres URL 的复制凭据。现在改为从 patroni 配置中获取凭据。secrets（复制用户名和密码）不再在 DCS 中公开。

- 修复围绕 demote 调用的异步机制（Alexander Kukushkin）

  Demote 现在完全异步运行，不会阻塞 DCS 交互。

- 让 patronictl 在配置了授权头时始终发送授权头（Alexander Kukushkin）

  这允许 patronictl 在 Patroni 配置为需要授权时发出 "受保护的" 请求，即 restart 或 reinitialize。

- 正确处理 SystemExit 异常（Alexander Kukushkin）

  避免 Patroni 在收到 SIGTERM 时无法正常停止的问题。

- 为 confd 提供 haproxy 模板示例（Alexander Kukushkin）

  使用 confid 根据 DCS 中的 patroni 状态生成并动态更改 haproxy 配置。

- 改进和重构文档，使其对新用户更友好（Lauri Apple）

- 在 pg_ctl stop 期间 API 必须报告 role=master（Alexander Kukushkin）

  使回调调用更可靠，尤其是在集群停止的情况下。此外，引入 `pg_ctl_timeout` 选项，通过 `pg_ctl` 设置 start、stop 和 restart 调用的超时。

- 修复 etcd 中的重试逻辑（Alexander Kukushkin）

  使重试更可预测和健壮。

- 使 ZooKeeper 代码对短暂的网络抖动更有弹性（Alexander Kukushkin）

  缩短连接超时，使 ZooKeeper 连接尝试更频繁。

版本 0.90
---------

发布于 2016-04-27

此版本添加了对 Consul 的支持，包含一个新的 *noloadbalance* 标签，更改了 *clonefrom* 标签的行为，改进了 *pg_rewind* 处理和 *patronictl* 控制程序。

**Consul 支持**

- 实现 Consul 支持（Alexander Kukushkin）

  Patroni 可以在 Consul 上运行，除了 Etcd 和 ZooKeeper。连接参数可以在 YAML 文件中配置。

**新的和改进的标签**

- 实现 *noloadbalance* 标签（Alexander Kukushkin）

  此标签使 Patroni 始终向负载均衡器返回该 replica 不可用。

- 更改 *clonefrom* 标签的实现（Alexander Kukushkin）

  之前，必须向 *clonefrom* 提供节点名称，强制标记的 replica 从特定节点克隆。新实现使 *clonefrom* 成为布尔标签：如果设置为 true，该 replica 就成为其他 replica 克隆的候选来源。当存在多个候选者时，replica 随机选择其中一个。

**稳定性和安全性改进**

- 大量可靠性改进（Alexander Kukushkin）

  移除了一些虚假的错误消息，提高了 failover 的稳定性，处理了从 DCS 读取数据、关闭、降级和重新附加前任 leader 的一些边界情况。

- 改进系统脚本，避免在停止时杀死 Patroni 子进程（Jan Keirse、Alexander Kukushkin）

  之前，停止 Patroni 时，*systemd* 也会向 PostgreSQL 发送信号。由于 Patroni 自己也试图停止 PostgreSQL，结果发送了两个不同的关闭请求（先智能关闭，再快速关闭）。这导致 replica 过早断开，前任 master 在降级后无法重新加入。修复由 Jan 完成，此前由 Alexander 进行过研究。

- 消除某些前任 master 在重新加入为 replica 之前无法调用 pg_rewind 的情况（Oleksii Kliukin）

  之前，我们只在前任 master 崩溃时调用 *pg_rewind*。现在改为只要系统中存在 pg_rewind，就始终为前任 master 运行 pg_rewind。这修复了 master 在 replica 获得最新更改之前被关闭（即 "智能" 关闭期间）的情况。

- 单元测试和验收测试的大量改进，特别是启用对 ZooKeeper 和 Consul 的支持（Alexander Kukushkin）。

- 加快 Travis CI 并实现对 ZooKeeper（Exhibitor）和 Consul 运行测试的支持（Alexander Kukushkin）

  单元测试和验收测试在每次提交或 pull request 时自动针对 Etcd、ZooKeeper 和 Consul 运行。

- 在从 Patroni 调用 PostgreSQL 命令之前清除环境变量（Feike Steenbergen）

  这防止了通过连接 Patroni 管理的 PostgreSQL 集群来读取系统环境变量的可能性。

**配置和控制更改**

- 统一 patronictl 和 Patroni 配置（Feike Steenbergen）

  patronictl 可以使用与 Patroni 本身相同的配置文件。

- 使 Patroni 能够从环境变量读取配置（Oleksii Kliukin）

  这简化了自动为 Patroni 生成配置，或合并来自不同来源的单一配置。

- 在 API 返回的信息中包含数据库系统标识符（Feike Steenbergen）

- 为所有可用的 DCS 实现 *delete_cluster* （Alexander Kukushkin）

  使 patronictl 支持除 Etcd 之外的其他 DCS。


版本 0.80
---------

发布于 2016-03-14

此版本添加了对 *级联复制* 的支持，并通过提供 *计划 failover* 简化了 Patroni 的管理。可以将旧版本 Patroni（特别是 0.78）与此版本结合使用，以迁移到新版本。请注意，计划 failover 和级联复制相关功能仅适用于 Patroni 0.80 及以上版本。

**级联复制**

- 为 patroni 节点添加对 *replicatefrom* 和 *clonefrom* 标签的支持（Oleksii Kliukin）。

  标签 *replicatefrom* 允许 replica 使用任意节点作为复制源，而不一定是 master。*clonefrom* 对初始备份也做同样的事情。它们一起使 Patroni 完全支持级联复制。

- 添加对运行复制方法来初始化 replica 的支持，即使没有活动的复制连接（Oleksii Kliukin）。

  这对于从存储在 S3 或 FTP 上的快照创建 replica 很有用。不需要活动复制连接的复制方法应在 yaml 配置中提供 *no_master: true*。如果存在复制连接，这些脚本仍会按顺序被调用。

**Patronictl、API 和 DCS 改进**

- 实现计划 failover（Feike Steenbergen）。

  Failover 可以使用 patronictl 或 API 调用安排在将来的某个特定时间发生。

- 在 patronictl 中添加对 *dbuser* 和 *password* 参数的支持（Feike Steenbergen）。

- 将 PostgreSQL 版本添加到健康检查输出中（Feike Steenbergen）。

- 改进 patronictl 中的 ZooKeeper 支持（Oleksandr Shulgin）

- 迁移到 python-etcd 0.43（Alexander Kukushkin）

**配置**

- 为 Patroni 添加示例系统配置脚本（Jan Keirse）。

- 修复 Patroni 忽略配置文件中为数据库连接指定的 superuser 名称的问题（Alexander Kukushkin）。

- 通过为 Patroni 启动的 postmaster 创建单独的会话 ID 和进程组，修复对 CTRL-C 的处理（Alexander Kukushkin）。

**测试**

- 使用 *behave* 添加验收测试，以检查运行 Patroni 的真实场景（Alexander Kukushkin、Oleksii Kliukin）。

  测试可以使用 *behave* 命令手动启动。它们也会在 pull request 和提交后自动启动。

  一些旧版本的发布说明可以在 `项目的 github 页面 <https://github.com/patroni/patroni/releases>`__ 找到。
