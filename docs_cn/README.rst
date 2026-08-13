.. _readme:

====
简介
====

Patroni 是一个使用 Python 构建的 PostgreSQL 高可用（HA）解决方案模板。Patroni 起源于 Compose 公司的项目 `Governor <https://github.com/compose/governor>`__ 的一个 fork，并包含大量新特性。

**Metatroni** 是在 Patroni 之上的自研增强：

1. **全量包含** Patroni 原有全部功能。
2. **额外支持 MySQL 高可用**\（``database.type: mysql``\）。
3. 支持 **ZooKeeper**\、**etcd** 或 **Consul**\（以及 Patroni 已支持的其他 DCS）。

MySQL 细节见 :ref:`mysql`、:ref:`mysql_ops`。上游 Patroni 背景：

* `PostgreSQL HA with Kubernetes and Patroni <https://www.youtube.com/watch?v=iruaCgeG7qs>`__，Josh Berkus 在 KubeCon 2016 上的演讲（视频）
* `2016 年 2 月 Zalando Tech 博客文章 <https://engineering.zalando.com/posts/2016/02/zalandos-patroni-a-template-for-high-availability-postgresql.html>`__


开发状态
--------

Patroni 正处于积极开发阶段，并接受贡献。更多细节请参阅下面的 :ref:`Contributing <contributing>` 部分。

新版本信息我们会在 :ref:`here <releases>` 发布。


技术要求/安装
-------------

在不同平台上安装和升级 Patroni 的指南，请参阅 :ref:`here <installation>`。

.. _running_configuring:

规划 PostgreSQL 节点数量
------------------------

Patroni/PostgreSQL 节点与 DCS 节点是解耦的（除非 Patroni 自行实现 RAFT），因此对节点的最小数量没有要求。运行一个由一个 primary 和一个 standby 组成的集群完全没问题。你可以在以后添加更多 standby 节点。

**双节点集群** （primary + standby）很常见，可提供具有高可用性的自动 failover。请注意，在 failover 期间，在故障节点重新加入之前，你将暂时没有冗余。

**DCS 要求**\：你的 DCS（etcd、ZooKeeper、Consul）必须以 **3 或 5 个节点** 运行，以实现正确的共识（consensus）和容错。单个 DCS 集群可以存储数百或数千个使用不同 namespace/scope 组合的 Patroni 集群的信息。

运行和配置
----------

以下部分假设你已经从 https://github.com/patroni/patroni 克隆了 Patroni 仓库。也就是说，你将需要示例配置文件 `postgres0.yml` 和 `postgres1.yml`。如果你通过 pip 安装了 Patroni，你可以从 git 仓库中获取这些文件，并将下面的 `./patroni.py` 替换为 `patroni` 命令。

要开始使用，请在各个不同的终端中执行以下操作：
::::::::::::::::::::::::::::::::::::::::::::::

    > etcd --data-dir=data/etcd --enable-v2=true
    > ./patroni.py postgres0.yml
    > ./patroni.py postgres1.yml

然后你会看到一个高可用集群启动。测试 YAML 文件中的不同设置，观察集群行为的变化。杀掉部分组件，看看系统会如何表现。

添加更多 ``postgres*.yml`` 文件以创建更大的集群。

Patroni 提供了一个 `HAProxy <http://www.haproxy.org/>`__ 配置，它能为你的应用程序提供连接到集群 leader 的单一端点。要进行配置，请运行：

::

    > haproxy -f haproxy.cfg

::

    > psql --host 127.0.0.1 --port 5000 postgres


YAML 配置
---------

关于 etcd、consul 和 ZooKeeper 设置的全面信息，请参阅 :ref:`here <yaml_configuration>`。示例配置请参见 `postgres0.yml <https://github.com/patroni/patroni/blob/master/postgres0.yml>`__。


环境配置
--------

关于通过环境变量配置（覆盖）设置的全面信息，请参阅 :ref:`here <environment>`。


复制选项
--------

Patroni 使用 Postgres 的流式复制，默认情况下是异步的。Patroni 的异步复制配置支持 ``maximum_lag_on_failover`` 设置。此设置确保如果 follower 落后 leader 的字节数超过某个值，则不会发生 failover。此设置应根据业务需求增大或减小。也可以使用同步复制来获得更好的持久性保证。详见 :ref:`replication modes documentation <replication_modes>`。


应用程序不应使用超级用户
------------------------

从应用程序连接时，始终使用非超级用户。Patroni 需要访问数据库才能正常工作。如果在应用程序中使用超级用户，你可能会用完整个连接池，包括通过 ``superuser_reserved_connections`` 设置为超级用户保留的连接。如果连接池已满导致 Patroni 无法访问 Primary，其行为将不尽如人意。


测试你的 HA 解决方案
--------------------
测试 HA 解决方案是一个耗时的过程，涉及许多变量。对于跨平台应用程序来说尤其如此。你需要一位训练有素的系统管理员或顾问来完成这项工作。这不是我们能在文档中深入覆盖的内容。

话虽如此，下面是你应该确保测试的一些基础设施组件：

* 网络（系统前面的网络以及 NIC [物理或虚拟] 本身）
* 磁盘 IO
* 文件限制（Linux 中的 nofile）
* RAM。即使你关闭了 oomkiller，RAM 的不可用也可能导致问题。
* CPU
* 虚拟化争用（超量分配 hypervisor）
* 任何 cgroup 限制（很可能与上述内容相关）
* 对任何 postgres 进程（postmaster 除外！）执行 ``kill -9``\。这是对段错误（segfault）的良好模拟。

你不应该做的一件事是对 postmaster 进程执行 ``kill -9``\。因为这样做无法模拟任何真实场景。如果你担心自己的基础设施不安全、攻击者可以运行 ``kill -9``\，那么再多的 HA 进程也无济于事。攻击者只会再次杀掉进程，或以其他方式制造混乱。
