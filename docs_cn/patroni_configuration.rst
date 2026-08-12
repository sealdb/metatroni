.. _patroni_configuration:

Patroni 配置
=====================

.. toctree::
   :hidden:

   dynamic_configuration
   yaml_configuration
   ENVIRONMENT


Patroni 配置有 3 种类型：

- 全局 :ref:`dynamic configuration <dynamic_configuration>`。
	这些选项存储在 DCS（分布式配置存储）中，并应用于所有集群节点。
	可以使用 :ref:`patronictl_edit_config` 工具或 Patroni 的 :ref:`REST API <rest_api>` 随时设置动态配置。
	如果更改的选项不属于启动配置的一部分，它们将异步应用（在下一个唤醒周期）
	到每个节点，随后该节点会重新加载配置。
	如果节点需要重启才能应用配置（对于 context 为 postmaster 的 `PostgreSQL 参数 <https://www.postgresql.org/docs/current/view-pg-settings.html>`__，如果它们的值
	发生了变化），会在 members.data JSON 中设置一个表示此情况的特殊标志 ``pending_restart``。
	此外，节点状态会通过显示 ``"restart_pending": true`` 来表明这一点。

- 本地 :ref:`configuration file <yaml_configuration>` （patroni.yml）。
	这些选项在配置文件中定义，优先级高于动态配置。
	可以通过向 Patroni 进程发送 SIGHUP、执行 ``POST /reload`` REST-API 请求或运行 :ref:`patronictl_reload` 来在运行时更改并重新加载 ``patroni.yml`` （无需重启 Patroni）。本地配置可以是单个 YAML 文件，也可以是一个目录。当它是一个目录时，该目录中的所有 YAML 文件将按排序顺序逐一加载。如果一个键在多个文件中定义，则以最后一个文件中的定义为准。

- :ref:`Environment configuration <environment>`。
	可以使用环境变量设置/覆盖部分「Local」配置参数。
	当您在动态环境中运行并且无法提前知道某些参数时，环境配置非常有用（例如，当您在 ``docker`` 中运行时无法知道外部 IP 地址）。

.. _important_configuration_rules:

重要规则
---------------

由 Patroni 控制的 PostgreSQL 参数
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

某些 PostgreSQL 参数在 **primary 和 replica 上必须保持相同的值 **。对于这些参数，** 在本地 patroni 配置文件或通过环境变量设置的值均不生效**。要修改或设置它们的值，必须更改 DCS 中的共享配置。以下是此类参数的实际列表以及默认值和最小值：

- **max_connections**：默认值 100，最小值 25
- **max_locks_per_transaction**：默认值 64，最小值 32
- **max_worker_processes**：默认值 8，最小值 2
- **max_prepared_transactions**：默认值 0，最小值 0
- **wal_level**：默认值 hot_standby，可接受的值：hot_standby、replica、logical
- **track_commit_timestamp**：默认值 off 

对于以下参数，PostgreSQL 不要求 primary 与所有 replica 之间的值相同。但是，考虑到 replica 随时可能成为 primary，对它们设置不同的值实际上没有意义；因此，**Patroni 限制只能通过**:ref:`dynamic configuration <dynamic_configuration>` **来设置它们的值**。

- **max_wal_senders**：默认值 10，最小值 3
- **max_replication_slots**：默认值 10，最小值 4
- **wal_keep_segments**：默认值 8，最小值 1
- **wal_keep_size**：默认值 128MB，最小值 16MB
- **wal_log_hints**：on

这些参数都会经过验证，以确保其取值合理或满足最小值要求。

还有一些其他由 Patroni 控制的 Postgres 参数：

- **listen_addresses**—— 从 ``postgresql.listen`` 或 ``PATRONI_POSTGRESQL_LISTEN`` 环境变量设置
- **port**—— 从 ``postgresql.listen`` 或 ``PATRONI_POSTGRESQL_LISTEN`` 环境变量设置
- **cluster_name**—— 从 ``scope`` 或 ``PATRONI_SCOPE`` 环境变量设置
- **hot_standby: on**

为安全起见，上述列表中的参数会被写入 ``postgresql.conf``，并作为参数列表传递给 ``postgres``，这使它们具有最高优先级（``wal_keep_segments`` 和 ``wal_keep_size`` 除外），甚至高于 `ALTER SYSTEM <https://www.postgresql.org/docs/current/static/sql-altersystem.html>`__

还有一些参数，如 **postgresql.listen**、**postgresql.data_dir**，**只能在本地设置**，即通过 Patroni 的 :ref:`config file <yaml_configuration>` 或 :ref:`configuration <environment>` 变量设置。在大多数情况下，本地配置将覆盖动态配置。


应用本地或动态配置选项时，将执行以下操作：

