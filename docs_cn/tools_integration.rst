.. _tools_integration:

与其他工具的集成
============================

Patroni 能够与你技术栈中的其他工具集成。在本节中，你将看到一些示例列表，虽然这些示例并非详尽无遗，但可能会给你带来关于 Patroni 如何与其他工具集成的启发。

Barman
------

Patroni 提供了一个名为 ``patroni_barman`` 的应用程序，它包含与 ``pg-backup-api`` 通信的逻辑，因此你可以远程执行 Barman 操作。

该应用程序目前有几个子命令：``recover`` 和 ``config-switch``。

patroni_barman recover
^^^^^^^^^^^^^^^^^^^^^^

``recover`` 子命令可以用作自定义 bootstrap 或自定义 replica 创建方法。你可以在 :ref:`replica_imaging_and_bootstrap` 中找到更多相关信息。

patroni_barman config-switch
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``config-switch`` 子命令设计用于作为 Patroni 中的 ``on_role_change`` 回调。举个例子，假设你正在将 WAL 从当前的 primary 流式传输到你的 Barman 主机。如果集群发生 failover，你可能希望开始从新的 primary 流式传输 WAL。你可以通过将 ``patroni_barman config-switch`` 用作 ``on_role_change`` 回调来实现这一点。

.. note::
    该子命令依赖于 ``barman config-switch`` 命令，该命令负责通过在 Barman 服务器之上应用预定义的模型来覆盖其配置。此命令自 Barman 3.10 起可用。更多细节请参阅 Barman 文档。

下面是一个示例，展示如何配置 Patroni，以便在此 Patroni 节点被提升为 primary 时应用某个配置模型：

.. code:: YAML

    postgresql:
        callbacks:
            on_role_change: >
                patroni_barman
                    --api-url YOUR_API_URL
                    config-switch
                    --barman-server YOUR_BARMAN_SERVER_NAME
                    --barman-model YOUR_BARMAN_MODEL_NAME
                    --switch-when promoted

.. note::
    ``patroni_barman config-switch`` 要求你在 Barman 主机上同时配置好 Barman 和 ``pg-backup-api``，这样它才能通过备份 API 远程执行 ``barman config-switch``。此外，它还要求你预先配置好要应用的 Barman 模型。上面的示例只使用了可用参数的一部分。你可以通过运行 ``patroni_barman config-switch --help`` 以及查阅 Barman 文档来获取更多信息。
