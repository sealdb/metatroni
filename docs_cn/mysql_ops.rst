.. _mysql_ops:

=============================
MySQL 运维与 FAQ
=============================

运维指南：安装、部署、day-2 管理、模式切换、HAProxy 以及常见故障。

.. contents::
   :local:
   :depth: 2

前置条件
=============

- Python 3.8+
- 推荐 MySQL 8.0+（``source``/``replica`` 命名需要 8.0.26+）；5.7 也可通过
  版本化模板支持
- ``pip install 'patroni[mysql,etcd3]'`` （或其他 DCS 扩展）
- 每个节点都能访问 DCS（etcd **3.x** → 在 YAML 中使用 ``etcd3:``）
- 可选：与 MySQL major.minor 匹配的 Percona XtraBackup
- 可选：用于 primary/replica 路由的 HAProxy

安装
=======

.. code-block:: shell

    pip install 'patroni[mysql,etcd3]'

    # verify
    python -c 'import pymysql; import patroni; print(patroni.__version__)'
    mysqld --version

在单台主机上生成本地多节点布局（端口错开）：

.. code-block:: shell

    patroni_mysql_init -o deploy/mysql-ha --force \
      --bin-dir /usr/local/mysql/bin \
      --memory-pct 50 \
      --mode semi-sync \
      --nodes 3

每个节点都会生成：``patroni.yml``、``my.cnf``、``data/``，以及集群辅助脚本
``start.sh``、``stop.sh``、``haproxy.cfg``、``README.md``、
``cluster-summary.yaml``。

常用选项
------------

.. list-table::
   :header-rows: 1
   :widths: 28 28 44

   * -  选项
     - 示例
     - 含义
   * -  ``--mode``
     - ``async|semi-sync|mgr``
     - 复制模板
   * -  ``--nodes``
     - ``3``
     - 本地实例数量（MGR 要求 ≥3）
   * -  ``--mysql-version``
     - ``8.0.35``
     - 跳过自动检测 / 固定版本系列
   * -  ``--innodb-buffer-pool-size``
     - ``2G``
     - 每个节点的绝对 buffer pool 大小（覆盖 pct）
   * -  ``--create-replica-methods``
     - ``xtrabackup,mysqldump``
     - 克隆顺序
   * -  ``--etcd``
     - ``127.0.0.1:2379``
     - DCS 端点

部署检查清单
================

1. 启动 DCS（etcd/Consul/ZK）。优先使用奇数节点的 DCS 集群。
2. 确保每个节点的 ``server_id``/ 端口 / ``connect_address`` 唯一。
3. 在第一个节点上启动 Patroni → 若数据目录为空则自动初始化。
4. 确认 REST ``/primary`` 与 ``patronictl list``。
5. 启动其余节点 → 克隆并复制（或加入 MGR）。
6. （可选）使用生成的 ``haproxy.cfg`` 启动 HAProxy。
7. 通过 ``:5000`` 冒烟测试写入、通过 ``:5001`` 冒烟测试读取。

多主机生产环境示意
----------------------------

在每台主机上使用真实的 ``connect_address``、唯一的 ``server_id``、共享的
``scope``/ ``group_replication_group_name`` （MGR）以及相同的复制
密码。**不要** 共享 ``data_dir``。建议先用
``patroni_mysql_init`` 生成一次，再编辑主机名，或者基于
``templates/mysql/`` 维护 Ansible/Helm。

配置参考（简版）
===============================

必需的选择器：

.. code:: YAML

    database:
      type: mysql

最小化的 ``mysql`` 配置段：

.. code:: YAML

    mysql:
      name: mysql-node-1
      scope: mysql-cluster
      listen: 0.0.0.0:3306
      connect_address: 10.0.0.1:3306
      data_dir: /var/lib/mysql
      bin_dir: /usr/local/mysql/bin
      port: 3306
      server_id: 1
      authentication:
        superuser:
          username: root
          password: "s3cret"
        replication:
          username: replicator
          password: "rep-pass"
      parameters:
        server_id: "1"
        gtid_mode: "ON"
        enforce_gtid_consistency: "ON"
        log-bin: "mysql-bin"
        log_slave_updates: "ON"
        mysqlx: "OFF"

