.. _replica_imaging_and_bootstrap:

Replica 镜像与 bootstrap
=============================

Patroni 允许自定义新 replica 的创建方式。它还支持定义在全新空集群被 bootstrap 时应该发生什么。两者之间的区别定义得很明确：只有当 DCS 中存在集群的 ``initialize`` 键时，Patroni 才会创建 replica。如果不存在 ``initialize`` 键，Patroni 只在第一个取得 initialize 键锁的节点上执行 bootstrap。

.. _custom_bootstrap:

Bootstrap
---------

PostgreSQL 提供了 ``initdb`` 命令来初始化新的集群，Patroni 默认会调用它。在某些情况下，尤其是在将现有集群的副本创建为新集群时，需要用自定义操作来替换内置方法。Patroni 支持执行用户自定义的脚本来 bootstrap 新集群，并向它们提供一些必需的参数，即集群名称和数据目录的路径。这在 Patroni 配置的 ``bootstrap`` 部分中进行配置。例如：

.. code:: YAML

    bootstrap:
        method: <custom_bootstrap_method_name>
        <custom_bootstrap_method_name>:
            command: <path_to_custom_bootstrap_script> [param1 [, ...]]
            keep_existing_recovery_conf: False
            no_params: False
            recovery_conf:
                recovery_target_action: promote
                recovery_target_timeline: latest
                restore_command: <method_specific_restore_command>


每个 bootstrap 方法至少必须定义一个 ``name`` 和一个 ``command``。可以使用特殊的 ``initdb`` 方法触发默认行为，在这种情况下可以完全省略 ``method`` 参数。``command`` 可以使用绝对路径，也可以使用相对于 ``patroni`` 命令位置的路径。除了配置文件中定义的固定参数外，Patroni 还提供两个集群特定的参数：

--scope
    要 bootstrap 的集群的名称
--datadir
    要 bootstrap 的集群实例的数据目录路径

可以通过将特殊的 ``no_params`` 参数设置为 ``True`` 来禁用传递这两个附加标志。

如果 bootstrap 脚本返回 ``0``，Patroni 会尝试配置并启动由它生成的 PostgreSQL 实例。如果任何中间步骤失败，或者脚本返回非零值，Patroni 会认为 bootstrap 失败，自行清理并释放 initialize 锁，以便给另一个节点提供 bootstrap 的机会。

如果在自定义 bootstrap 方法所在的同一部分定义了 ``recovery_conf`` 块，Patroni 将在启动新 bootstrap 的实例之前生成一个 ``recovery.conf``（如果运行的是 PostgreSQL >= 12，则在 Postgres 配置上设置恢复设置）。通常，此类恢复配置应至少包含一个 ``recovery_target_*`` 参数，并将 ``recovery_target_action`` 设置为 ``promote``。

如果定义 ``keep_existing_recovery_conf`` 并将其设置为 ``True``，Patroni 将不会删除已存在的 ``recovery.conf`` 文件（PostgreSQL <= 11）。同样，在这种情况下，Patroni 不会删除已存在的 ``recovery.signal`` 或 ``standby.signal``，也不会覆盖已配置的恢复设置（PostgreSQL >= 12）。当使用 pgBackRest 等工具从备份进行 bootstrap（这些工具会为您生成适当的恢复配置）时，这非常有用。

此外，在自定义 bootstrap 方法配置中提供的任何其他键/值对，都将以 ``--name=value`` 的格式作为参数传递给 ``command``。例如：

.. code:: YAML

    bootstrap:
        method: <custom_bootstrap_method_name>
        <custom_bootstrap_method_name>:
            command: <path_to_custom_bootstrap_script>
            arg1: value1
            arg2: value2

这样配置的 ``command`` 就会额外使用 ``--arg1=value1 --arg2=value2`` 命令行参数被调用。

 .. note:: Bootstrap 方法既不会串联，也不会在主方法失败时回退到默认方法

例如，您可以使用如下配置从 Barman 备份中 bootstrap 一个全新的 Patroni 集群：

.. code:: YAML

    bootstrap:
        method: barman
        barman:
            keep_existing_recovery_conf: true
            command: patroni_barman --api-url https://barman-host:7480 recover
            barman-server: my_server
            ssh-command: ssh postgres@patroni-host

.. note::
    ``patroni_barman recover`` 要求您在 Barman 主机上同时配置 Barman 和 ``pg-backup-api``，以便它能够通过备份 API 执行远程的 ``barman recover``。
    上面的示例只使用了可用参数的一部分。您可以通过运行 ``patroni_barman recover --help`` 获取更多信息。

.. _custom_replica_creation:

构建 replica
-----------------

