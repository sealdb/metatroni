.. _contributing_guidelines:

贡献指南
=======================

.. _chatting:

交流讨论
--------

如果您有疑问、在寻找交互式的故障排除帮助，或者想与其他 Patroni 用户交流，请加入 `PostgreSQL Slack <https://pgtreats.info/slack-invite>`__ 的 `#patroni <https://postgresteam.slack.com/archives/C9XPYG92A>`__ 频道。

.. _reporting_bugs:

报告 Bug
--------------

在报告 Bug 之前，请务必使用 **最新的 Patroni 版本复现该问题**！
同时请再次检查该问题是否已存在于我们的 `问题追踪器 <https://github.com/patroni/patroni/issues>`__ 中。

运行测试
-------------

运行 behave 测试的要求：

#. 需要安装 PostgreSQL 软件包，包括 `contrib <https://www.postgresql.org/docs/current/contrib.html>`__ 模块。
#. PostgreSQL 二进制文件必须位于您的 `PATH` 中。您可能需要将它们添加到路径中，例如使用 `PATH=/usr/lib/postgresql/11/bin:$PATH python -m behave`。
#. 如果您想使用外部 DCS（例如 Etcd、Consul 和 Zookeeper）进行测试，则需要安装相应的软件包，并让各自的服务在 localhost 的默认端口上运行，且接受未加密/未受保护的连接。对于 Etcd 或 Consul，如果 `PATH` 中有可用的二进制文件，behave 测试套件可以自行启动它们。

安装依赖：

.. code-block:: bash

    # You may want to use Virtualenv or specify pip3.
    pip install -r requirements.txt
    pip install -r requirements.dev.txt

安装完所有依赖后，您可以运行各种测试套件：

.. code-block:: bash

    # You may want to use Virtualenv or specify python3.

    # Run flake8 to check syntax and formatting:
    python setup.py flake8

    # Run the pytest suite in tests/:
    python setup.py test

    # Moreover, you may want to run tests in different scopes for debugging purposes,
    # the -s option include print output during test execution.
    # Tests in pytest typically follow the pattern: FILEPATH::CLASSNAME::TESTNAME.
    pytest -s tests/test_api.py
    pytest -s tests/test_api.py::TestRestApiHandler
    pytest -s tests/test_api.py::TestRestApiHandler::test_do_GET

    # Run the behave (https://behave.readthedocs.io/en/latest/) test suite in features/;
    # modify DCS as desired (raft has no dependencies so is the easiest to start with):
    DCS=raft python -m behave

使用 tox 进行测试
-----------------

要运行 tox 测试，您只需要安装一个依赖（Python 之外）

.. code-block:: bash

    pip install tox>=4

如果您希望运行 `behave` 测试，则还需要安装 docker。

`tox.ini` 中的 tox 配置定义了用于运行以下任务的「environments」：

* lint：使用 `flake8` 进行 Python 代码检查
* test：使用 `pytest` 对所有可用的 Python 解释器进行单元测试，
  如果检测到 TTY 则生成 XML 报告或 HTML 报告
* dep：使用 `pipdeptree` 检测包依赖冲突
* type：使用 `pyright` 进行静态类型检查
* black：使用 `black` 进行代码格式化
* docker-build：构建用于 `behave` 环境的 docker 镜像
* docker-cmd：使用上述镜像运行任意命令
* docker-behave-etcd：使用上述镜像为 behave 测试运行 tox
* py*behave：使用可用的 Python 解释器运行 behave（不使用 docker，尽管
  这正是 docker 容器内部所调用的方式）
* docs：使用 `sphinx` 构建文档

运行 tox
^^^^^^^^^^^

要运行默认的环境列表（dep、lint、test 和 docs），只需运行：

.. code-block:: bash

    tox

`test` 环境可以通过标签 `test` 运行：

.. code-block:: bash

   tox -m test

`behave` docker 测试可以通过标签 `behave` 运行：

.. code-block:: bash

   tox -m behave

类似地，docs 具有标签 `docs`。

所有其他环境都可以使用各自的环境名称运行：

.. code-block:: bash

   tox -e lint
   tox -e py39-test-lin

还可以使用 `factors` 选择部分环境列表。例如，如果您想为 python 3.10 运行所有环境：

.. code-block:: bash

    tox -f py310

这等效于运行下面列出的所有环境：

.. code-block:: bash

    $ tox -l -f py310
    py310-test-lin
    py310-test-mac
    py310-test-win
    py310-type-lin
    py310-type-mac
    py310-type-win
    py310-behave-etcd-lin
    py310-behave-etcd-win
    py310-behave-etcd-mac


您可以像下面这样使用 tox（>=v4）列出所有已配置的环境组合：

.. code-block:: bash

    tox l

当 job 完成时，如果 tox 在活动的终端中运行，`test` 和 `docs` 环境将尝试打开
HTML 输出文件。这是为了便于在本地运行这些环境的开发人员。它会在 mac 上
尝试运行 `open`，在 Linux 上尝试运行 `xdg-open`。要使用不同的命令，请将环境变量
`OPEN_CMD` 设置为该命令的名称或路径。如果此步骤失败，不会导致整个运行失败。
如果您想禁用此功能，请将环境变量 `OPEN_CMD` 设置为 `:` 空操作命令。

.. code-block:: bash

   OPEN_CMD=: tox -m docs

Behave 测试
^^^^^^^^^^^^

使用 `-m behave` 的 Behave 测试将基于 PG_MAJOR 11 到 16 版本构建 docker 镜像，然后运行所有
behave 测试。这可能需要相当长的时间，因此您可能需要将范围限制为选定的 Postgres 版本，
或特定的功能集或步骤。

要指定 postgres 的版本，请包含您想要的相关镜像构建环境的完整名称，然后是
behave 环境名称。例如，如果您想使用 Postgres 14：

.. code-block:: bash

    tox -e pg14-docker-build,pg14-docker-behave-etcd-lin

另一方面，如果您想测试某个特定功能，可以向 behave 传递位置参数。这将使用所有版本的
Postgres 运行 watchdog behave 功能测试场景。

.. code-block:: bash

    tox -m behave -- features/watchdog.feature

当然，您也可以将两者结合使用。

提交 pull request
---------------------------

#. 派生（fork）仓库，开发并测试您的代码更改。
#. 在用户文档中反映这些更改。
#. 提交一个 pull request，并清楚描述更改的目标。如有必要，请链接现有的 issue。

您会尽快收到关于您的 pull request 的反馈。

祝您 Patroni 开发愉快 ;-)
