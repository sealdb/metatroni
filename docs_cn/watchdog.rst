.. _watchdog:

Watchdog 支持
=============

如果多个 PostgreSQL 服务器同时以 primary 身份运行，可能会因 timeline 分叉而导致事务丢失。这种情况也被称为脑裂（split-brain）问题。为了避免脑裂，Patroni 需要确保在 DCS 中的 leader key 过期之后，PostgreSQL 不再接受任何事务提交。在正常情况下，Patroni 会通过在任何原因导致 leader lock 更新失败时停止 PostgreSQL 来实现这一点。然而，由于各种原因，这可能会无法实现：

- Patroni 因 bug、内存不足（out-of-memory）或被系统管理员意外终止而崩溃。

- 关闭 PostgreSQL 的速度太慢。

- 由于系统负载过高、虚拟机被 hypervisor 暂停或其他基础设施问题，Patroni 无法运行。

为了在这些条件下保证正确行为，Patroni 支持 watchdog 设备。Watchdog 设备是一种软件或硬件机制，当在指定时间范围内未收到 keepalive 心跳时，它会重置整个系统。这为通常的 Patroni 脑裂保护机制失效时增加了一层额外的安全保护。

Patroni 会在将 PostgreSQL 提升为 primary 之前尝试激活 watchdog。如果 watchdog 激活失败且 watchdog 模式为 ``required``\，则节点将拒绝成为 leader。在决定是否参与 leader 选举时，Patroni 还会检查 watchdog 配置是否允许它成为 leader。在降级 PostgreSQL 之后（例如由于手动 failover），Patroni 会再次禁用 watchdog。当 Patroni 处于暂停状态时，watchdog 也会被禁用。

默认情况下，Patroni 会将 watchdog 设置为在 TTL 到期前 5 秒过期。在 ``loop_wait=10`` 和 ``ttl=30`` 的默认设置下，HA 循环在系统被强制重置之前至少有 15 秒（``ttl``- ``safety_margin``- ``loop_wait``\）时间来完成。默认情况下，访问 DCS 配置为在 10 秒后超时。这意味着当 DCS 不可用（例如由于网络问题）时，Patroni 和 PostgreSQL 至少有 5 秒（``ttl``- ``safety_margin``- ``loop_wait``- ``retry_timeout``\）时间达到所有客户端连接都被终止的状态。

Safety margin 是 Patroni 为 leader key 更新与 watchdog keepalive 之间的时间预留的时间量。Patroni 会在 leader key 更新确认后立即尝试发送 keepalive。如果 Patroni 进程恰好在关键时刻被长时间挂起，keepalive 可能延迟超过 safety margin 而不会触发 watchdog。这会导致出现一个 watchdog 不会在 leader key 过期前触发的时间窗口，从而使这一保证失效。为了绝对确保 watchdog 在所有情况下都能触发，可以将 ``safety_margin`` 设置为 -1，让 watchdog 在 TTL 的一半后过期，即将 watchdog 超时设置为 ``ttl // 2``\。如果你需要这种保证，可能应该增大 ``ttl`` 和/或减小 ``loop_wait`` 和 ``retry_timeout``\。

目前 watchdog 仅支持使用 Linux watchdog 设备接口。

在 Linux 上设置软件 watchdog
----------------------------

默认的 Patroni 配置在 Linux 上会尝试使用 ``/dev/watchdog`` （如果 Patroni 可以访问它）。对于大多数使用场景，使用内置于 Linux 内核的软件 watchdog 已经足够安全。

要启用软件 watchdog，请在启动 Patroni 之前以 root 身份执行以下命令：

.. code-block:: bash

    modprobe softdog
    # Replace postgres with the user you will be running patroni under
    chown postgres /dev/watchdog

为了测试，可以通过在 modprobe 命令行中添加 ``soft_noboot=1`` 来禁用重启，这会很有帮助。在这种情况下，watchdog 只会在内核环形缓冲区中记录一行日志，可通过 `dmesg` 查看。

当 watchdog 成功启用时，Patroni 会记录相关信息。
