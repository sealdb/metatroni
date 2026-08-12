.. _patronictl:

patronictl
==========

Patroni 提供了一个名为 ``patronictl`` 的命令行界面，主要用于与 Patroni 的 REST API 和 DCS 进行交互。其目的是让集群中的操作变得更加容易，既适合人工使用，也方便脚本调用。

.. _patronictl_configuration:

配置
-----

``patronictl`` 使用配置中的 3 个部分：

- **ctl**：如何针对 Patroni REST API 进行身份认证，以及如何校验服务器身份。更多详情请参阅 :ref:`ctl settings <patronictl_settings>`；
- **restapi**：如何针对 Patroni REST API 进行身份认证，以及如何校验服务器身份。仅在 ``ctl`` 配置不足时使用。``patronictl`` 主要关注 ``restapi.authentication`` 部分（当缺少 ``ctl.authentication`` 时）以及 ``restapi.cafile`` 设置（当缺少 ``ctl.cacert`` 时）。更多详情请参阅 :ref:`REST API settings <restapi_settings>`；
- DCS（例如 **etcd**）：如何连接 Patroni 所使用的 DCS 并针对其进行身份认证。

这些配置选项既可以来自环境变量，也可以来自配置文件。请在 :ref:`Environment Configuration Settings <environment>` 或 :ref:`YAML Configuration Settings <yaml_configuration>` 中查找上述部分，以了解如何通过环境变量或配置文件为这些选项设置值。

如果你选择使用环境变量，这是一种简单直接的方式。Patronictl 会读取环境变量并使用它们的值。

如果你选择使用配置文件，有多种方式可以告知 ``patronictl`` 要使用的文件。默认情况下，``patronictl`` 会尝试加载名为 ``patronictl.yaml`` 的配置文件，根据你的系统不同，该文件应位于以下任一路径下：

- Mac OS X: ``~/Library/Application Support/patroni``
- Mac OS X (POSIX): ``~/.patroni``
- Unix: ``~/.config/patroni``
- Unix (POSIX): ``~/.patroni``
- Windows (roaming): ``C:\Users\<user>\AppData\Roaming\patroni``
- Windows (not roaming): ``C:\Users\<user>\AppData\Local\patroni``

你可以通过以下任一方式覆盖该行为：

- 设置环境变量 ``PATRONICTL_CONFIG_FILE``，值为自定义配置文件的路径；
- 使用 ``patronictl`` 的 ``-c``/ ``--config-file`` 命令行参数，并指定自定义配置文件的路径。

.. note::
    如果你在与 ``patroni`` 守护进程相同的宿主机上运行 ``patronictl``，只要该配置文件包含 ``patronictl`` 所需的全部配置部分，你就可以直接使用同一个配置文件。

.. _patronictl_usage:

用法
-----

``patronictl`` 提供了若干便捷的操作。本节将逐一介绍这些操作。

在逐一介绍 ``patronictl`` 的子命令之前，请注意 ``patronictl`` 本身支持以下命令行参数：

``-c``/ ``--config-file``
    如前所述，用于为 ``patronictl`` 提供配置文件的路径。

``-d``/ ``--dcs-url``/ ``--dcs``
    提供 Patroni 所用 DCS 的连接字符串。

    该参数既可以用于覆盖 ``patronictl`` 配置中的 DCS 和 ``namespace`` 设置，也可以在配置中缺失这些设置时对其进行定义。

    该值的格式应为 ``DCS://HOST:PORT/NAMESPACE``，例如 ``etcd3://localhost:2379/service``，用于连接运行在 ``localhost`` 上的 etcd v3，此时 Patroni 集群存储在 ``service`` 命名空间下。参数值中缺失的任何部分都将替换为配置中已有的值或其默认值。

``-k``/ ``--insecure``
    用于跳过 REST API 服务器 SSL 证书校验的标记。

以下是从 ``patronictl`` 运行命令的语法：

.. code:: text

    patronictl [ { -c | --config-file } CONFIG_FILE ]
      [ { -d | --dcs-url | --dcs } DCS_URL ] 
      [ { -k | --insecure } ]
      SUBCOMMAND

.. note::

    这是语法说明所采用的语法格式：

    - 方括号内的选项为可选项；
    - 花括号内的选项表示「从一组中选一个」的操作；
    - 带有 ``[, ... ]`` 的选项可以多次指定；
    - 以大写书写的内容表示需要给定一个值的字面量。

    在以下各小节中描述 ``patronictl`` 子命令时，我们将使用同样的语法格式。
    此外，在以下各小节中描述子命令时，各命令的语法说明应视为上述语法中 ``SUBCOMMAND`` 的替换。

在以下各小节中，你可以找到 ``patronictl`` 所实现的每个命令的说明。为了举例，我们将使用 Patroni 的 GitHub 仓库中提供的配置文件（``postgres0.yml``、``postgres1.yml`` 和 ``postgres2.yml``）。

.. _patronictl_dsn:

patronictl dsn
^^^^^^^^^^^^^^

.. _patronictl_dsn_synopsis:

语法
""""""

.. code:: text

    dsn
      [ CLUSTER_NAME ]
      [ { { -r | --role } { leader | primary | standby-leader | replica | standby | any } | { -m | --member } MEMBER_NAME } ]
      [ --group CITUS_GROUP ]

.. _patronictl_dsn_description:

说明
""""""""

``patronictl dsn`` 获取 Patroni 集群中某个成员的连接字符串。

如果有多个成员与该命令的参数匹配，则会选择其中一个，并优先选择 primary 节点。

.. _patronictl_dsn_parameters:

参数
""""""""

``CLUSTER_NAME``
    Patroni 集群的名称。

    如果未指定，``patronictl`` 将尝试从 ``scope`` 配置中获取该值（如果存在）。

``-r``/ ``--role``
    选择具有指定角色的成员。

    角色可以是以下之一：

    - ``leader``：常规 Patroni 集群或 standby Patroni 集群的 leader；或
    - ``primary``：常规 Patroni 集群的 leader；或
    - ``standby-leader``：standby Patroni 集群的 leader；或
    - ``replica``：Patroni 集群的 replica；或
    - ``standby``：与 ``replica`` 相同；或
    - ``any``：任意角色，等同于省略该参数；或

``-m``/ ``--member``
    选择集群中具有指定名称的成员。

    ``MEMBER_NAME`` 是成员的名称。

``--group``
    选择属于指定 Citus 组的成员。

    ``CITUS_GROUP`` 是 Citus 组的 ID。

.. _patronictl_dsn_examples:

示例
""""""""

获取 primary 节点的 DSN：

.. code:: bash

    $ patronictl -c postgres0.yml dsn batman -r primary
    host=127.0.0.1 port=5432

获取名为 ``postgresql1`` 的节点的 DSN：

.. code:: bash

    $ patronictl -c postgres0.yml dsn batman --member postgresql1
    host=127.0.0.1 port=5433

.. _patronictl_edit_config:

patronictl edit-config
^^^^^^^^^^^^^^^^^^^^^^

.. _patronictl_edit_config_synopsis:

语法
""""""

.. code:: text

    edit-config
      [ CLUSTER_NAME ]
      [ --group CITUS_GROUP ]
      [ { -q | --quiet } ]
      [ { -s | --set } CONFIG="VALUE" [, ... ] ]
      [ { -p | --pg } PG_CONFIG="PG_VALUE" [, ... ] ]
      [ { --apply | --replace } CONFIG_FILE ]
      [ --force ]

.. _patronictl_edit_config_description:

说明
""""""""

``patronictl edit-config`` 修改集群的动态配置，并将修改后的配置更新到 DCS 中。

.. note::
    当通过 TTY 调用时，该命令会尝试通过分页器（pager）显示动态配置的 diff。默认情况下，它会尝试使用 ``less`` 或 ``more``。如果你想使用其他分页器，请通过设置 ``PAGER`` 环境变量来指定。

.. _patronictl_edit_config_parameters:

参数
""""""""

``CLUSTER_NAME``
    Patroni 集群的名称。

    如果未指定，``patronictl`` 将尝试从 ``scope`` 配置中获取该值（如果存在）。

``--group``
    修改指定 Citus 组的动态配置。
    
    如果未指定，``patronictl`` 将尝试从 ``citus.group`` 配置中获取该值（如果存在）。

    ``CITUS_GROUP`` 是 Citus 组的 ID。

``-q``/ ``--quiet``
    用于跳过显示配置 diff 的标记。

