.. _installation:

安装
====

Mac OS 的安装前要求
-------------------

要在 Mac 上安装所需依赖，请运行以下命令：

.. code-block:: shell

    brew install postgresql etcd haproxy libyaml python

.. _psycopg2_install_options:

Psycopg
-------

从 `psycopg2-2.8`_ 开始，psycopg2 的二进制版本将不再默认安装。从源代码安装它需要
C 编译器和 postgres+python 开发包。由于在 Python 世界中无法将依赖指定为
``psycopg2 OR psycopg2-binary``\，您必须自行决定如何安装它。

有几个选项可用：

1. 使用您的发行版的包管理器

.. code-block:: shell

    sudo apt-get install python3-psycopg2  # install psycopg2 module on Debian/Ubuntu
    sudo yum install python3-psycopg2      # install psycopg2 on RedHat/Fedora/CentOS

2. 使用 pip 安装 Patroni 时，在 :ref:`list of dependencies <extras>` 中指定 `psycopg`、`psycopg2` 或 `psycopg2-binary` 之一。


.. _extras:

使用 pip 进行常规安装
---------------------

Patroni 可以使用 pip 安装：

.. code-block:: shell

    pip install patroni[dependencies]

其中 ``dependencies`` 可以为空，也可以包含以下一项或多项：

etcd or etcd3
    使用 Etcd 作为分布式配置存储（DCS）所需的 `python-etcd` 模块
consul
    使用 Consul 作为 DCS 所需的 `py-consul` 模块
zookeeper
    使用 Zookeeper 作为 DCS 所需的 `kazoo` 模块
exhibitor
    使用 Exhibitor 作为 DCS 所需的 `kazoo` 模块（与 Zookeeper 的依赖相同）
kubernetes
    在 Patroni 中使用 Kubernetes 作为 DCS 所需的 `kubernetes` 模块
raft
    使用 python Raft 实现作为 DCS 所需的 `pysyncobj` 模块
aws
    使用 AWS 回调所需的 `boto3`
jsonlogger
    以 json 格式启用 :ref:`logging <log_settings>` 所需的 `python-json-logger` 模块
systemd
    使用 sd_notify 集成所需的 `systemd-python`
mysql
    使用 MySQL 后端（``database.type: mysql``\）所需的 `pymysql`
all
    以上所有项（psycopg 系列除外）
psycopg3
    `psycopg[binary]>=3.0.0` 模块
psycopg2
    `psycopg2>=2.5.4` 模块
psycopg2-binary
    `psycopg2-binary` 模块

例如，要同时安装 Patroni、psycopg3、Etcd 作为 DCS 所需的依赖以及 AWS 回调，命令为：

.. code-block:: shell

    pip install patroni[psycopg3,etcd3,aws]

要安装带 etcd3 的 MySQL 支持：

.. code-block:: shell

    pip install 'patroni[mysql,etcd3]'

请注意，在 replica 创建或自定义 bootstrap 脚本（即 WAL-E）中调用的外部工具应独立于
Patroni 安装。

.. _package_installation:

在 Linux 上通过软件包安装
-------------------------

您的操作系统可能提供由 Postgres 社区构建的 Patroni 软件包，适用于：

* RHEL、RockyLinux、AlmaLinux；
* Debian 和 Ubuntu；
* SUSE Enterprise Linux。

您还可以找到 Patroni 直接依赖的软件包，例如官方操作系统仓库中可能没有的 python 模块。

更多信息请参阅 `PGDG repository`_ 的文档。

如果您使用的是 RedHat Enterprise Linux 衍生操作系统，可能还需要 EPEL 中的软件包，请参阅
`EPEL repository`_ 的文档。

为您的操作系统安装好 PGDG 仓库后，即可安装 patroni。

.. note::

    Patroni 软件包并非由 Patroni 开发者维护，而是由 Postgres 社区维护。如果您
    需要支持，请首先尝试在 `Postgres slack`_ 上联系。

在 Debian 衍生发行版上安装
^^^^^^^^^^^^^^^^^^^^^^^^^^

安装好 PGDG 仓库后，参见 :ref:`above <package_installation>`，通过 apt 安装 Patroni，运行：

.. code-block:: shell

    apt-get install patroni

在 RedHat 衍生发行版上安装
^^^^^^^^^^^^^^^^^^^^^^^^^^

安装好 PGDG 仓库后，参见 :ref:`above <package_installation>`，在 RHEL 9（及衍生发行版）上通过 dnf 安装带 etcd DCS 的 patroni，运行：

.. code-block:: shell

    dnf install patroni patroni-etcd

如果您的 RedHat 衍生发行版不提供软件包，可以从 PGDG 安装 etcd。在将托管 DCS 的节点上运行：

.. code-block:: shell

    dnf install 'dnf-command(config-manager)'
    dnf config-manager --enable pgdg-rhel9-extras
    dnf install etcd

如果需要，您可以将仓库中的 RHEL 版本替换为 `8`，以启用 `pgdg-rhel8-extras`。在 RockyLinux、AlmaLinux、Oracle Linux 等发行版上，仓库名称仍然是 `pgdg-rhelN-extras`。

在 SUSE Enterprise Linux 上安装
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

某些依赖可能需要您启用 SUSE PackageHub 仓库。请参阅 `SUSE PackageHub`_ 的文档。

对于安装了 PGDG 仓库的 SLES 15，参见 :ref:`above <package_installation>`，您可以使用以下命令安装 patroni：

.. code-block:: shell

    zypper install patroni patroni-etcd

启用 SUSE PackageHub 仓库后，您还可以安装 etcd：

.. code-block:: shell

    SUSEConnect -p PackageHub/15.5/x86_64
    zypper install etcd

升级
----

升级 patroni 是一个非常简单的过程，只需更新软件安装并在集群中的每个节点上重启 Patroni 守护进程。

不过，重启 Patroni 守护进程会导致 Postgres 数据库重启。在某些情况下，这可能
导致集群中的 primary 节点发生 failover，因此建议将集群置于维护模式，
直到 Patroni 守护进程重启完成。

要将集群置于维护模式，请在其中一个 patroni 节点上运行以下命令：

.. code-block:: shell

    patronictl pause --wait

然后在集群中的每个节点上，执行操作系统所需的软件包升级：

.. code-block:: shell

    apt-get update && apt-get install patroni patroni-etcd

在每个节点上重启 patroni 守护进程：

.. code-block:: shell

    systemctl restart patroni

最后，恢复使用 patroni 对 Postgres 的监控，将其从维护模式中取出：

.. code-block:: shell

    patronictl resume --wait

现在，集群将以新版本的 Patroni 完全正常运行。

.. _psycopg2-2.8: http://initd.org/psycopg/articles/2019/04/04/psycopg-28-released/
.. _PGDG repository: https://www.postgresql.org/download/linux/
.. _EPEL repository: https://docs.fedoraproject.org/en-US/epel/
.. _SUSE PackageHub: https://packagehub.suse.com/how-to-use/
.. _Postgres slack: http://pgtreats.info/slack-invite
