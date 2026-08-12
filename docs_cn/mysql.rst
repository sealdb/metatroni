.. _mysql:

==============================
MySQL 高可用支持
==============================

.. warning::

   MySQL 支持目前正处于积极开发阶段，**尚不建议用于生产环境**。

本章介绍 Patroni 的 MySQL 后端：它如何融入 HA 循环、replication 模式如何工作，以及如何部署和运维一个集群。

.. toctree::
   :maxdepth: 2

   mysql_architecture
   mysql_mechanisms
   mysql_ops

你能获得什么
============

使用 ``database.type: mysql`` 时，每个节点运行 Patroni + ``mysqld``。Patroni：

- 在 DCS（etcd、Consul、ZooKeeper……）中持有/竞争 **leader lease**
- 监控 MySQL 健康状态，并将状态（包括 GTID）发布到 DCS
- 管理 **异步 GTID**、**semi-sync** 或 **Group Replication (MGR)**
- 通过 ``mysqldump`` 或 ``xtrabackup`` 克隆 replica
- 提供常用的 REST API 和 ``patronictl`` 接口

快速开始
===========

.. code-block:: shell

    pip install 'patroni[mysql,etcd3]'

    patroni_mysql_init -o deploy/mysql-ha --force \
      --bin-dir /usr/local/mysql/bin --mode semi-sync --nodes 3

    # start etcd, then:
    ./deploy/mysql-ha/start.sh
    patronictl -c deploy/mysql-ha/mysql0/patroni.yml list
    haproxy -f deploy/mysql-ha/haproxy.cfg -db   # optional :5000 / :5001

继续阅读
=========

.. list-table::
   :header-rows: 1
   :widths: 28 32 40

   * -  页面
     - 重点
     - 如果你需要……请从这里开始
   * -  :ref:`mysql_architecture`
     - 组件、DCS 模型、与 PostgreSQL 的对比
     - 系统设计 / 代码地图
   * -  :ref:`mysql_mechanisms`
     - Failover、降级、semi-sync、MGR、clone
     - 它是如何工作的？
   * -  :ref:`mysql_ops`
     - 安装、day-2、FAQ
     - 部署 / 故障排查