``-s``/ ``--set``
    以给定的值设置某个动态配置选项。

    ``CONFIG`` 是 YAML 树中动态配置路径的名称，各级之间用 ``.`` 连接。

    ``VALUE`` 是 ``CONFIG`` 的值。如果该值为 ``null``，则 ``CONFIG`` 将从动态配置中移除。

``-p``/ ``--pg``
    以给定的值设置某个动态 Postgres 配置选项。

    这实际上是 ``--s``/ ``--set`` 的一种简写形式，会在 ``CONFIG`` 前加上 ``postgresql.parameters.`` 前缀。

    ``PG_CONFIG`` 是要设置的 Postgres 配置的名称。

    ``PG_VALUE`` 是 ``PG_CONFIG`` 的值。如果该值为 ``null``，则 ``PG_CONFIG`` 将从动态配置中移除。

``--apply``
    从给定的文件应用动态配置。

    这类似于为 ``CONFIG_FILE`` 中的每一项配置分别指定一个 ``-s``/ ``--set`` 选项。

    ``CONFIG_FILE`` 是包含要应用的动态配置的文件的路径，格式为 YAML。如果想从 ``stdin`` 读取，请使用 ``-``。

``--replace``
    将 DCS 中的动态配置替换为指定文件中定义的动态配置。

    ``CONFIG_FILE`` 是包含新的、即将生效的动态配置的文件的路径，格式为 YAML。如果想从 ``stdin`` 读取，请使用 ``-``。

``--force``
    在修改动态配置时跳过确认提示的标记。

    适用于脚本。

.. _patronictl_edit_config_examples:

示例
""""""""

修改 ``max_connections`` Postgres GUC：

.. code:: diff

    patronictl -c postgres0.yml edit-config batman --pg max_connections="150" --force
    ---
    +++
    @@ -1,6 +1,8 @@
    loop_wait: 10
    maximum_lag_on_failover: 1048576
    postgresql:
    +  parameters:
    +    max_connections: 150
      pg_hba:
      - host replication replicator 127.0.0.1/32 md5
      - host all all 0.0.0.0/0 md5

    Configuration changed

修改 ``loop_wait`` 和 ``ttl`` 设置：

.. code:: diff

    patronictl -c postgres0.yml edit-config batman --set loop_wait="15" --set ttl="45" --force
    ---
    +++
    @@ -1,4 +1,4 @@
    -loop_wait: 10
    +loop_wait: 15
    maximum_lag_on_failover: 1048576
    postgresql:
      pg_hba:
    @@ -6,4 +6,4 @@
      - host all all 0.0.0.0/0 md5
      use_pg_rewind: true
    retry_timeout: 10
    -ttl: 30
    +ttl: 45

    Configuration changed

从动态配置中移除 ``maximum_lag_on_failover`` 设置：

.. code:: diff

    patronictl -c postgres0.yml edit-config batman --set maximum_lag_on_failover="null" --force
    ---
    +++
    @@ -1,5 +1,4 @@
    loop_wait: 10
    -maximum_lag_on_failover: 1048576
    postgresql:
      pg_hba:
      - host replication replicator 127.0.0.1/32 md5

    Configuration changed

.. _patronictl_failover:

patronictl failover
^^^^^^^^^^^^^^^^^^^

.. _patronictl_failover_synopsis:

语法
""""""

.. code:: text

    failover
      [ CLUSTER_NAME ]
      [ --group CITUS_GROUP ]
      --candidate CANDIDATE_NAME
      [ --force ]

.. _patronictl_failover_description:

说明
""""""""

``patronictl failover`` 在集群中执行手动 failover。

它专为集群不健康的情况而设计，例如：

- 没有 leader；或
- 在同步集群中没有可用的 synchronous standby。

如果启用了同步模式，它还允许 failover 到异步节点。

.. note::
    没有任何机制阻止你在健康的集群中运行 ``patronictl failover``。不过，在这种情况下，我们建议使用 ``patronictl switchover``。

.. warning::
    触发 failover 可能导致数据丢失，具体取决于被提升的 replica 与 primary 相比的新鲜程度。

.. _patronictl_failover_parameters:

参数
""""""""

``CLUSTER_NAME``
    Patroni 集群的名称。

    如果未指定，``patronictl`` 将尝试从 ``scope`` 配置中获取该值（如果存在）。

``--group``
    在指定的 Citus 组中执行 failover。

    ``CITUS_GROUP`` 是 Citus 组的 ID。

``--candidate``
    failover 时将被提升的节点。

    ``CANDIDATE_NAME`` 是将被提升节点的名称。

``--force``
    执行 failover 时跳过确认提示的标记。

    适用于脚本。

.. _patronictl_failover_examples:

示例
""""""""

Failover 到节点 ``postgresql2``：

.. code:: bash

    $ patronictl -c postgres0.yml failover batman --candidate postgresql2 --force
    Current cluster topology
    + Cluster: batman (7277694203142172922) -+-----------+----+-------------+-----+------------+-----+
    | Member      | Host           | Role    | State     | TL | Receive LSN | Lag | Replay LSN | Lag |
    +-------------+----------------+---------+-----------+----+-------------+-----+------------+-----+
    | postgresql0 | 127.0.0.1:5432 | Leader  | running   |  3 |             |     |            |     |
    | postgresql1 | 127.0.0.1:5433 | Replica | streaming |  3 |   0/40004E8 |   0 |  0/40004E8 |   0 |
    | postgresql2 | 127.0.0.1:5434 | Replica | streaming |  3 |   0/40004E8 |   0 |  0/40004E8 |   0 |
    +-------------+----------------+---------+-----------+----+-------------+-----+------------+-----+
    2023-09-12 11:52:27.50978 Successfully failed over to "postgresql2"
    + Cluster: batman (7277694203142172922) -+---------+----+-------------+---------+------------+---------+
    | Member      | Host           | Role    | State   | TL | Receive LSN |     Lag | Replay LSN |     Lag |
    +-------------+----------------+---------+---------+----+-------------+---------+------------+---------+
    | postgresql0 | 127.0.0.1:5432 | Replica | stopped |    |     unknown | unknown |    unknown | unknown |
    | postgresql1 | 127.0.0.1:5433 | Replica | running |  3 |   0/4000188 |       0 |  0/4000188 |       0 |
    | postgresql2 | 127.0.0.1:5434 | Leader  | running |  3 |             |         |            |         |
    +-------------+----------------+---------+---------+----+-------------+---------+------------+---------+

.. _patronictl_flush:

patronictl flush
^^^^^^^^^^^^^^^^

.. _patronictl_flush_synopsis:

语法
""""""

.. code:: text

    flush
      CLUSTER_NAME
      [ MEMBER_NAME [, ... ] ]
      { restart | switchover }
      [ --group CITUS_GROUP ]
      [ { -r | --role } { leader | primary | standby-leader | replica | standby | any } ]
      [ --force ]

.. _patronictl_flush_description:

说明
""""""""

``patronictl flush`` 丢弃已计划的事件（如果有）。

.. _patronictl_flush_parameters:

参数
""""""""

``CLUSTER_NAME``
    Patroni 集群的名称。

``MEMBER_NAME``
    丢弃指定 Patroni 成员的计划事件。

    可以指定多个成员。如果未指定成员，则考虑所有成员。

    .. note::
        仅在丢弃计划的 restart 事件时使用。

``restart``
    丢弃计划的 restart 事件。

``switchover``
    丢弃计划的 switchover 事件。

``--group``
    丢弃指定 Citus 组的计划事件。

    ``CITUS_GROUP`` 是 Citus 组的 ID。

``-r``/ ``--role``
    丢弃具有指定角色的成员的计划事件。

    角色可以是以下之一：

    - ``leader``：常规 Patroni 集群或 standby Patroni 集群的 leader；或
    - ``primary``：常规 Patroni 集群的 leader；或
    - ``standby-leader``：standby Patroni 集群的 leader；或
    - ``replica``：Patroni 集群的 replica；或
    - ``standby``：与 ``replica`` 相同；或
    - ``any``：任意角色，等同于省略该参数。

    .. note::
        仅在丢弃计划的 restart 事件时使用。

``--force``
    执行 flush 时跳过确认提示的标记。

    适用于脚本。

.. _patronictl_flush_examples:

示例
""""""""

丢弃一个计划的 switchover 事件：

.. code:: bash

    $ patronictl -c postgres0.yml flush batman switchover --force
    Success: scheduled switchover deleted

丢弃所有 standby 节点的计划 restart：