- 节点首先检查是否存在 `postgresql.base.conf` 文件，或者是否设置了 ``custom_conf`` 参数。
- 如果设置了 ``custom_conf`` 参数，则使用它指定的文件作为基础配置，并忽略 `postgresql.base.conf` 和 `postgresql.conf`。
- 如果未设置 ``custom_conf`` 参数且 `postgresql.base.conf` 存在，则该文件包含重命名后的「原始」配置，并被用作基础配置。
- 如果既没有 ``custom_conf`` 也没有 `postgresql.base.conf`，则原始的 `postgresql.conf` 会被重命名为 `postgresql.base.conf` 并用作基础配置。
- 动态选项（除上述例外之外）会被转储到 `postgresql.conf` 中，并在
  `postgresql.conf` 中设置一个指向基础配置（`postgresql.base.conf` 或 ``custom_conf`` 指定的文件）的 include。
  因此，我们无需重新读取配置文件来检查 include 是否存在，就可以应用新的选项。
- 某些对 Patroni 管理集群至关重要的参数会通过命令行进行覆盖。
- 如果更改了需要重启的选项（我们应查看 pg_settings 中的 context 以及这些选项的
  实际值），则会在该节点上设置 pending_restart 标志。该标志会在任何重启时被重置。

参数将按以下顺序应用（运行时的参数优先级最高）：

1. 从文件 `postgresql.base.conf` 加载参数（如果设置了，则从 ``custom_conf`` 文件加载）
2. 从文件 `postgresql.conf` 加载参数
3. 从文件 `postgresql.auto.conf` 加载参数
4. 使用 `-o --name=value` 设置运行时参数

这允许为所有节点进行配置（2），使用 ``ALTER SYSTEM`` 为特定节点进行配置（3），并确保对 Patroni 运行至关重要的参数得到强制执行（4），同时也为不经过 Patroni 而直接管理 `postgresql.conf` 的配置工具留出了空间（1）。

.. _shared_memory_gucs:

影响共享内存的 PostgreSQL 参数
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

PostgreSQL 有一些参数决定其使用的共享内存的大小：

- **max_connections**
- **max_prepared_transactions**
- **max_locks_per_transaction**
- **max_wal_senders**
- **max_worker_processes**

更改这些参数需要重启 PostgreSQL 才能生效，并且 standby 节点上的共享内存结构不能小于 primary 节点。

如前所述，Patroni 限制通过 :ref:`dynamic configuration <dynamic_configuration>` 更改它们的值，这通常包括：

1. 通过 :ref:`patronictl_edit_config` 应用更改（或通过 REST API 的 ``/config`` 端点）
2. 通过 :ref:`patronictl_restart` 重启节点（或通过 REST API 的 ``/restart`` 端点）

**注意：** 请记住，您应该通过 :ref:`patronictl_restart` 命令或 REST API 的 ``/restart`` 端点重启 PostgreSQL 节点。尝试通过重启 Patroni 守护进程（例如执行 ``systemctl restart patroni``）来重启 PostgreSQL，如果您正在重启 primary 节点，可能会导致集群发生 failover。

但是，由于这些设置管理共享内存，在重启节点时应格外小心：

* 如果您想 **增加** 其中任何设置的值：

   1. 先重启所有 standby
   2. 之后再重启 primary

* 如果您想 **减少** 其中任何设置的值：

   1. 先重启 primary
   2. 之后再重启所有 standby

**注意：** 如果您在 **减少** 其中任何设置的值后试图一次性重启所有节点，Patroni 将忽略此更改，并以原始设置值重启 standby，从而要求您稍后再次重启 standby。Patroni 这样做是为了防止 standby 陷入无限崩溃循环，因为如果您试图将其中任何参数设置为低于 Standby 节点上 ``pg_controldata`` 中所见的值，PostgreSQL 会以 `FATAL` 消息退出。换句话说，只有当 standby 的 ``pg_controldata`` 在 primary 上这些更改方面与 primary 保持同步后，我们才能减少 standby 上的该设置。

更多相关信息可在 `PostgreSQL 管理员概览 <https://www.postgresql.org/docs/current/hot-standby.html#HOT-STANDBY-ADMIN>`__ 中找到。

Patroni 配置参数
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

此外，以下 Patroni 配置选项 **只能通过动态配置更改**：

- **ttl**：30
- **loop_wait**：10
- **retry_timeouts**：10
- **maximum_lag_on_failover**：1048576
- **max_timelines_history**：0
- **check_timeline**：false
- **postgresql.use_slots**：true

更改这些选项时，Patroni 将读取存储在 DCS 中的配置的相关部分，并更改其运行时值。

每当配置发生变化时，Patroni 节点都会将 DCS 选项的状态转储到位于 Postgres 数据目录中的 ``patroni.dynamic.json`` 文件中。只有当这些选项在 DCS 中完全不存在或无效时，才允许 leader 从磁盘转储中恢复这些选项。


.. _validate_generate_config:

配置的生成与验证
---------------------------------------

Patroni 提供命令行接口，用于 Patroni :ref:`local configuration <yaml_configuration>` 的生成和验证。使用 ``patroni`` 可执行文件，您可以：

- 创建示例本地 Patroni 配置；
- 为本地运行的 PostgreSQL 实例创建 Patroni 配置文件（例如，作为 :ref:`Patroni integration <existing_data>` 的准备工作）；
- 验证给定的 Patroni 配置文件。

