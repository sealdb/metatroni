.. _dcs_failsafe_mode:

DCS Failsafe 模式
=================

问题
-----------

Patroni 高度依赖分布式配置存储（DCS）来完成 leader 选举和检测网络分区。也就是说，节点只有在能够更新 DCS 中的 leader lock 时，才被允许以 primary 身份运行 Postgres。如果 leader lock 更新失败，Postgres 会立即被降级并以只读方式启动。根据所使用的 DCS 不同，遇到"问题"的几率也不同。例如，对于只用于 Patroni 的 Etcd，几率接近于零，而对于 K8s API（由 Etcd 支撑），则可能更频繁地观察到这个问题。


当前实现的原因
---------------------------------------

leader lock 更新失败可能由两个主要原因造成：

1. 网络分区
2. DCS 宕机

一般来说，从单个节点无法区分这两种情况，因此 Patroni 会假设最坏的情况——网络分区。在发生网络分区的情况下，Patroni 集群中的其他节点可能会成功抢占 leader lock 并将 Postgres 提升为 primary。为了避免脑裂，旧 primary 会在 leader lock 过期之前被降级。


DCS Failsafe 模式
-----------------

我们引入了一个新的特殊选项，即 ``failsafe_mode``。它只能通过存储在 DCS ``/config`` key 中的全局 :ref:`dynamic configuration <dynamic_configuration>` 启用。如果 failsafe 模式已启用，且 DCS 中的 leader lock 更新失败的原因不是版本/值/索引不匹配，那么只要 Postgres 能够通过 Patroni REST API 访问集群中的所有已知成员，它就可以继续以 primary 身份运行。


底层实现细节
--------------------------------

- 我们在 DCS 中引入了一个新的永久 key，名为 ``/failsafe``。
- ``/failsafe`` key 包含给定时刻某个 Patroni 集群的所有已知成员。
- 当前 leader 维护 ``/failsafe`` key。
- 只有出现在 ``/failsafe`` key 中的成员才被允许参与 leader 竞争并成为新 leader。
- 如果集群由单个节点组成，则 ``/failsafe`` key 将只包含一个成员。
- 在 DCS"中断"的情况下，现有 primary 会通过 ``POST /failsafe`` REST API 连接 ``/failsafe`` key 中的所有成员，如果所有 replica 都确认它，就可以继续以 primary 身份运行。
- 如果其中一个成员没有响应，primary 就会被降级。
- Replica 使用收到的 ``POST /failsafe`` REST API 请求作为 primary 仍然存活的指示。该信息会被缓存 ``ttl`` 秒。


常见问题
--------

- 为什么当前 primary 必须看到所有其他成员？难道我们不能依赖 quorum 吗？

  这是一个很好的问题！问题在于，从 DCS 和 Patroni 的角度来看，对 quorum 的看法可能不同。虽然 DCS 节点必须均匀分布在各个可用区（availability zone）之间，但对 Patroni 却没有这样的规则，更重要的是，也没有机制来引入和执行这样的规则。如果大多数 Patroni 节点（包括 primary）最终处于被分区的网络中的失败一侧，而少数节点处于成功一侧，那么 primary 必须被降级。只有检查所有其他成员才能发现这种情况。

- 如果 DCS 宕机期间节点/pod 被终止会怎样？

  如果 DCS 不可访问，每个心跳循环周期（每 ``loop_wait`` 秒）都会执行"所有其他集群成员是否都可访问？"的检查。如果 pod/node 被终止，检查将失败，Postgres 将被降级为只读，并且在 DCS 恢复之前不会恢复。

- 如果 DCS 宕机期间 Patroni 集群的所有成员都丢失了会怎样？

  即使集群没有 leader，也可以将 Patroni 配置为从备份创建新的 replica。但是，如果新成员不在 ``/failsafe`` key 中，它将无法获取 leader lock 并被提升。

- 如果 primary 失去了对 DCS 的访问而 replica 没有，会发生什么？

  primary 将执行 failsafe 代码并联系所有已知 replica。这些 replica 会将此信息作为 primary 存活的指示，即使 DCS 中的 leader lock 已过期，也不会启动 leader 竞争。

- 如何启用 Failsafe 模式？

  在启用 ``failsafe_mode`` 之前，请确保所有成员上的 Patroni 版本都是最新的。之后，你可以使用 ``PATCH /config`` :ref:`REST API <rest_api>` 或 :ref:`patronictl edit-config -s failsafe_mode=true <patronictl_edit_config_parameters>`