.. code:: bash

    $ patronictl -c postgres0.yml flush batman restart -r replica --force
    + Cluster: batman (7277694203142172922) -+-----------+----+-------------+-----+------------+-----+---------------------------+
    | Member      | Host           | Role    | State     | TL | Receive LSN | Lag | Replay LSN | Lag | Scheduled restart         |
    +-------------+----------------+---------+-----------+----+-------------+-----+------------+-----+---------------------------+
    | postgresql0 | 127.0.0.1:5432 | Leader  | running   |  5 |             |     |            |     | 2025-03-23T18:00:00-03:00 |
    | postgresql1 | 127.0.0.1:5433 | Replica | streaming |  5 |   0/4000400 |   0 |  0/4000400 |   0 | 2025-03-23T18:00:00-03:00 |
    | postgresql2 | 127.0.0.1:5434 | Replica | streaming |  5 |   0/4000400 |   0 |  0/4000400 |   0 | 2025-03-23T18:00:00-03:00 |
    +-------------+----------------+---------+-----------+----+-------------+-----+------------+-----+---------------------------+
    Success: flush scheduled restart for member postgresql1
    Success: flush scheduled restart for member postgresql2

丢弃节点 ``postgresql0`` 和 ``postgresql1`` 的计划 restart：

.. code:: bash

    $ patronictl -c postgres0.yml flush batman postgresql0 postgresql1 restart --force
    + Cluster: batman (7277694203142172922) -+-----------+----+-------------+-----+------------+-----+---------------------------+
    | Member      | Host           | Role    | State     | TL | Receive LSN | Lag | Replay LSN | Lag | Scheduled restart         |
    +-------------+----------------+---------+-----------+----+-------------+-----+------------+-----+---------------------------+
    | postgresql0 | 127.0.0.1:5432 | Leader  | running   |  5 |             |     |            |     | 2025-03-23T18:00:00-03:00 |
    | postgresql1 | 127.0.0.1:5433 | Replica | streaming |  5 |   0/4000400 |   0 |  0/4000400 |   0 | 2025-03-23T18:00:00-03:00 |
    | postgresql2 | 127.0.0.1:5434 | Replica | streaming |  5 |   0/4000400 |   0 |  0/4000400 |   0 | 2025-03-23T18:00:00-03:00 |
    +-------------+----------------+---------+-----------+----+-------------+-----+------------+-----+---------------------------+
    Success: flush scheduled restart for member postgresql0
    Success: flush scheduled restart for member postgresql1

.. _patronictl_history:

patronictl history
^^^^^^^^^^^^^^^^^^

.. _patronictl_history_synopsis:

语法
""""""

.. code:: text

    history
      [ CLUSTER_NAME ]
      [ --group CITUS_GROUP ]
      [ { -f | --format } { pretty | tsv | json | yaml } ]

.. _patronictl_history_description:

说明
""""""""

``patronictl history`` 显示集群中 failover 和 switchover 事件的历史记录（如果有）。

输出中包含以下信息：

``TL``
    事件发生时 Postgres 的 timeline。

``LSN``
    事件发生时 Postgres 的 LSN。

``Reason``
    从 Postgres 的 ``.history`` 文件中获取的原因。

``Timestamp``
    事件发生的时间。

``New Leader``
    事件期间被提升的 Patroni 成员。

.. _patronictl_history_parameters:

参数
""""""""

``CLUSTER_NAME``
    Patroni 集群的名称。

    如果未指定，``patronictl`` 将尝试从 ``scope`` 配置中获取该值（如果存在）。

``--group``
    显示指定 Citus 组的事件历史。

    ``CITUS_GROUP`` 是 Citus 组的 ID。
    
    如果未指定，``patronictl`` 将尝试从 ``citus.group`` 配置中获取该值（如果存在）。

``-f``/ ``--format``
    输出中事件列表的格式。

    格式可以是以下之一：

    - ``pretty``：以美观的表格形式输出 history；或
    - ``tsv``：以表格形式输出 history，列之间用 ``\t`` 分隔；或
    - ``json``：以 JSON 格式输出 history；或
    - ``yaml``：以 YAML 格式输出 history。

    默认格式为 ``pretty``。

``--force``
    执行 flush 时跳过确认提示的标记。

    适用于脚本。

.. _patronictl_history_examples:

示例
""""""""

显示事件的历史记录：

.. code:: bash

    $ patronictl -c postgres0.yml history batman
    +----+----------+------------------------------+----------------------------------+-------------+
    | TL |      LSN | Reason                       | Timestamp                        | New Leader  |
    +----+----------+------------------------------+----------------------------------+-------------+
    |  1 | 24392648 | no recovery target specified | 2023-09-11T22:11:27.125527+00:00 | postgresql0 |
    |  2 | 50331864 | no recovery target specified | 2023-09-12T11:34:03.148097+00:00 | postgresql0 |
    |  3 | 83886704 | no recovery target specified | 2023-09-12T11:52:26.948134+00:00 | postgresql2 |
    |  4 | 83887280 | no recovery target specified | 2023-09-12T11:53:09.620136+00:00 | postgresql0 |
    +----+----------+------------------------------+----------------------------------+-------------+

以 YAML 格式显示事件的历史记录：

.. code:: bash

    $ patronictl -c postgres0.yml history batman -f yaml
    - LSN: 24392648
      New Leader: postgresql0
      Reason: no recovery target specified
      TL: 1
      Timestamp: '2023-09-11T22:11:27.125527+00:00'
    - LSN: 50331864
      New Leader: postgresql0
      Reason: no recovery target specified
      TL: 2
      Timestamp: '2023-09-12T11:34:03.148097+00:00'
    - LSN: 83886704
      New Leader: postgresql2
      Reason: no recovery target specified
      TL: 3
      Timestamp: '2023-09-12T11:52:26.948134+00:00'
    - LSN: 83887280
      New Leader: postgresql0
      Reason: no recovery target specified
      TL: 4
      Timestamp: '2023-09-12T11:53:09.620136+00:00'

.. _patronictl_list:

patronictl list
^^^^^^^^^^^^^^^

.. _patronictl_list_synopsis:

语法
""""""

.. code:: text

    list
      [ CLUSTER_NAME [, ... ] ]
      [ --group CITUS_GROUP ]
      [ { -e | --extended } ]
      [ { -t | --timestamp } ]
      [ { -f | --format } { pretty | tsv | json | yaml } ]
      [ { -W | { -w | --watch } TIME } ]

.. _patronictl_list_description:

说明
""""""""

``patronictl list`` 显示 Patroni 集群及其成员的信息。

输出中包含以下信息：

``Cluster``
    Patroni 集群的名称。

``Member``
    Patroni 成员的名称。

``Host``
    成员所在的主机。

``Role``
    成员当前的 role。

    可以是以下之一：

    * ``Leader``：常规 Patroni 集群当前的 leader；或
    * ``Standby Leader``：Patroni standby 集群当前的 leader；或
    * ``Sync Standby``：启用了同步模式的 Patroni 集群中的 synchronous standby；或
    * ``Replica``：Patroni 集群的常规 standby。

``State``
    Patroni 成员中 Postgres 的当前状态。

    以下是可能状态中的一些示例：

    * ``running``：如果 Postgres 当前正在运行；
    * ``streaming``：如果是 replica 且 Postgres 当前正从 primary 节点流式接收 WAL；
    * ``in archive recovery``：如果是 replica 且 Postgres 当前正在从归档中获取 WAL；
    * ``stopped``：如果 Postgres 已被关闭；
    * ``crashed``：如果 Postgres 已崩溃。

``TL``
    Patroni 成员中 Postgres 当前的 timeline。

``Receive LSN``
    该成员通过流复制接收并同步到磁盘的最后一个预写日志位置（``pg_catalog.pg_last_(xlog|wal)_receive_(location|lsn)()``）。

``Receive Lag``
    成员的 ``Receive LSN`` 位置与其上游之间的复制延迟，以 MB 为单位。

``Replay LSN``
    该成员在恢复期间重放的最后一个预写日志位置（``pg_catalog.pg_last_(xlog|wal)_replay_(location|lsn)()``）。

``Replay Lag``
    成员的 ``Replay LSN`` 位置与其上游之间的复制延迟，以 MB 为单位。

除此之外，输出中还可能包含以下信息：

``System identifier``
    Postgres 系统标识符。

    .. note::
        显示在表头中。

        仅当输出格式为 ``pretty`` 时显示。

``Group``
    Citus 组 ID。

    .. note::
        显示在表头中。

        仅当是 Citus 集群时显示。

``Pending restart``
    ``*`` 表示节点需要 restart 才能让某些 Postgres 配置生效。空值表示节点不需要 restart。

    .. note::
        作为成员属性显示。

        在以下情况显示：

        - 以 ``pretty`` 或 ``tsv`` 格式输出且启用了扩展输出；或
        - 节点需要 restart。