.. _generate_sample_config:

示例 Patroni 配置
^^^^^^^^^^^^^^^^^^^^

.. code:: text

   patroni --generate-sample-config [configfile]

描述
"""""""""""

生成一个 ``yaml`` 格式的示例 Patroni 配置文件。
参数值优先使用 :ref:`Environment configuration <environment>` 中定义的值；如果未设置，则使用 Patroni 中的默认值，或者为那些需要用户稍后定义的值使用 ``#FIXME`` 字符串。

一些默认值基于本地环境定义：

   -  **postgresql.listen**：``gethostname`` 调用针对当前机器主机名返回的 IP 地址以及标准 ``5432`` 端口。
   -  **postgresql.connect_address**：``gethostname`` 调用针对当前机器主机名返回的 IP 地址以及标准 ``5432`` 端口。
   -  **postgresql.authentication.rewind**：仅当可以从二进制文件确定 PostgreSQL 版本且版本为 11 或更高时才会定义。
   -  **restapi.listen**：``gethostname`` 调用针对当前机器主机名返回的 IP 地址以及标准 ``8008`` 端口。
   -  **restapi.connect_address**：``gethostname`` 调用针对当前机器主机名返回的 IP 地址以及标准 ``8008`` 端口。

参数
""""""""""

``configfile``—— 用于存储结果的配置文件的完整路径。如果未提供，结果将输出到 ``stdout``。

.. _generate_config:

针对正在运行的实例的 Patroni 配置
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code:: text

   patroni --generate-config [--dsn DSN] [configfile]

描述
""""""""""

为本地运行的 PostgreSQL 实例生成 ``yaml`` 格式的 Patroni 配置。 
PostgreSQL 连接将使用提供的 DSN（优先）或 PostgreSQL `环境变量 <https://www.postgresql.org/docs/current/libpq-envars.html>`__。如果未提供密码，则应通过提示符输入。

源 Postgres 实例中定义的所有非内部 GUC，无论它们是通过配置文件、postmaster 命令行还是环境变量设置的，都将用作以下 Patroni 配置参数的来源：

   -  **scope**：``cluster_name`` GUC 的值；
   -  **postgresql.listen**：``listen_addresses`` 和 ``port`` GUC 的值；
   -  **postgresql.datadir**：``data_directory`` GUC 的值；
   -  **postgresql.parameters**：``archive_command``、``restore_command``、``archive_cleanup_command``、``recovery_end_command``、``ssl_passphrase_command``、``hba_file``、``ident_file``、``config_file`` GUC 的值；
   -  **bootstrap.dcs**：收集到的所有其他 PostgreSQL GUC。

如果未从 Postgres GUC 中设置 ``scope``、``postgresql.listen`` 或 ``postgresql.datadir``，则使用相应的 :ref:`Environment configuration <environment>` 值。

应用于值定义的其他规则：

   -  **name**：如果设置了 ``PATRONI_NAME`` 环境变量则使用其值，否则使用当前机器的主机名。
   -  **postgresql.bin_dir**：从正在运行的实例获取的 Postgres 二进制文件的路径。
   -  **postgresql.connect_address**：``gethostname`` 调用针对当前机器主机名返回的 IP 地址，以及实例连接所使用的端口或 ``port`` GUC 的值。
   -  **postgresql.authentication.superuser**：实例连接所使用的配置；
   -  **postgresql.pg_hba**：从源实例的 ``hba_file`` 中收集的行。
   -  **postgresql.pg_ident**：从源实例的 ``ident_file`` 中收集的行。
   -  **restapi.listen**：``gethostname`` 调用针对当前机器主机名返回的 IP 地址以及标准 ``8008`` 端口。
   -  **restapi.connect_address**：``gethostname`` 调用针对当前机器主机名返回的 IP 地址以及标准 ``8008`` 端口。

使用 :ref:`Environment configuration <environment>` 定义的其他参数也会包含在配置中。

参数
""""""""""

``configfile``
    用于存储结果的配置文件的完整路径。如果未提供，结果将输出到 ``stdout``。

``dsn``
    可选的 DSN 字符串，用于从本地 PostgreSQL 实例获取 GUC 值。


验证 Patroni 配置
^^^^^^^^^^^^^^^^^^^^^^

.. code:: text

   patroni --validate-config [configfile] [--ignore-listen-port | -i]

描述
""""""""""

验证给定的 Patroni 配置，并打印关于未通过检查项的信息。

参数
""""""""""

``configfile``
    要检查的配置文件的完整路径。如果未指定或文件不存在，将尝试从 ``PATRONI_CONFIG_VARIABLE`` 环境变量读取，如果未设置，则从 :ref:`Patroni environment variables <environment>` 读取。

``--ignore-listen-port | -i``
    可选标志，用于在验证 ``configfile`` 时忽略 ``listen`` 端口已被占用而导致的绑定失败。

``--print | -p``
    可选标志，用于在本地配置（包括环境配置覆盖项）成功验证后将其打印出来。