有关各版本的命名差异（``source``/``replica`` 与 ``master``/``slave``、binlog 过期策略、redo 容量），请参阅 :ref:`mysql` 与 ``templates/mysql/VERSIONS.md``。

Day-2 运维
================

状态
------

.. code-block:: shell

    patronictl -c /path/to/patroni.yml list
    curl -s http://127.0.0.1:8008/patroni | jq .
    curl -s http://127.0.0.1:8008/cluster | jq .

Switchover / failover
---------------------

.. code-block:: shell

    # planned
    patronictl -c patroni.yml switchover --master mysql0 --candidate mysql1

    # unplanned / force candidate
    patronictl -c patroni.yml failover --master mysql0 --candidate mysql1

重启 / 重载 / 重建 replica
----------------------------------

.. code-block:: shell

    patronictl -c patroni.yml restart mysql1
    patronictl -c patroni.yml reload mysql1
    patronictl -c patroni.yml reinitialize mysql1   # wipe + reclone

暂停自动 failover
------------------

.. code-block:: shell

    patronictl -c patroni.yml pause
    # … maintenance …
    patronictl -c patroni.yml resume

HAProxy
=======

生成的 ``haproxy.cfg``（以及根目录示例 ``haproxy-mysql.cfg``）：

.. list-table::
   :header-rows: 1
   :widths: 18 18 64

   * -  监听项
     - 端口
     - 健康检查
   * -  primary
     - ``*:5000``
     - ``HEAD /primary`` → 200
   * -  replicas
     - ``*:5001``
     - ``HEAD /replica`` → 200
   * -  stats
     - ``*:7000``
     - HAProxy stats 界面

.. code-block:: shell

    haproxy -f deploy/mysql-ha/haproxy.cfg -db
    mysql -h 127.0.0.1 -P 5000 -u root -p
    mysql -h 127.0.0.1 -P 5001 -u root -p -e 'SELECT @@read_only, @@super_read_only'

如需动态成员管理，可修改 ``extras/confd/templates/haproxy.tmpl`` （与 PostgreSQL 使用相同的
``conn_url``/ ``api_url`` 模式）。

复制模式切换
=========================

**不支持在线热切换。** 操作前务必先做快照/备份。

异步 ↔ 半同步
-----------------

1. ``patronictl pause`` （推荐）。
2. 停止 Patroni；对齐 ``my.cnf``/ YAML 中 ``rpl_semi_sync_*`` 与 ``plugin-load-add`` 的顺序
   （或重新生成 ``--mode``）。
3. 重启 mysqld 与 Patroni；``patronictl resume``。
4. 验证 ``SHOW STATUS LIKE 'Rpl_semi_sync_%'``，并确认 primary 仅在满足 quorum 时才可写。

异步 / 半同步 → MGR
-----------------------

1. 排空写入；pause。
2. 在每个节点上执行 ``STOP SLAVE; RESET SLAVE ALL;`` （GR 会拒绝双通道）。
3. 配置 MGR 参数（共享 UUID、seeds、本地端口 = 客户端端口+10）。
4. 复制用户：``mysql_native_password``（recovery 通道上不使用 ``GET_MASTER_PUBLIC_KEY``）。
5. Bootstrap 一个节点；其余节点通过 Patroni ``rejoin_mgr_group``。
6. 确认 ``replication_group_members`` 全部为 ``ONLINE``；resume。

MGR → 异步 / 半同步
-----------------------

1. pause；在所有节点上执行 ``STOP GROUP_REPLICATION``；移除 GR 配置。
2. 选择 GTID 领先/原 primary 的节点作为异步源；其余节点 ``follow``。
3. 如需半同步，可在流式复制建立后启用；resume。

切换模式时，建议在干净停止后清空 ``/service/<scope>/``，以免过期的成员角色干扰选举。

监控钩子
================

- REST ``/metrics``— Prometheus 风格的 gauges（适用处用 binlog 位置替代
  xlog）
- DCS 成员 ``gtid_executed``— MGR 选举输入
- 成员 / ``/patroni`` 上的 ``mgr_gtid_fork``— 脑裂 GTID 告警
- 半同步：关注 ``Rpl_semi_sync_*_clients`` 与 primary 的 ``read_only``