``Scheduled restart``
    为 Patroni 成员所管理的 Postgres 实例计划 restart 的时间戳。空值表示该成员没有计划 restart。

    .. note::
        作为成员属性显示。

        在以下情况显示：

        - 以 ``pretty`` 或 ``tsv`` 格式输出且启用了扩展输出；或
        - 节点有计划 restart。

``Tags``
    包含为 Patroni 成员设置的标签。空值表示尚未配置标签，或标签均配置为默认值。

    .. note::
        作为成员属性显示。

        在以下情况显示：

        - 以 ``pretty`` 或 ``tsv`` 格式输出且启用了扩展输出；或
        - 节点有任何自定义标签，或存在值非默认的默认标签。

``Scheduled switchover``
    为 Patroni 集群计划 switchover 的时间戳（如果有）。

    .. note::
        显示在表尾中。

        仅当存在计划的 switchover 且输出格式为 ``pretty`` 时显示。

``Maintenance mode``

    集群监控当前是否已暂停。

    .. note::
        显示在表尾中。

        仅当集群处于暂停状态且输出格式为 ``pretty`` 时显示。

.. _patronictl_list_parameters:

参数
""""""""

``CLUSTER_NAME``
    Patroni 集群的名称。

    如果未指定，``patronictl`` 将尝试从 ``scope`` 配置中获取该值（如果存在）。

``--group``
    显示指定 Citus 组成员的信息。

    ``CITUS_GROUP`` 是 Citus 组的 ID。

``-e``/ ``--extended``
    显示扩展信息。

    强制显示 ``Pending restart``、``Scheduled restart`` 和 ``Tags`` 属性，即使它们的值为空。

    .. note::
        仅适用于 ``pretty`` 和 ``tsv`` 输出格式。

``-t``/ ``--timestamp``
    在打印集群及其成员的信息之前先打印时间戳。

``-f``/ ``--format``
    输出中事件列表的格式。

    格式可以是以下之一：

    - ``pretty``：以美观的表格形式输出 history；或
    - ``tsv``：以表格形式输出 history，列之间用 ``\t`` 分隔；或
    - ``json``：以 JSON 格式输出 history；或
    - ``yaml``：以 YAML 格式输出 history。

    默认格式为 ``pretty``。

``-W``
    每 2 秒自动刷新信息。

``-w``/ ``--watch``
    以指定的间隔自动刷新信息。

    ``TIME`` 是刷新间隔，单位为秒。

.. _patronictl_list_examples:

示例
""""""""

以 pretty 格式显示集群的信息：

.. code:: bash

    $ patronictl -c postgres0.yml list batman
    + Cluster: batman (7277694203142172922) -+-----------+----+-------------+-----+------------+-----+
    | Member      | Host           | Role    | State     | TL | Receive LSN | Lag | Replay LSN | Lag |
    +-------------+----------------+---------+-----------+----+-------------+-----+------------+-----+
    | postgresql0 | 127.0.0.1:5432 | Leader  | running   |  5 |             |     |            |     |
    | postgresql1 | 127.0.0.1:5433 | Replica | streaming |  5 |   0/40004E8 |   0 |  0/40004E8 |   0 |
    | postgresql2 | 127.0.0.1:5434 | Replica | streaming |  5 |   0/40004E8 |   0 |  0/40004E8 |   0 |
    +-------------+----------------+---------+-----------+----+-------------+-----+------------+-----+

以 pretty 格式显示集群信息并包含扩展列：

.. code:: bash

    $ patronictl -c postgres0.yml list batman -e
    + Cluster: batman (7277694203142172922) -+-----------+----+-------------+-----+------------+-----+-----------------+------------------------+-------------------+------+
    | Member      | Host           | Role    | State     | TL | Receive LSN | Lag | Replay LSN | Lag | Pending restart | Pending restart reason | Scheduled restart | Tags |
    +-------------+----------------+---------+-----------+----+-------------+-----+------------+-----+-----------------+------------------------+-------------------+------+
    | postgresql0 | 127.0.0.1:5432 | Leader  | running   |  5 |             |     |            |     |                 |                        |                   |      |
    | postgresql1 | 127.0.0.1:5433 | Replica | streaming |  5 |   0/40004E8 |   0 |  0/40004E8 |   0 |                 |                        |                   |      |
    | postgresql2 | 127.0.0.1:5434 | Replica | streaming |  5 |   0/40004E8 |   0 |  0/40004E8 |   0 |                 |                        |                   |      |
    +-------------+----------------+---------+-----------+----+-------------+-----+------------+-----+-----------------+------------------------+-------------------+------+

以 YAML 格式显示集群信息，并包含执行时间戳：

.. code:: bash

    $ patronictl -c postgres0.yml list batman -f yaml -t
    2023-09-12 13:30:48
    - Cluster: batman
      Host: 127.0.0.1:5432
      Member: postgresql0
      Role: Leader
      State: running
      TL: 5
    - Cluster: batman
      Host: 127.0.0.1:5433
      Receive LSN: 0/40004E8
      Receive Lag: 0
      Replay LSN: 0/40004E8
      Replay Lag: 0
      Member: postgresql1
      Role: Replica
      State: streaming
      TL: 5
    - Cluster: batman
      Host: 127.0.0.1:5434
      Receive LSN: 0/40004E8
      Receive Lag: 0
      Replay LSN: 0/40004E8
      Replay Lag: 0
      Member: postgresql2
      Role: Replica
      State: streaming
      TL: 5

.. _patronictl_pause:

patronictl pause
^^^^^^^^^^^^^^^^

.. _patronictl_pause_synopsis:

语法
""""""

.. code:: text

    pause
      [ CLUSTER_NAME ]
      [ --group CITUS_GROUP ]
      [ --wait ]

.. _patronictl_pause_description:

说明
""""""""

``patronictl pause`` 暂时将 Patroni 集群置于维护模式，并禁用自动 failover。

.. _patronictl_pause_parameters:

参数
""""""""

``CLUSTER_NAME``
    Patroni 集群的名称。

    如果未指定，``patronictl`` 将尝试从 ``scope`` 配置中获取该值（如果存在）。

``--group``
    暂停指定的 Citus 组。

    ``CITUS_GROUP`` 是 Citus 组的 ID。
    
    如果未指定，``patronictl`` 将尝试从 ``citus.group`` 配置中获取该值（如果存在）。

``--wait``
    等待所有 Patroni 成员都暂停后再将控制权返回给调用方。

.. _patronictl_pause_examples:

示例
""""""""

将集群置于维护模式，并等待所有节点都已暂停：

.. code:: bash

    $ patronictl -c postgres0.yml pause batman --wait
    'pause' request sent, waiting until it is recognized by all nodes
    Success: cluster management is paused

.. _patronictl_query:

patronictl query
^^^^^^^^^^^^^^^^

.. _patronictl_query_synopsis:

语法
""""""

.. code:: text

    query
      [ CLUSTER_NAME ]
      [ --group CITUS_GROUP ]
      [ { { -r | --role } { leader | primary | standby-leader | replica | standby | any } | { -m | --member } MEMBER_NAME } ]
      [ { -d | --dbname } DBNAME ]
      [ { -U | --username } USERNAME ]
      [ --password ]
      [ --format { pretty | tsv | json | yaml } ]
      [ { { -f | --file } FILE_NAME | { -c | --command } SQL_COMMAND } ]
      [ --delimiter ]
      [ { -W | { -w | --watch } TIME } ]

.. _patronictl_query_description:

说明
""""""""

``patronictl query`` 针对 Patroni 集群的某个成员执行 SQL 命令或脚本。

.. _patronictl_query_parameters:

参数
""""""""

``CLUSTER_NAME``
    Patroni 集群的名称。

    如果未指定，``patronictl`` 将尝试从 ``scope`` 配置中获取该值（如果存在）。

``--group``
    查询指定的 Citus 组。

    ``CITUS_GROUP`` 是 Citus 组的 ID。

``-r``/ ``--role``
    选择具有指定角色的成员。

    角色可以是以下之一：

    - ``leader``：常规 Patroni 集群或 standby Patroni 集群的 leader；或
    - ``primary``：常规 Patroni 集群的 leader；或
    - ``standby-leader``：standby Patroni 集群的 leader；或
    - ``replica``：Patroni 集群的 replica；或
    - ``standby``：与 ``replica`` 相同；或
    - ``any``：任意角色，等同于省略该参数。