Patroni 使用久经考验的 ``pg_basebackup`` 来创建新的 replica。它的一个缺点是要求 leader 节点处于运行状态。另一个缺点是没有针对备份数据的「即时」压缩，也没有对过时备份文件的内置清理。有些人更喜欢其他备份解决方案，例如 ``WAL-E``、``pgBackRest``、``Barman`` 等，或者干脆自己编写脚本。为了满足所有这些使用场景，Patroni 支持运行自定义脚本来克隆新的 replica。这些在 ``postgresql`` 配置块中进行配置：

.. code:: YAML

    postgresql:
        create_replica_methods:
            - <method name>
        <method name>:
            command: <command name>
            keep_data: True
            no_params: True
            no_leader: 1

示例：wal_e

.. code:: YAML

    postgresql:
        create_replica_methods:
            - wal_e
            - basebackup
        wal_e:
            command: patroni_wale_restore
            no_leader: 1
            envdir: {{WALE_ENV_DIR}}
            use_iam: 1
        basebackup:
            max-rate: '100M'

示例：pgbackrest

.. code:: YAML

    postgresql:
        create_replica_methods:
            - pgbackrest
            - basebackup
        pgbackrest:
            command: /usr/bin/pgbackrest --stanza=<scope> --delta restore
            keep_data: True
            no_params: True
        basebackup:
            max-rate: '100M'

示例：Barman

.. code:: YAML

    postgresql:
        create_replica_methods:
            - barman
            - basebackup
        barman:
            command: patroni_barman --api-url https://barman-host:7480 recover
            barman-server: my_server
            ssh-command: ssh postgres@patroni-host
        basebackup:
            max-rate: '100M'

.. note::
    ``patroni_barman recover`` 要求您在 Barman 主机上同时配置 Barman 和 ``pg-backup-api``，以便它能够通过备份 API 执行远程的 ``barman recover``。
    上面的示例只使用了可用参数的一部分。您可以通过运行 ``patroni_barman recover --help`` 获取更多信息。

``create_replica_methods`` 定义了可用的 replica 创建方法及其执行顺序。Patroni 会在第一个返回 0 的方法处停止。每个方法都应在配置文件中定义单独的部分，列出要执行的命令以及应传递给该命令的任何自定义参数。所有参数都将以 ``--name=value`` 格式传递。除了用户定义的参数之外，Patroni 还提供几个集群特定的参数：

--scope
    此 replica 属于哪个集群
--datadir
    replica 的数据目录路径
--role
    始终为 'replica'
--connstring
    连接到要从中克隆的集群成员（primary 或其他 replica）的连接字符串。连接字符串中的
    用户可以执行 SQL 和复制协议命令。

如果定义了特殊的 ``no_leader`` 参数，即使没有正在运行的 leader 或 replica，Patroni 也会允许调用 replica 创建方法。在这种情况下，连接字符串中会传入一个空字符串。这对于从二进制备份恢复先前运行的集群非常有用。

如果定义了特殊的 ``keep_data`` 参数，将指示 Patroni 在调用 restore 之前不要清理 PGDATA 文件夹。

如果定义了特殊的 ``no_params`` 参数，将限制向自定义命令传递参数。

``basebackup`` 方法是一种特殊情况：当 ``create_replica_methods`` 为空时就会使用它，尽管
也可以在 ``create_replica_methods`` 方法中显式列出它。此方法使用
``pg_basebackup`` 初始化新的 replica，基础备份取自 leader，除非存在带有 ``clonefrom`` 标签的 replica，在这种情况下
将使用其中一个这样的 replica 作为 pg_basebackup 的数据来源。它无需任何配置即可工作；不过，
也可以指定一个 ``basebackup`` 配置部分。与其他方法配置适用的规则相同，
即只能在这里指定长（带 --）选项。并非所有参数都有意义：如果您覆盖了连接
字符串，或者提供了创建 tar 压缩或压缩基础备份的选项，patroni 将无法用它创建 replica。
传递给 ``basebackup`` 部分的参数名称或值不会进行任何校验。
另外请注意，如果 WAL 文件夹使用了符号链接，则需要用户指定正确的 ``--waldir``
路径作为选项，以便在 replica 构建或重新初始化后符号链接仍然存在。不过，此选项仅从 v10 开始支持。

您可以将 basebackup 参数指定为映射（键值对）或元素列表，其中每个元素
可以是键值对，也可以是单个键（用于不接受任何值的选项，例如 ``--verbose``）。
请考虑以下两个示例：

.. code:: YAML

    postgresql:
        basebackup:
            max-rate: '100M'
            checkpoint: 'fast'

以及

.. code:: YAML

    postgresql:
        basebackup:
            - verbose
            - max-rate: '100M'
            - waldir: /pg-wal-mount/external-waldir

如果所有 replica 创建方法都失败，Patroni 将在下一个事件循环周期中按顺序再次尝试所有方法。