集成测试（开发）
=======================

.. code-block:: shell

    MYSQL_BASE=/path/to/mysql PYTHONPATH=. \
      python3 -u integration-tests/test_mysql_patroni_ha.py

    MYSQL_BASE=/path/to/mysql PYTHONPATH=. \
      python3 -u integration-tests/test_mysql_semi_sync.py

    MYSQL_BASE=/path/to/mysql PYTHONPATH=. \
      python3 -u integration-tests/test_mysql_mgr_patroni_ha.py

FAQ / 故障排查
=====================

``patronictl list`` 为空 / 没有 leader
--------------------------------------

- 检查 DCS 连通性（``etcdctl endpoint health``）。
- 确认所有节点共享相同的 ``scope`` 和 ``namespace``。
- 对于 etcd 3.x，YAML 必须使用 ``etcd3:``，而不是 ``etcd:``。

replica 一直无法进入 ``streaming`` 状态
---------------------------------------

- 检查复制用户/密码及权限。
- 在 MySQL 8 异步模式下，确保 ``GET_MASTER_PUBLIC_KEY`` 路径可用，或改用
  ``mysql_native_password``。
- 检查 ``SHOW SLAVE STATUS``/ ``SHOW REPLICA STATUS`` 中的 ``Last_IO_Error``。
- 重新克隆：``patronictl reinitialize <name>``。

半同步 primary 一直处于 read-only
---------------------------------

当已连接的半同步 replicas 低于 quorum ``(N-1)//2`` 时，这是预期行为。恢复
replicas，或仅在谨慎评估后临时调整 ``cluster_size``。检查
``Rpl_semi_sync_*_clients``。

MGR group 无法形成
-----------------------

- 需要 ≥3 个节点，且 ``group_replication_group_name`` 一致。
- 本地 MGR 端口默认为 ``mysql_port + 10`` （避免端口溢出的方案）。
- ``caching_sha2_password`` + ``GET_MASTER_PUBLIC_KEY`` 在 recovery
  通道上会失败（ER 3139）→ 改用 ``mysql_native_password``。
- 查询 ``performance_schema.replication_group_members`` （而不是
  ``@@group_replication_primary_member``，它不是 sysvar）。

多数派丢失；cluster 已暂停 / ``mgr_gtid_fork``
------------------------------------------------

- ``gtid_executed`` 集合不可比较 → 拒绝自动 bootstrap。
- 修复数据（重建分歧节点）后执行 ``patronictl resume``。
- 仅在可接受风险的情况下禁用自动暂停：
  ``mysql.parameters.mgr_pause_on_gtid_fork: false``。

failover 后旧 primary 无法重新加入
------------------------------------------

- MySQL demote 必须在优雅/立即路径上释放 leader 锁。
- 确认已向新 primary 执行 ``follow()`` 并启用 GTID 自动定位。
- 检查日志中的 demote/follow 错误；不期望存在 rewind 步骤。

xtrabackup 克隆失败
----------------------

- XtraBackup 的 major.minor 必须与 MySQL 一致。
- 确保 donor 上授予了 ``BACKUP_ADMIN`` （或等效）权限。
- 失败时 Patroni 应清理不完整的数据目录；重试或回退到
  ``create_replica_methods`` 中的 ``mysqldump``。

端口冲突 / X Plugin
-------------------------

- 生成的 ``my.cnf`` 中默认 ``mysqlx=OFF``。
- 单台主机上的多实例：错开 MySQL 与 REST 端口
  （``patroni_mysql_init`` 会自动处理）。

switchover 无限循环
------------------------

- 通常是被降级的 primary 没有释放 DCS 锁。升级到包含优雅 MySQL demote 锁释放的
  版本，或手动删除
  leader key 并向预期的 primary 执行 ``follow``。

已知限制（运维视角）
============================

- **不支持** standby cluster（跨站点 WAL 归档模式）
- 没有与 ``pg_rewind`` 等价的功能
- 模式变更属于重建/切换，而非在线热切换
- 仍处于积极开发阶段 — 上生产前请结合你的工作负载与
  集成测试套件进行验证