``-m``/ ``--member``
    选择具有指定名称的成员。

    ``MEMBER_NAME`` 是要选择的成员的名称。

``-d``/ ``--dbname``
    要连接并执行查询的数据库。

    ``DBNAME`` 是数据库的名称。如果未指定，默认为 ``USERNAME``。

``-U``/ ``--username``
    连接数据库的用户。

    ``USERNAME`` 是用户的名称。如果未指定，默认为运行 ``patronictl query`` 的操作系统用户。

``--password``
    提示输入连接用户的密码。

    由于 Patroni 使用 ``libpq``，你也可以创建 ``~/.pgpass`` 文件或设置 ``PGPASSWORD`` 环境变量。

``--format``
    查询输出的格式。

    格式可以是以下之一：

    - ``pretty``：以美观的表格形式输出查询结果；或
    - ``tsv``：以表格形式输出查询结果，列之间用 ``\t`` 分隔；或
    - ``json``：以 JSON 格式输出查询结果；或
    - ``yaml``：以 YAML 格式输出查询结果。

    默认格式为 ``tsv``。

``-f``/ ``--file``
    使用文件作为执行查询的命令来源。

    ``FILE_NAME`` 是源文件的路径。

``-c``/ ``--command``
    在查询中运行给定的 SQL 命令。

    ``SQL_COMMAND`` 是要执行的 SQL 命令。

``--delimiter``
    以 ``tsv`` 格式输出信息时使用的分隔符；如果省略，则为 ``\t``。

``-W``
    每 2 秒自动重新运行查询。

``-w``/ ``--watch``
    以指定的间隔自动重新运行查询。

    ``TIME`` 是重新运行之间的间隔，单位为秒。

.. _patronictl_query_examples:

示例
""""""""

以 ``postgres`` 用户身份运行 SQL 命令，并要求输入其密码：

.. code:: bash

    $ patronictl -c postgres0.yml query batman -U postgres --password -c "SELECT now()"
    Password:
    now
    2023-09-12 18:10:53.228084+00:00

以 ``postgres`` 用户身份运行 SQL 命令，并从 ``libpq`` 环境变量中获取密码：

.. code:: bash

    $ PGPASSWORD=patroni patronictl -c postgres0.yml query batman -U postgres -c "SELECT now()"
    now
    2023-09-12 18:11:37.639500+00:00

运行 SQL 命令，并每 2 秒以 ``pretty`` 格式输出一次：

.. code:: bash

    $ patronictl -c postgres0.yml query batman -c "SELECT now()" --format pretty -W
    +----------------------------------+
    | now                              |
    +----------------------------------+
    | 2023-09-12 18:12:16.716235+00:00 |
    +----------------------------------+
    +----------------------------------+
    | now                              |
    +----------------------------------+
    | 2023-09-12 18:12:18.732645+00:00 |
    +----------------------------------+
    +----------------------------------+
    | now                              |
    +----------------------------------+
    | 2023-09-12 18:12:20.750573+00:00 |
    +----------------------------------+

在数据库 ``test`` 上运行 SQL 命令，并以 YAML 格式输出结果：

.. code:: bash

    $ patronictl -c postgres0.yml query batman -d test -c "SELECT now() AS column_1, 'test' AS column_2" --format yaml
    - column_1: 2023-09-12 18:14:22.052060+00:00
      column_2: test

在成员 ``postgresql2`` 上运行 SQL 命令：

.. code:: bash

    $ patronictl -c postgres0.yml query batman -m postgresql2 -c "SHOW port"
    port
    5434

在任意一个 standby 上运行 SQL 命令：

.. code:: bash

    $ patronictl -c postgres0.yml query batman -r replica -c "SHOW port"
    port
    5433

.. _patronictl_reinit:

patronictl reinit
^^^^^^^^^^^^^^^^^

.. _patronictl_reinit_synopsis:

语法
""""""

.. code:: text

    reinit
      CLUSTER_NAME
      [ MEMBER_NAME [, ... ] ]
      [ --group CITUS_GROUP ]
      [ --wait ]
      [ --force ]
      [ --from-leader ]

.. _patronictl_reinit_description:

说明
""""""""

``patronictl reinit`` 重建由 Patroni 集群中 replica 成员所管理的 Postgres standby 实例。

.. _patronictl_reinit_parameters:

参数
""""""""

``CLUSTER_NAME``
    Patroni 集群的名称。

``MEMBER_NAME``
    要重建其 Postgres 实例的 replica 成员的名称。

    可以指定多个 replica 成员。如果未指定成员，该命令将不执行任何操作。

``--group``
    重建指定 Citus 组中的 replica 成员。

    ``CITUS_GROUP`` 是 Citus 组的 ID。

``--wait``
    等待 Postgres standby 节点的重新初始化完成。

``--force``
    重建 Postgres standby 实例时跳过确认提示的标记。

``--from-leader``
    直接从 leader 获取 basebackup 的标记。

    适用于脚本。

.. _patronictl_reinit_examples:

示例
""""""""

请求重建 Patroni 集群的所有 replica 成员，并立即将控制权返回给调用方：

.. code:: bash

    $ patronictl -c postgres0.yml reinit batman postgresql1 postgresql2 --force
    + Cluster: batman (7277694203142172922) -+-----------+----+-------------+-----+------------+-----+
    | Member      | Host           | Role    | State     | TL | Receive LSN | Lag | Replay LSN | Lag |
    +-------------+----------------+---------+-----------+----+-------------+-----+------------+-----+
    | postgresql0 | 127.0.0.1:5432 | Leader  | running   |  5 |             |     |            |     |
    | postgresql1 | 127.0.0.1:5433 | Replica | streaming |  5 |   0/40004E8 |   0 |  0/40004E8 |   0 |
    | postgresql2 | 127.0.0.1:5434 | Replica | streaming |  5 |   0/40004E8 |   0 |  0/40004E8 |   0 |
    +-------------+----------------+---------+-----------+----+-------------+-----+------------+-----+
    Success: reinitialize for member postgresql1
    Success: reinitialize for member postgresql2

请求重建 ``postgresql2``，并等待其完成：

.. code:: bash

    $ patronictl -c postgres0.yml reinit batman postgresql2 --wait --force
    + Cluster: batman (7277694203142172922) -+-----------+----+-------------+-----+------------+-----+
    | Member      | Host           | Role    | State     | TL | Receive LSN | Lag | Replay LSN | Lag |
    +-------------+----------------+---------+-----------+----+-------------+-----+------------+-----+
    | postgresql0 | 127.0.0.1:5432 | Leader  | running   |  5 |             |     |            |     |
    | postgresql1 | 127.0.0.1:5433 | Replica | streaming |  5 |   0/40004E8 |   0 |  0/40004E8 |   0 |
    | postgresql2 | 127.0.0.1:5434 | Replica | streaming |  5 |   0/40004E8 |   0 |  0/40004E8 |   0 |
    +-------------+----------------+---------+-----------+----+-------------+-----+------------+-----+
    Success: reinitialize for member postgresql2
    Waiting for reinitialize to complete on: postgresql2
    Reinitialize is completed on: postgresql2

请求重建 ``postgresql2``，并直接从 leader 获取 basebackup：

.. code:: bash

    $ patronictl -c postgres0.yml reinit batman postgresql2 --from-leader
    + Cluster: batman (7277694203142172922) -+-----------+----+-------------+-----+------------+-----+
    | Member      | Host           | Role    | State     | TL | Receive LSN | Lag | Replay LSN | Lag |
    +-------------+----------------+---------+-----------+----+-------------+-----+------------+-----+
    | postgresql0 | 127.0.0.1:5432 | Leader  | running   |  5 |             |     |            |     |
    | postgresql1 | 127.0.0.1:5433 | Replica | streaming |  5 |   0/40004E8 |   0 |  0/40004E8 |   0 |
    | postgresql2 | 127.0.0.1:5434 | Replica | streaming |  5 |   0/40004E8 |   0 |  0/40004E8 |   0 |
    +-------------+----------------+---------+-----------+----+-------------+-----+------------+-----+
    Success: reinitialize for member postgresql2

.. _patronictl_reload:

patronictl reload
^^^^^^^^^^^^^^^^^

.. _patronictl_reload_synopsis:

语法
""""""

.. code:: text

    reload
      CLUSTER_NAME
      [ MEMBER_NAME [, ... ] ]
      [ --group CITUS_GROUP ]
      [ { -r | --role } { leader | primary | standby-leader | replica | standby | any } ]
      [ --force ]

.. _patronictl_reload_description:

说明
""""""""

