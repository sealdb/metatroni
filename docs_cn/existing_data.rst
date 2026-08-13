.. _existing_data:

将独立实例转换为 Patroni 集群
=============================

本节介绍将独立运行的 PostgreSQL 实例转换为 Patroni 集群的过程。

如果要在不使用已有 PostgreSQL 实例的情况下部署 Patroni 集群，请参阅 :ref:`Running and Configuring <running_configuring>`。

操作步骤
--------

下面概述了将现有 Postgres 集群转换为 Patroni 管理集群的步骤。在这些步骤中，我们假设现有集群中的所有节点目前都在运行，并且你 *不打算* 在迁移进行期间更改 Postgres 配置。步骤如下：

#. 按照 Patroni 配置的 :ref:`authentication <postgresql_settings>` 部分的说明创建 Postgres 用户。你可以在下面的代码块中找到创建用户的示例 SQL 命令，需要根据你的环境替换其中的用户名和密码。如果已经存在相关用户，则可以跳过此步骤。

   .. code-block:: sql

      -- Patroni superuser
      -- Replace PATRONI_SUPERUSER_USERNAME and PATRONI_SUPERUSER_PASSWORD accordingly
      CREATE USER PATRONI_SUPERUSER_USERNAME WITH SUPERUSER ENCRYPTED PASSWORD 'PATRONI_SUPERUSER_PASSWORD';

      -- Patroni replication user
      -- Replace PATRONI_REPLICATION_USERNAME and PATRONI_REPLICATION_PASSWORD accordingly
      CREATE USER PATRONI_REPLICATION_USERNAME WITH REPLICATION ENCRYPTED PASSWORD 'PATRONI_REPLICATION_PASSWORD';

      -- Patroni rewind user, if you intend to enable use_pg_rewind in your Patroni configuration
      -- Replace PATRONI_REWIND_USERNAME and PATRONI_REWIND_PASSWORD accordingly
      CREATE USER PATRONI_REWIND_USERNAME WITH ENCRYPTED PASSWORD 'PATRONI_REWIND_PASSWORD';
      GRANT EXECUTE ON function pg_catalog.pg_ls_dir(text, boolean, boolean) TO PATRONI_REWIND_USERNAME;
      GRANT EXECUTE ON function pg_catalog.pg_stat_file(text, boolean) TO PATRONI_REWIND_USERNAME;
      GRANT EXECUTE ON function pg_catalog.pg_read_binary_file(text) TO PATRONI_REWIND_USERNAME;
      GRANT EXECUTE ON function pg_catalog.pg_read_binary_file(text, bigint, bigint, boolean) TO PATRONI_REWIND_USERNAME;

#. 在所有 Postgres 节点上执行以下步骤。先在一个节点上执行完所有步骤，再进行下一个节点。先从 primary 节点开始，然后依次处理每个 standby 节点：

   #. 如果你通过 systemd 运行 Postgres，请禁用 Postgres 的 systemd unit。之所以这样做，是因为 Patroni 负责管理 Postgres 守护进程的启动和停止。

   #. 为 Patroni 创建 YAML 配置文件。你可以使用 :ref:`Patroni configuration generation and validation tooling <validate_generate_config>` 来完成这一操作。

      * **注意（仅针对 primary 节点）：** 如果你有用于集群成员之间复制的 replication slots，建议启用 ``use_slots``\，并通过 ``slots`` 配置项将现有 replication slots 配置为永久 slots。请注意，当 ``use_slots`` 启用时，Patroni 会自动为成员之间的复制创建 replication slots，并删除它无法识别的 replication slots。在此使用永久 slots 的想法是，让现有 slots 在向 Patroni 迁移期间得以保留。详见 :ref:`Dynamic Configuration Settings <dynamic_configuration>`。

   #. 使用 ``patroni`` systemd 服务 unit 启动 Patroni。它会自动检测到 Postgres 已在运行，并开始监控该实例。

