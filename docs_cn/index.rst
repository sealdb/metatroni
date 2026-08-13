.. Patroni / Metatroni documentation master file, created by sphinx-quickstart.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Metatroni：使用 ZooKeeper、etcd 或 Consul 实现 PostgreSQL HA 的模板（基于 Patroni）

===============================================================

.. image:: _static/patroni-logo.png
   :height: 128px
   :width: 128px

**Metatroni** 是在 `Patroni <https://github.com/patroni/patroni>`__ 之上的自研增强：

1. **全量包含** Patroni 原有全部功能。
2. **额外支持 MySQL 高可用**\（``database.type: mysql``\）。
3. 支持 **ZooKeeper**\、**etcd** 或 **Consul**\（以及 Patroni 已支持的其他 DCS）。

共享的 Patroni 行为见本手册各章；MySQL 专章从 :ref:`mysql` 开始。

.. warning::

  在 **内存受限且使用 Python 3.11+** 的系统上运行 Patroni/Metatroni

----

如果你在具有严格内存限制的系统上运行 Patroni（例如设置 ``vm.overcommit_memory=2``\，这是 PostgreSQL 的推荐设置），并使用 Python 3.11 或更高版本，你可能会观察到异常行为：

- Patroni 看起来一切正常
- PostgreSQL 继续运行
- Patroni **REST API 无响应**
- 操作系统显示 Patroni 正在监听 REST API 端口
- Patroni 日志看起来正常；但可能会出现以下一次性消息：``Exception ignored in thread started by: <object repr() failed>``\、``MemoryError``
- 内核日志中可能包含类似 ``not enough memory for the allocation`` 的消息

该行为是由 `bug in Python 3.11+ <https://github.com/python/cpython/issues/140746>`__ 引起的。在严格的内存条件下，当空闲内存不足时，启动新线程可能会无限期挂起。

推荐解决方案
============

较新的 Patroni 版本（4.1.1+、4.0.8+）通过在启动早期、系统尚未面临内存压力时提前启动所有必需的线程，来减轻此问题的影响。

补充建议（Linux、glibc）
========================

当使用 ``vm.overcommit_memory=2`` （PostgreSQL 的推荐设置）运行时，我们还建议在启动 Patroni 时配置以下环境变量：

- ``MALLOC_ARENA_MAX=1``- 减少 glibc 为多线程应用程序分配的虚拟内存量
- ``PG_MALLOC_ARENA_MAX=``- 重置由 Patroni 启动的 PostgreSQL 进程的 ``MALLOC_ARENA_MAX`` 值。

此外，你还可以调整以下 Patroni 配置参数：

- ``thread_stack_size``- 用于 Patroni 启动的线程的栈大小。降低此值可以减少 Patroni 进程的内存占用。Patroni 设置的默认值为 ``512kB``\。如果 Patroni 遇到与栈相关的崩溃，请增大 ``thread_stack_size``\；否则默认值就足够了。
- ``thread_pool_size``- Patroni 用于异步任务，以及在 leader 竞争或 failsafe 检查期间与其他成员进行 REST API 通信的线程池大小。默认值为 ``5``\，对于三节点集群来说已经足够。
- ``restapi.thread_pool_size``- 用于处理 REST API 请求的线程池大小。默认值为 ``5``\，最多允许五个并行的 REST API 请求。请注意，涉及 SQL 查询的请求实际上是串行执行的，因为使用的是单个数据库连接，所以增大此值通常没有益处。

----

简介
====

Patroni 是一个使用 Python 构建的 PostgreSQL 高可用（HA）解决方案模板。为了最大限度地提高可用性，Patroni 支持多种分布式配置存储，如 `ZooKeeper <https://zookeeper.apache.org/>`__、`etcd <https://github.com/coreos/etcd>`__、`Consul <https://github.com/hashicorp/consul>`__ 或 `Kubernetes <https://kubernetes.io>`__。希望在数据中心——或任何其他地方——快速部署 HA PostgreSQL 的数据库工程师、DBA、DevOps 工程师和 SRE 应该会发现它很有用。

我们把 Patroni 称为"模板"，因为它远非一个放之四海而皆准或即插即用的复制系统。它有自己的注意事项。请明智地使用它。使用 PostgreSQL 实现高可用的方式有很多；相关列表请参阅 `PostgreSQL Documentation <https://wiki.postgresql.org/wiki/Replication,_Clustering,_and_Connection_Pooling>`__。

目前支持的 PostgreSQL 版本：9.3 到 18。

**给 Citus 用户的说明**\：从 3.0 版本开始，Patroni 与 `Citus <https://github.com/citusdata/citus>`__ Postgres 数据库扩展很好地集成。关于如何将 Patroni 高可用与 Citus 分布式集群结合使用，请参阅 Patroni 文档中的 :ref:`Citus support page <citus>`。

**给 Kubernetes 用户的说明**\：Patroni 可以原生运行在 Kubernetes 之上。请参阅 Patroni 文档中的 :ref:`Kubernetes <kubernetes>` 章节。

**给 MySQL 用户的说明**\：这个 fork 可以通过 ``database.type: mysql`` 管理 MySQL HA（异步 GTID、半同步和 MGR）。请参阅 :ref:`MySQL <mysql>` 章节。该支持仍处于积极开发阶段。


.. toctree::
   :maxdepth: 2
   :caption: Contents:

   README
   installation
   patroni_configuration
   rest_api
   patronictl
   replica_bootstrap
   replication_modes
   standby_cluster
   watchdog
   pause
   dcs_failsafe_mode
   kubernetes
   citus
   mysql
   existing_data
   tools_integration
   security
   ha_multi_dc
   faq
   releases
   CONTRIBUTING

索引和表格
==========

.. ifconfig:: builder == 'html'

  * :ref:`genindex`
  * :ref:`modindex`
  * :ref:`search`

.. ifconfig:: builder != 'html'

  * :ref:`genindex`
  * :ref:`search`