``patronictl reload`` 请求一个或多个 Patroni 成员重新加载本地配置。

即使没有发生任何变化，它也会在被管理的 Postgres 实例上触发 ``pg_ctl reload``。

.. _patronictl_reload_parameters:

参数
""""""""

``CLUSTER_NAME``
    Patroni 集群的名称。

``MEMBER_NAME``
    请求指定的 Patroni 成员重新加载本地配置。

    可以指定多个成员。如果未指定成员，则考虑所有成员。

``--group``
    请求重新加载指定 Citus 组成员的配置。

    ``CITUS_GROUP`` 是 Citus 组的 ID。

``-r``/ ``--role``
    选择具有指定角色的成员。

    角色可以是以下之一：

    - ``leader``：常规 Patroni 集群或 standby Patroni 集群的 leader；或
    - ``primary``：常规 Patroni 集群的 leader；或
    - ``standby-leader``：standby Patroni 集群的 leader；或
    - ``replica``：Patroni 集群的 replica；或
    - ``standby``：与 ``replica`` 相同；或
    - ``any``：任意角色，等同于省略该参数。

``--force``
    请求重新加载本地配置时跳过确认提示的标记。

    适用于脚本。

.. _patronictl_reload_examples:

示例
""""""""

请求重新加载 Patroni 集群所有成员的本地配置：

.. code:: bash

    $ patronictl -c postgres0.yml reload batman --force
    + Cluster: batman (7277694203142172922) -+-----------+----+-------------+-----+------------+-----+
    | Member      | Host           | Role    | State     | TL | Receive LSN | Lag | Replay LSN | Lag |
    +-------------+----------------+---------+-----------+----+-------------+-----+------------+-----+
    | postgresql0 | 127.0.0.1:5432 | Leader  | running   |  5 |             |     |            |     |
    | postgresql1 | 127.0.0.1:5433 | Replica | streaming |  5 |   0/40004E8 |   0 |  0/40004E8 |   0 |
    | postgresql2 | 127.0.0.1:5434 | Replica | streaming |  5 |   0/40004E8 |   0 |  0/40004E8 |   0 |
    +-------------+----------------+---------+-----------+----+-------------+-----+------------+-----+
    Reload request received for member postgresql0 and will be processed within 10 seconds
    Reload request received for member postgresql1 and will be processed within 10 seconds
    Reload request received for member postgresql2 and will be processed within 10 seconds

.. _patronictl_remove:

patronictl remove
^^^^^^^^^^^^^^^^^

.. _patronictl_remove_synopsis:

语法
""""""

.. code:: text

    remove
      CLUSTER_NAME
      [ --group CITUS_GROUP ]
      [ { -f | --format } { pretty | tsv | json | yaml } ]

.. _patronictl_remove_description:

说明
""""""""

``patronictl remove`` 从 DCS 中移除集群的信息。

这是一个交互式操作。

.. warning::
    此操作将销毁 DCS 中 Patroni 集群的信息。

.. _patronictl_remove_parameters:

参数
""""""""

``CLUSTER_NAME``
    Patroni 集群的名称。

``--group``
    移除与指定 Citus 组相关的 Patroni 集群信息。

    ``CITUS_GROUP`` 是 Citus 组的 ID。

``-f``/ ``--format``
    在提示确认时，输出中成员列表的格式。

    格式可以是以下之一：

    - ``pretty``：以美观的表格形式输出成员；或
    - ``tsv``：以表格形式输出成员，列之间用 ``\t`` 分隔；或
    - ``json``：以 JSON 格式输出成员；或
    - ``yaml``：以 YAML 格式输出成员。

    默认格式为 ``pretty``。

.. _patronictl_remove_examples:

示例
""""""""

从 DCS 中移除 Patroni 集群 ``batman`` 的信息：

.. code:: bash

    $ patronictl -c postgres0.yml remove batman
    + Cluster: batman (7277694203142172922) -+-----------+----+-------------+-----+------------+-----+
    | Member      | Host           | Role    | State     | TL | Receive LSN | Lag | Replay LSN | Lag |
    +-------------+----------------+---------+-----------+----+-------------+-----+------------+-----+
    | postgresql0 | 127.0.0.1:5432 | Leader  | running   |  5 |             |     |            |     |
    | postgresql1 | 127.0.0.1:5433 | Replica | streaming |  5 |   0/40004E8 |   0 |  0/40004E8 |   0 |
    | postgresql2 | 127.0.0.1:5434 | Replica | streaming |  5 |   0/40004E8 |   0 |  0/40004E8 |   0 |
    +-------------+----------------+---------+-----------+----+-------------+-----+------------+-----+
    Please confirm the cluster name to remove: batman
    You are about to remove all information in DCS for batman, please type: "Yes I am aware": Yes I am aware
    This cluster currently is healthy. Please specify the leader name to continue: postgresql0

.. _patronictl_restart:

patronictl restart
^^^^^^^^^^^^^^^^^^

.. _patronictl_restart_synopsis:

语法
""""""

.. code:: text

    restart
      CLUSTER_NAME
      [ MEMBER_NAME [, ...] ]
      [ --group CITUS_GROUP ]
      [ { -r | --role } { leader | primary | standby-leader | replica | standby | any } ]
      [ --any ]
      [ --pg-version PG_VERSION ]
      [ --pending ]
      [ --timeout TIMEOUT ]
      [ --scheduled TIMESTAMP ]
      [ --force ]

.. _patronictl_restart_description:

说明
""""""""

``patronictl restart`` 请求重启 Patroni 集群中成员所管理的 Postgres 实例。

该 restart 可以立即执行，也可以计划在稍后执行。

.. _patronictl_restart_parameters:

参数
""""""""

``CLUSTER_NAME``
    Patroni 集群的名称。

``--group``
    重启与指定 Citus 组相关的 Patroni 集群。

    ``CITUS_GROUP`` 是 Citus 组的 ID。

``-r``/ ``--role``
    选择具有指定角色的成员。

    角色可以是以下之一：

    - ``leader``：常规 Patroni 集群或 standby Patroni 集群的 leader；或
    - ``primary``：常规 Patroni 集群的 leader；或
    - ``standby-leader``：standby Patroni 集群的 leader；或
    - ``replica``：Patroni 集群的 replica；或
    - ``standby``：与 ``replica`` 相同；或
    - ``any``：任意角色，等同于省略该参数。

``--any``
    在与给定筛选条件匹配的节点中，随机重启一个节点。

``--pg-version``
    仅选择所管理的 Postgres 实例版本早于指定版本的成员。

    ``PG_VERSION`` 是要进行比较的 Postgres 版本。

``--pending``
    仅选择被标记为 ``Pending restart`` 的成员。

``--timeout``
    如果 restart 耗时超过指定的超时时间，则中止该 restart；如果问题出在 primary 上，则 failover 到 replica。

    ``TIMEOUT`` 是在中止 restart 之前等待的秒数。

``--scheduled``
    计划在给定时间戳执行 restart。

    ``TIMESTAMP`` 是 restart 应发生的时间戳。请以无歧义的格式指定，最好包含时区。你也可以使用字面量 ``now`` 让 restart 立即执行。

``--force``
    请求 restart 操作时跳过确认提示的标记。

    适用于脚本。

.. _patronictl_restart_examples:

示例
""""""""

立即重启集群的所有成员：

.. code:: bash

    $ patronictl -c postgres0.yml restart batman --force
    + Cluster: batman (7277694203142172922) -+-----------+----+-------------+-----+------------+-----+
    | Member      | Host           | Role    | State     | TL | Receive LSN | Lag | Replay LSN | Lag |
    +-------------+----------------+---------+-----------+----+-------------+-----+------------+-----+
    | postgresql0 | 127.0.0.1:5432 | Leader  | running   |  6 |             |     |            |     |
    | postgresql1 | 127.0.0.1:5433 | Replica | streaming |  6 |   0/40004E8 |   0 |  0/40004E8 |   0 |
    | postgresql2 | 127.0.0.1:5434 | Replica | streaming |  6 |   0/40004E8 |   0 |  0/40004E8 |   0 |
    +-------------+----------------+---------+-----------+----+-------------+-----+------------+-----+
    Success: restart on member postgresql0
    Success: restart on member postgresql1
    Success: restart on member postgresql2

立即重启集群的某个随机成员：