#. 将 Postgres 的"启动流程"移交给 Patroni。为此，你需要通过 :ref:`patronictl restart cluster-name member-name <patronictl_restart_parameters>` 命令重启集群成员。为了将停机时间降至最低，你也许希望将此步骤拆分为：

   #. 立即重启 standby 节点。
   #. 在维护窗口内对 primary 节点进行计划内重启。

#. 如果你在第 ``1.2.`` 步配置了永久 slots，那么一旦 Patroni 创建的 slots 的 ``restart_lsn`` 能够追赶上对应成员的原始 slots 的 ``restart_lsn``\，你就应该通过 :ref:`patronictl edit-config cluster-name <patronictl_edit_config_parameters>` 命令将它们从 ``slots`` 配置中移除。通过从 ``slots`` 配置中移除这些 slots，一旦不再需要它们，Patroni 就可以删除集群中的原始 slots。下面是一个检查多个 slots 的 ``restart_lsn`` 的示例查询，以便你进行比较：

   .. code-block:: sql

      -- Assume original_slot_for_member_x is the name of the slot in your original
      -- cluster for replicating changes to member X, and slot_for_member_x is the
      -- slot created by Patroni for that purpose. You need restart_lsn of
      -- slot_for_member_x to be >= restart_lsn of original_slot_for_member_x
      SELECT slot_name,
             restart_lsn
      FROM pg_replication_slots
      WHERE slot_name IN (
          'original_slot_for_member_x',
          'slot_for_member_x'
      )

.. _major_upgrade:

PostgreSQL 大版本升级
=====================

目前执行大版本升级的唯一方法是：

#. 停止 Patroni
#. 升级 PostgreSQL 二进制文件，并在 primary 节点上执行 `pg_upgrade <https://www.postgresql.org/docs/current/pgupgrade.html>`_
#. 更新 patroni.yml
#. 从 DCS 中删除 initialize key，或清除 DCS 中完整的集群状态。第二种方式可以通过运行 :ref:`patronictl remove cluster-name <patronictl_remove_parameters>` 实现。这一步是必要的，因为 pg_upgrade 会运行 initdb，而 initdb 实际上会创建一个带有新 PostgreSQL system identifier 的数据库。
#. 如果你在上一步清除了集群状态，你也许希望将 patroni.dynamic.json 从旧数据目录复制到新数据目录。这将帮助你保留之前设置的一些 PostgreSQL 参数。
#. 在 primary 节点上启动 Patroni。
#. 在 standby 节点上升级 PostgreSQL 二进制文件、更新 patroni.yml 并清除 data_dir。
#. 在 standby 节点上启动 Patroni，并等待复制完成。

PostgreSQL 不支持在 standby 节点上运行 pg_upgrade。如果你清楚自己在做什么，可以尝试使用 https://www.postgresql.org/docs/current/pgupgrade.html 中描述的 rsync 流程，而不是清除 standby 节点上的 data_dir。然而，最安全的方式是让 Patroni 为你复制数据。

常见问题
--------

- 在 Patroni 启动期间，Patroni 提示无法绑定到 PostgreSQL 端口。

  你需要核对 ``postgresql.conf`` 中的 ``listen_addresses`` 和 ``port``\，以及 ``patroni.yml`` 中的 ``postgresql.listen``\。不要忘记 ``pg_hba.conf`` 应该允许此类访问。

- 在请求 Patroni 重启节点后，PostgreSQL 显示错误消息 ``could not open configuration file "/etc/postgresql/10/main/pg_hba.conf": No such file or directory``

  根据你管理 PostgreSQL 配置的方式，这可能意味着多种情况。如果你指定了 `postgresql.config_dir`，Patroni 只会在 bootstrap 一个新集群时，根据 :ref:`bootstrap <bootstrap_settings>` 部分中的设置生成 ``pg_hba.conf``\。在此场景中，``PGDATA`` 并非为空，因此没有发生 bootstrap。该文件必须预先存在。