.. code:: bash

    $ patronictl -c postgres0.yml restart batman --any --force
    + Cluster: batman (7277694203142172922) -+-----------+----+-------------+-----+------------+-----+
    | Member      | Host           | Role    | State     | TL | Receive LSN | Lag | Replay LSN | Lag |
    +-------------+----------------+---------+-----------+----+-------------+-----+------------+-----+
    | postgresql0 | 127.0.0.1:5432 | Leader  | running   |  6 |             |     |            |     |
    | postgresql1 | 127.0.0.1:5433 | Replica | streaming |  6 |   0/40004E8 |   0 |  0/40004E8 |   0 |
    | postgresql2 | 127.0.0.1:5434 | Replica | streaming |  6 |   0/40004E8 |   0 |  0/40004E8 |   0 |
    +-------------+----------------+---------+-----------+----+-------------+-----+------------+-----+
    Success: restart on member postgresql1

计划在 ``2023-09-13T18:00-03:00`` 执行 restart：

.. code:: bash

    $ patronictl -c postgres0.yml restart batman --scheduled 2023-09-13T18:00-03:00 --force
    + Cluster: batman (7277694203142172922) -+-----------+----+-------------+-----+------------+-----+
    | Member      | Host           | Role    | State     | TL | Receive LSN | Lag | Replay LSN | Lag |
    +-------------+----------------+---------+-----------+----+-------------+-----+------------+-----+
    | postgresql0 | 127.0.0.1:5432 | Leader  | running   |  6 |             |     |            |     |
    | postgresql1 | 127.0.0.1:5433 | Replica | streaming |  6 |   0/40004E8 |   0 |  0/40004E8 |   0 |
    | postgresql2 | 127.0.0.1:5434 | Replica | streaming |  6 |   0/40004E8 |   0 |  0/40004E8 |   0 |
    +-------------+----------------+---------+-----------+----+-------------+-----+------------+-----+
    Success: restart scheduled on member postgresql0
    Success: restart scheduled on member postgresql1
    Success: restart scheduled on member postgresql2

.. _patronictl_resume:

patronictl resume
^^^^^^^^^^^^^^^^^

.. _patronictl_resume_synopsis:

语法
""""""

.. code:: text

    resume
      [ CLUSTER_NAME ]
      [ --group CITUS_GROUP ]
      [ --wait ]

.. _patronictl_resume_description:

说明
""""""""

``patronictl resume`` 将 Patroni 集群退出维护模式，并重新启用自动 failover。

.. _patronictl_resume_parameters:

参数
""""""""

``CLUSTER_NAME``
    Patroni 集群的名称。

    如果未指定，``patronictl`` 将尝试从 ``scope`` 配置中获取该值（如果存在）。

``--group``
    恢复指定的 Citus 组。

    ``CITUS_GROUP`` 是 Citus 组的 ID。
    
    如果未指定，``patronictl`` 将尝试从 ``citus.group`` 配置中获取该值（如果存在）。

``--wait``
    等待所有 Patroni 成员都取消暂停后再将控制权返回给调用方。

.. _patronictl_resume_examples:

示例
""""""""

将集群退出维护模式：

.. code:: bash

    $ patronictl -c postgres0.yml resume batman --wait
    'resume' request sent, waiting until it is recognized by all nodes
    Success: cluster management is resumed

.. _patronictl_show_config:

patronictl show-config
^^^^^^^^^^^^^^^^^^^^^^

.. _patronictl_show_config_synopsis:

语法
""""""

.. code:: text

    show-config
      [ CLUSTER_NAME ]
      [ --group CITUS_GROUP ]

.. _patronictl_show_config_description:

说明
""""""""

``patronictl show-config`` 显示存储在 DCS 中的集群动态配置。

.. _patronictl_show_config_parameters:

参数
""""""""

``CLUSTER_NAME``
    Patroni 集群的名称。

    如果未指定，``patronictl`` 将尝试从 ``scope`` 配置中获取该值（如果存在）。

``--group``
    显示指定 Citus 组的动态配置。

    ``CITUS_GROUP`` 是 Citus 组的 ID。
    
    如果未指定，``patronictl`` 将尝试从 ``citus.group`` 配置中获取该值（如果存在）。

.. _patronictl_show_config_examples:

示例
""""""""

显示集群 ``batman`` 的动态配置：

.. code:: bash

    $ patronictl -c postgres0.yml show-config batman
    loop_wait: 10
    postgresql:
      parameters:
        max_connections: 250
      pg_hba:
      - host replication replicator 127.0.0.1/32 md5
      - host all all 0.0.0.0/0 md5
      use_pg_rewind: true
    retry_timeout: 10
    ttl: 30

.. _patronictl_switchover:

patronictl switchover
^^^^^^^^^^^^^^^^^^^^^

.. _patronictl_switchover_synopsis:

语法
""""""

.. code:: text

    switchover
      [ CLUSTER_NAME ]
      [ --group CITUS_GROUP ]
      [ { --leader | --primary } LEADER_NAME ]
      --candidate CANDIDATE_NAME
      [ --force ]

.. _patronictl_switchover_description:

说明
""""""""

``patronictl switchover`` 在集群中执行 switchover。

它专为集群健康的情况而设计，例如：

- 存在 leader；
- 在同步集群中有可用的 synchronous standby。

.. note::
    如果你的集群不健康，你可能会对 ``patronictl failover`` 更感兴趣。

.. _patronictl_switchover_parameters:

参数
""""""""

``CLUSTER_NAME``
    Patroni 集群的名称。

    如果未指定，``patronictl`` 将尝试从 ``scope`` 配置中获取该值（如果存在）。

``--group``
    在指定的 Citus 组中执行 switchover。

    ``CITUS_GROUP`` 是 Citus 组的 ID。

``--leader``/ ``--primary``
    指定 switchover 时将被降级的 leader。

    ``LEADER_NAME`` 应与集群中当前 leader 的名称一致。

``--candidate``
    switchover 时将被提升并承担 primary role 的节点。

    ``CANDIDATE_NAME`` 是将被提升节点的名称。

``--scheduled``
    计划在给定时间戳执行 switchover。

    ``TIMESTAMP`` 是 switchover 应发生的时间戳。请以无歧义的格式指定，最好包含时区。你也可以使用字面量 ``now`` 让 switchover 立即执行。

``--force``
    执行 switchover 时跳过确认提示的标记。

    适用于脚本。

.. _patronictl_switchover_examples:

示例
""""""""

使用节点 ``postgresql2`` 执行 switchover：

.. code:: bash

    $ patronictl -c postgres0.yml switchover batman --leader postgresql0 --candidate postgresql2 --force
    Current cluster topology
    + Cluster: batman (7277694203142172922) -+-----------+----+-------------+-----+------------+-----+
    | Member      | Host           | Role    | State     | TL | Receive LSN | Lag | Replay LSN | Lag |
    +-------------+----------------+---------+-----------+----+-------------+-----+------------+-----+
    | postgresql0 | 127.0.0.1:5432 | Leader  | running   |  6 |             |     |            |     |
    | postgresql1 | 127.0.0.1:5433 | Replica | streaming |  6 |   0/40004E8 |   0 |  0/40004E8 |   0 |
    | postgresql2 | 127.0.0.1:5434 | Replica | streaming |  6 |   0/40004E8 |   0 |  0/40004E8 |   0 |
    +-------------+----------------+---------+-----------+----+-------------+-----+------------+-----+
    2023-09-13 14:15:23.07497 Successfully switched over to "postgresql2"
    + Cluster: batman (7277694203142172922) -+---------+----+-------------+---------+------------+---------+
    | Member      | Host           | Role    | State   | TL | Receive LSN |     Lag | Replay LSN |     Lag |
    +-------------+----------------+---------+---------+----+-------------+---------+------------+---------+
    | postgresql0 | 127.0.0.1:5432 | Replica | stopped |    |     unknown | unknown |    unknown | unknown |
    | postgresql1 | 127.0.0.1:5433 | Replica | running |  6 |   0/4000188 |       0 |  0/4000188 |       0 |
    | postgresql2 | 127.0.0.1:5434 | Leader  | running |  6 |             |         |            |         |
    +-------------+----------------+---------+---------+----+-------------+---------+------------+---------+

计划在 ``2023-09-13T18:00:00-03:00`` 于 ``postgresql0`` 和 ``postgresql2`` 之间执行 switchover：

.. code:: bash

    $ patronictl -c postgres0.yml switchover batman --leader postgresql0 --candidate postgresql2 --scheduled 2023-09-13T18:00-03:00 --force
    Current cluster topology
    + Cluster: batman (7277694203142172922) -+-----------+----+-------------+-----+------------+-----+
    | Member      | Host           | Role    | State     | TL | Receive LSN | Lag | Replay LSN | Lag |
    +-------------+----------------+---------+-----------+----+-------------+-----+------------+-----+
    | postgresql0 | 127.0.0.1:5432 | Leader  | running   |  8 |             |     |            |     |
    | postgresql1 | 127.0.0.1:5433 | Replica | streaming |  8 |   0/40004E8 |   0 |  0/40004E8 |   0 |
    | postgresql2 | 127.0.0.1:5434 | Replica | streaming |  8 |   0/40004E8 |   0 |  0/40004E8 |   0 |
    +-------------+----------------+---------+-----------+----+-------------+-----+------------+-----+
    2023-09-13 14:18:11.20661 Switchover scheduled
    + Cluster: batman (7277694203142172922) -+-----------+----+-------------+-----+------------+-----+
    | Member      | Host           | Role    | State     | TL | Receive LSN | Lag | Replay LSN | Lag |
    +-------------+----------------+---------+-----------+----+-------------+-----+------------+-----+
    | postgresql0 | 127.0.0.1:5432 | Leader  | running   |  8 |             |     |            |     |
    | postgresql1 | 127.0.0.1:5433 | Replica | streaming |  8 |   0/40004E8 |   0 |  0/40004E8 |   0 |
    | postgresql2 | 127.0.0.1:5434 | Replica | streaming |  8 |   0/40004E8 |   0 |  0/40004E8 |   0 |
    +-------------+----------------+---------+-----------+----+-------------+-----+------------+-----+
    Switchover scheduled at: 2023-09-13T18:00:00-03:00
                        from: postgresql0
                        to: postgresql2

.. _patronictl_topology:

patronictl topology
^^^^^^^^^^^^^^^^^^^

.. _patronictl_topology_synopsis:

语法
""""""

.. code:: text

    topology
      [ CLUSTER_NAME [, ... ] ]
      [ --group CITUS_GROUP ]
      [ { -W | { -w | --watch } TIME } ]

.. _patronictl_topology_description:

说明
""""""""

``patronictl topology`` 以树状视图的方式显示 Patroni 集群及其成员的信息。

输出中包含以下信息：

``Cluster``
    Patroni 集群的名称。

    .. note::
        显示在表头中。

``System identifier``
    Postgres 系统标识符。

    .. note::
        显示在表头中。

``Member``
    Patroni 成员的名称。

    .. note::
        此列中的信息以树状视图的形式显示成员，反映复制连接关系。

``Host``
    成员所在的主机。

``Role``
    成员当前的 role。

    可以是以下之一：

    * ``Leader``：常规 Patroni 集群当前的 leader；或
    * ``Standby Leader``：Patroni standby 集群当前的 leader；或
    * ``Sync Standby``：启用了同步模式的 Patroni 集群中的 synchronous standby；或
    * ``Replica``：Patroni 集群的常规 standby。

``State``
    Patroni 成员中 Postgres 的当前状态。

    以下是可能状态中的一些示例：

    * ``running``：如果 Postgres 当前正在运行；
    * ``streaming``：如果是 replica 且 Postgres 当前正从 primary 节点流式接收 WAL；
    * ``in archive recovery``：如果是 replica 且 Postgres 当前正在从归档中获取 WAL；
    * ``stopped``：如果 Postgres 已被关闭；
    * ``crashed``：如果 Postgres 已崩溃。

``TL``
    Patroni 成员中 Postgres 当前的 timeline。

``Receive LSN``
    该成员通过流复制接收并同步到磁盘的最后一个预写日志位置（``pg_catalog.pg_last_(xlog|wal)_receive_(location|lsn)()``）。

``Receive Lag``
    成员的 ``Receive LSN`` 位置与其上游之间的复制延迟，以 MB 为单位。

``Replay LSN``
    该成员在恢复期间重放的最后一个预写日志位置（``pg_catalog.pg_last_(xlog|wal)_replay_(location|lsn)()``）。

``Replay Lag``
    成员的 ``Replay LSN`` 位置与其上游之间的复制延迟，以 MB 为单位。

除此之外，输出中还可能包含以下信息：

``Group``
    Citus 组 ID。

    .. note::
        显示在表头中。

        仅当是 Citus 集群时显示。

``Pending restart``
    ``*`` 表示节点需要 restart 才能让某些 Postgres 配置生效。空值表示节点不需要 restart。

    .. note::
        作为成员属性显示。

        当节点需要 restart 时显示。

``Scheduled restart``
    为 Patroni 成员所管理的 Postgres 实例计划 restart 的时间戳。空值表示该成员没有计划 restart。

    .. note::
        作为成员属性显示。

        当节点有计划 restart 时显示。

``Tags``
    包含为 Patroni 成员设置的标签。空值表示尚未配置标签，或标签均配置为默认值。

    .. note::
        作为成员属性显示。

        当节点有任何自定义标签，或存在值非默认的默认标签时显示。

``Scheduled switchover``
    为 Patroni 集群计划 switchover 的时间戳（如果有）。

    .. note::
        显示在表尾中。

        仅当存在计划的 switchover 时显示。

``Maintenance mode``

    集群监控当前是否已暂停。

    .. note::
        显示在表尾中。

        仅当集群处于暂停状态时显示。

.. _patronictl_topology_parameters:

参数
""""""""

``CLUSTER_NAME``
    Patroni 集群的名称。

    如果未指定，``patronictl`` 将尝试从 ``scope`` 配置中获取该值（如果存在）。

``--group``
    显示指定 Citus 组成员的信息。

    ``CITUS_GROUP`` 是 Citus 组的 ID。

``-W``
    每 2 秒自动刷新信息。

``-w``/ ``--watch``
    以指定的间隔自动刷新信息。

    ``TIME`` 是刷新间隔，单位为秒。

.. _patronictl_topology_examples:

示例
""""""""

显示集群 ``batman`` 的拓扑——``postgresql1`` 和 ``postgresql2`` 正在从 ``postgresql0`` 复制：

.. code:: bash

    $ patronictl -c postgres0.yml topology batman
    + Cluster: batman (7277694203142172922) ---+-----------+----+-------------+-----+------------+-----+
    | Member        | Host           | Role    | State     | TL | Receive LSN | Lag | Replay LSN | Lag |
    +---------------+----------------+---------+-----------+----+-------------+-----+------------+-----+
    | postgresql0   | 127.0.0.1:5432 | Leader  | running   |  8 |             |     |            |     |
    | + postgresql1 | 127.0.0.1:5433 | Replica | streaming |  8 |   0/40004E8 |   0 |  0/40004E8 |   0 |
    | + postgresql2 | 127.0.0.1:5434 | Replica | streaming |  8 |   0/40004E8 |   0 |  0/40004E8 |   0 |
    +---------------+----------------+---------+-----------+----+-------------+-----+------------+-----+

.. _patronictl_version:

patronictl version
^^^^^^^^^^^^^^^^^^

.. _patronictl_version_synopsis:

语法
""""""

.. code:: text

    version
      [ CLUSTER_NAME [, ... ] ]
      [ MEMBER_NAME [, ... ] ]
      [ --group CITUS_GROUP ]

.. _patronictl_version_description:

说明
""""""""

``patronictl version`` 获取 ``patronictl`` 应用程序的版本。此外，它还可能包含 Patroni 集群及其成员的版本信息。

.. _patronictl_version_parameters:

参数
""""""""

``CLUSTER_NAME``
    Patroni 集群的名称。

``MEMBER_NAME``
    Patroni 集群成员的名称。

``--group``
    考虑具有指定 Citus 组的 Patroni 集群。

    ``CITUS_GROUP`` 是 Citus 组的 ID。

.. _patronictl_version_examples:

示例
""""""""

仅获取 ``patronictl`` 的版本：

.. code:: bash

    $ patronictl -c postgres0.yml version
    patronictl version 4.0.0

获取 ``patronictl`` 以及集群 ``batman`` 所有成员的版本：

.. code:: bash

    $ patronictl -c postgres0.yml version batman
    patronictl version 4.0.0

    postgresql0: Patroni 4.0.0 PostgreSQL 16.4
    postgresql1: Patroni 4.0.0 PostgreSQL 16.4
    postgresql2: Patroni 4.0.0 PostgreSQL 16.4

获取 ``patronictl`` 以及集群 ``batman`` 中成员 ``postgresql1`` 和 ``postgresql2`` 的版本：

.. code:: bash

    $ patronictl -c postgres0.yml version batman postgresql1 postgresql2
    patronictl version 4.0.0

    postgresql1: Patroni 4.0.0 PostgreSQL 16.4
    postgresql2: Patroni 4.0.0 PostgreSQL 16.4
