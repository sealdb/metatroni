.. _citus:

Citus 支持
==========

Patroni 让部署 `Multi-Node Citus`__ 集群变得极其简单。

__ https://docs.citusdata.com/en/stable/installation/multi_node.html

TL;DR
-----

你只需要遵循几条简单的规则：

1. 所有节点上都必须安装 PostgreSQL 的 `Citus <https://github.com/citusdata/citus>`__ 数据库扩展。支持的最低 Citus
   版本是 10.0，但为了充分享受透明的 switchover 和
   worker 重启带来的好处，我们建议至少使用 Citus 11.2。
2. 所有 Citus 节点的集群名称（``scope``\）必须相同！
3. coordinator 和所有 worker
   节点上的超级用户凭据必须相同，并且 ``pg_hba.conf`` 应允许所有节点之间的超级用户访问。
4. 应允许从 worker
   节点访问 coordinator 的 :ref:`REST API <restapi_settings>`。例如，凭据必须相同，并且如果配置了
   客户端证书，coordinator 必须接受来自 worker 节点的客户端证书。
5. 在 ``patroni.yaml`` 中添加以下配置段：

.. code:: YAML

        citus:
          group: X  # 0 for coordinator and 1, 2, 3, etc for workers
          database: citus  # must be the same on all nodes


之后，你只需启动 Patroni，其余工作都由它来完成：

0. 如果 ``bootstrap.dcs.synchronous_mode`` 没有被显式设置为其他值，Patroni 会将其设为 :ref:`quorum <quorum_mode>`。
1. ``citus`` 扩展会被自动添加到 ``shared_preload_libraries``\。
2. 如果全局
   :ref:`dynamic configuration <dynamic_configuration>` 中没有显式设置 ``max_prepared_transactions``\，Patroni 会
   自动将其设置为 ``2*max_connections``\。
3. ``citus.local_hostname`` GUC 的值会从 ``localhost`` 调整为
   Patroni 用于连接本地 PostgreSQL
   实例的值。该值有时应与 ``localhost`` 不同，
   因为 PostgreSQL 可能并没有监听 ``localhost``\。
4. 会自动创建 ``citus.database`` 指定的数据库，随后执行 ``CREATE EXTENSION citus``\。
5. 当前超级用户的 :ref:`credentials <postgresql_settings>` 会被添加到 ``pg_dist_authinfo``
   表中，以允许跨节点通信。如果之后你决定修改超级用户的 username/password/sslcert/sslkey，别忘了更新它们！
6. coordinator 的 primary 节点会自动发现 worker 的 primary
   节点，并使用
   ``citus_add_node()`` 函数将它们添加到 ``pg_dist_node`` 表中。
7. 当 coordinator 或 worker 集群发生 failover/switchover
   时，Patroni 也会维护 ``pg_dist_node`` 表。

patronictl
----------

coordinator 和 worker 集群本质上是不同的 PostgreSQL/Patroni
集群，只是通过 PostgreSQL 的
`Citus <https://github.com/citusdata/citus>`__ 数据库扩展在逻辑上组合在一起。因此在大多数情况下，无法将它们作为一个
整体来管理。

与通常情况相比，当
``patroni.yaml`` 包含 ``citus`` 配置段时，:ref:`patronictl` 的行为有两个主要差异：

1. 默认情况下，``list`` 和 ``topology`` 会输出 Citus
   编队（coordinator 和 workers）的所有成员。新增的 ``Group`` 列用于指示
   它们属于哪个 Citus group。
2. 所有 ``patronictl`` 命令都新增了一个名为
   ``--group`` 的选项。对于某些命令，group 的默认值可能会
   取自 ``patroni.yaml``\。例如，:ref:`patronictl_pause` 默认会对
   ``citus`` 配置段中设置的 ``group`` 启用维护模式；但例如 :ref:`patronictl_switchover` 或
   :ref:`patronictl_remove` 则必须显式指定 group。

Citus 集群的 :ref:`patronictl_list` 输出示例::

    postgres@coord1:~$ patronictl list demo
    + Citus cluster: demo ----------+----------------+---------+----+-------------+-----+------------+-----+
    | Group | Member  | Host        | Role           | State   | TL | Receive LSN | Lag | Replay LSN | Lag |
    +-------+---------+-------------+----------------+---------+----+-------------+-----+------------+-----+
    |     0 | coord1  | 172.27.0.10 | Replica        | running |  1 |   0/41C0368 |   0 |  0/41C0368 |   0 |
    |     0 | coord2  | 172.27.0.6  | Quorum Standby | running |  1 |   0/41C0368 |   0 |  0/41C0368 |   0 |
    |     0 | coord3  | 172.27.0.4  | Leader         | running |  1 |             |     |            |     |
    |     1 | work1-1 | 172.27.0.8  | Quorum Standby | running |  1 |   0/31D3198 |   0 |  0/31D3198 |   0 |
    |     1 | work1-2 | 172.27.0.2  | Leader         | running |  1 |             |     |            |     |
    |     2 | work2-1 | 172.27.0.5  | Quorum Standby | running |  1 |   0/31CDFC0 |   0 |  0/31CDFC0 |   0 |
    |     2 | work2-2 | 172.27.0.7  | Leader         | running |  1 |             |     |            |     |
    +-------+---------+-------------+----------------+---------+----+-------------+-----+------------+-----+

如果加上 ``--group`` 选项，输出将变为::

    postgres@coord1:~$ patronictl list demo --group 0
    + Citus cluster: demo (group: 0, 7179854923829112860) -+-------------+-----+------------+-----+
    | Member | Host        | Role           | State   | TL | Receive LSN | Lag | Replay LSN | Lag |
    +--------+-------------+----------------+---------+----+-------------+-----+------------+-----+
    | coord1 | 172.27.0.10 | Replica        | running |  1 |   0/41C0368 |   0 |  0/41C0368 |   0 |
    | coord2 | 172.27.0.6  | Quorum Standby | running |  1 |   0/41C0368 |   0 |  0/41C0368 |   0 |
    | coord3 | 172.27.0.4  | Leader         | running |  1 |             |     |            |     |
    +--------+-------------+----------------+---------+----+-------------+-----+------------+-----+

    postgres@coord1:~$ patronictl list demo --group 1
    + Citus cluster: demo (group: 1, 7179854923881963547) -+-------------+-----+------------+-----+
    | Member  | Host       | Role           | State   | TL | Receive LSN | Lag | Replay LSN | Lag |
    +---------+------------+----------------+---------+----+-------------+-----+------------+-----+
    | work1-1 | 172.27.0.8 | Quorum Standby | running |  1 |   0/31D3198 |   0 |  0/31D3198 |   0 |
    | work1-2 | 172.27.0.2 | Leader         | running |  1 |             |     |            |     |
    +---------+------------+----------------+---------+----+-------------+-----+------------+-----+

Citus worker 的 switchover
--------------------------

当为 Citus worker 节点编排 switchover 时，Citus 提供了让 switchover 对应用程序几乎透明的能力。
因为应用程序连接的是 coordinator，而 coordinator 再连接到
worker 节点，因此借助 Citus，可以在 coordinator 上 `pause` 针对托管在某个 worker 节点上的分片的 SQL 流量。随后
switchover 在流量仍停留在 coordinator 上时发生，一旦
新的 worker primary 节点准备好接受读写查询，流量即恢复。

worker 集群上 :ref:`patronictl_switchover` 的示例::

    postgres@coord1:~$ patronictl switchover demo
    + Citus cluster: demo ----------+----------------+---------+----+-------------+-----+------------+-----+
    | Group | Member  | Host        | Role           | State   | TL | Receive LSN | Lag | Replay LSN | Lag |
    +-------+---------+-------------+----------------+---------+----+-------------+-----+------------+-----+
    |     0 | coord1  | 172.27.0.10 | Replica        | running |  1 |   0/41C0368 |   0 |  0/41C0368 |   0 |
    |     0 | coord2  | 172.27.0.6  | Quorum Standby | running |  1 |   0/41C0368 |   0 |  0/41C0368 |   0 |
    |     0 | coord3  | 172.27.0.4  | Leader         | running |  1 |             |     |            |     |
    |     1 | work1-1 | 172.27.0.8  | Leader         | running |  1 |             |     |            |     |
    |     1 | work1-2 | 172.27.0.2  | Quorum Standby | running |  1 |   0/31D3198 |   0 |  0/31D3198 |   0 |
    |     2 | work2-1 | 172.27.0.5  | Quorum Standby | running |  1 |   0/31CDFC0 |   0 |  0/31CDFC0 |   0 |
    |     2 | work2-2 | 172.27.0.7  | Leader         | running |  1 |             |     |            |     |
    +-------+---------+-------------+----------------+---------+----+-------------+-----+------------+-----+
    Citus group: 2
    Primary [work2-2]:
    Candidate ['work2-1'] []:
    When should the switchover take place (e.g. 2024-08-26T08:02 )  [now]:
    Current cluster topology
    + Citus cluster: demo (group: 2, 7179854924063375386) -+-------------+-----+------------+-----+
    | Member  | Host       | Role           | State   | TL | Receive LSN | Lag | Replay LSN | Lag |
    +---------+------------+----------------+---------+----+-------------+-----+------------+-----+
    | work2-1 | 172.27.0.5 | Quorum Standby | running |  1 |   0/31CDFC0 |   0 |  0/31CDFC0 |   0 |
    | work2-2 | 172.27.0.7 | Leader         | running |  1 |             |     |            |     |
    +---------+------------+----------------+---------+----+-------------+-----+------------+-----+
    Are you sure you want to switchover cluster demo, demoting current primary work2-2? [y/N]: y
    2024-08-26 07:02:40.33003 Successfully switched over to "work2-1"
    + Citus cluster: demo (group: 2, 7179854924063375386) --------+---------+------------+---------+
    | Member  | Host       | Role    | State   | TL | Receive LSN |     Lag | Replay LSN |     Lag |
    +---------+------------+---------+---------+----+-------------+---------+------------+---------+
    | work2-1 | 172.27.0.5 | Leader  | running |  1 |             |         |            |         |
    | work2-2 | 172.27.0.7 | Replica | stopped |    |     unknown | unknown |    unknown | unknown |
    +---------+------------+---------+---------+----+-------------+---------+------------+---------+

    postgres@coord1:~$ patronictl list demo
    + Citus cluster: demo ----------+----------------+---------+----+-------------+-----+------------+-----+
    | Group | Member  | Host        | Role           | State   | TL | Receive LSN | Lag | Replay LSN | Lag |
    +-------+---------+-------------+----------------+---------+----+-------------+-----+------------+-----+
    |     0 | coord1  | 172.27.0.10 | Replica        | running |  1 |   0/41C0368 |   0 |  0/41C0368 |   0 |
    |     0 | coord2  | 172.27.0.6  | Quorum Standby | running |  1 |   0/41C0368 |   0 |  0/41C0368 |   0 |
    |     0 | coord3  | 172.27.0.4  | Leader         | running |  1 |             |     |            |     |
    |     1 | work1-1 | 172.27.0.8  | Leader         | running |  1 |             |     |            |     |
    |     1 | work1-2 | 172.27.0.2  | Quorum Standby | running |  1 |   0/31D3198 |   0 |  0/31D3198 |   0 |
    |     2 | work2-1 | 172.27.0.5  | Leader         | running |  2 |             |     |            |     |
    |     2 | work2-2 | 172.27.0.7  | Quorum Standby | running |  2 |   0/31CDFC0 |   0 |  0/31CDFC0 |   0 |
    +-------+---------+-------------+----------------+---------+----+-------------+-----+------------+-----+

这是 coordinator 侧看到的样子::

    # The worker primary notifies the coordinator that it is going to execute "pg_ctl stop".
    2024-08-26 07:02:38,636 DEBUG: query(BEGIN, ())
    2024-08-26 07:02:38,636 DEBUG: query(SELECT pg_catalog.citus_update_node(%s, %s, %s, true, %s), (3, '172.19.0.7-demoted', 5432, 10000))
    # From this moment all application traffic on the coordinator to the worker group 2 is paused.

    # The old worker primary is assigned as a secondary. 
    2024-08-26 07:02:40,084 DEBUG: query(SELECT pg_catalog.citus_update_node(%s, %s, %s, true, %s), (7, '172.19.0.7', 5432, 10000))

    # The future worker primary notifies the coordinator that it acquired the leader lock in DCS and about to run "pg_ctl promote".
    2024-08-26 07:02:40,085 DEBUG: query(SELECT pg_catalog.citus_update_node(%s, %s, %s, true, %s), (3, '172.19.0.5', 5432, 10000))

    # The new worker primary just finished promote and notifies coordinator that it is ready to accept read-write traffic.
    2024-08-26 07:02:41,485 DEBUG: query(COMMIT, ())
    # From this moment the application traffic on the coordinator to the worker group 2 is unblocked.

Secondary 节点
--------------

从 Patroni v4.0.0 开始，没有 ``noloadbalance`` :ref:`tag <tags_settings>` 的 Citus secondary 节点也会注册到 ``pg_dist_node`` 中。
不过，要使用 secondary 节点执行只读查询，应用程序需要修改 `citus.use_secondary_nodes <https://docs.citusdata.com/en/latest/develop/api_guc.html#citus-use-secondary-nodes-enum>`__ GUC。

查看 DCS 内部
-------------

Citus 集群（coordinator 和 workers）在 DCS 中以一系列逻辑上组合在一起的
Patroni 集群形式存储::

    /service/batman/              # scope=batman
    /service/batman/0/            # citus.group=0, coordinator
    /service/batman/0/initialize
    /service/batman/0/leader
    /service/batman/0/members/
    /service/batman/0/members/m1
    /service/batman/0/members/m2
    /service/batman/1/            # citus.group=1, worker
    /service/batman/1/initialize
    /service/batman/1/leader
    /service/batman/1/members/
    /service/batman/1/members/m3
    /service/batman/1/members/m4
    ...

之所以选择这种方式，是因为对大多数 DCS 而言，可以通过一次递归读取请求获取
整个 Citus 集群。只有 Citus
coordinator 节点会读取整棵树，因为它们需要发现
worker 节点。worker 节点只读取自己 group 对应的子树，在某些情况下它们可能读取 coordinator group 的子树。

Kubernetes 上的 Citus
---------------------

由于 Kubernetes 不支持层级结构，我们不得不将
citus group 包含在 Patroni 创建的所有 K8s 对象中::

    batman-0-leader  # the leader config map for the coordinator
    batman-0-config  # the config map holding initialize, config, and history "keys"
    ...
    batman-1-leader  # the leader config map for worker group 1
    batman-1-config
    ...

也就是说，命名模式为：``${scope}-${citus.group}-${type}``\。

Patroni 通过 `label selector`__ 发现所有 Kubernetes 对象，
因此所有运行 Patroni 和 Citus 的 Pod 以及 Endpoints/ConfigMaps 都必须具有
相似的 labels，并且必须使用 Kubernetes
:ref:`settings <kubernetes_settings>` 或 :ref:`environment variables
<kubernetes_environment>` 配置 Patroni 来使用它们。

__ https://kubernetes.io/docs/concepts/overview/working-with-objects/labels/#label-selectors

几个使用 Pod 环境变量的 Patroni 配置示例：

1. coordinator 集群的配置

.. code:: YAML

        apiVersion: v1
        kind: Pod
        metadata:
          labels:
            application: patroni
            citus-group: "0"
            citus-type: coordinator
            cluster-name: citusdemo
          name: citusdemo-0-0
          namespace: default
        spec:
          containers:
          - env:
            - name: PATRONI_SCOPE
              value: citusdemo
            - name: PATRONI_NAME
              valueFrom:
                fieldRef:
                  apiVersion: v1
                  fieldPath: metadata.name
            - name: PATRONI_KUBERNETES_POD_IP
              valueFrom:
                fieldRef:
                  apiVersion: v1
                  fieldPath: status.podIP
            - name: PATRONI_KUBERNETES_NAMESPACE
              valueFrom:
                fieldRef:
                  apiVersion: v1
                  fieldPath: metadata.namespace
            - name: PATRONI_KUBERNETES_LABELS
              value: '{application: patroni}'
            - name: PATRONI_CITUS_DATABASE
              value: citus
            - name: PATRONI_CITUS_GROUP
              value: "0"

2. group 2 的 worker 集群的配置

.. code:: YAML

        apiVersion: v1
        kind: Pod
        metadata:
          labels:
            application: patroni
            citus-group: "2"
            citus-type: worker
            cluster-name: citusdemo
          name: citusdemo-2-0
          namespace: default
        spec:
          containers:
          - env:
            - name: PATRONI_SCOPE
              value: citusdemo
            - name: PATRONI_NAME
              valueFrom:
                fieldRef:
                  apiVersion: v1
                  fieldPath: metadata.name
            - name: PATRONI_KUBERNETES_POD_IP
              valueFrom:
                fieldRef:
                  apiVersion: v1
                  fieldPath: status.podIP
            - name: PATRONI_KUBERNETES_NAMESPACE
              valueFrom:
                fieldRef:
                  apiVersion: v1
                  fieldPath: metadata.namespace
            - name: PATRONI_KUBERNETES_LABELS
              value: '{application: patroni}'
            - name: PATRONI_CITUS_DATABASE
              value: citus
            - name: PATRONI_CITUS_GROUP
              value: "2"

你可能已经注意到，两个示例都设置了 ``citus-group`` label。这个 label
让 Patroni 能够识别对象属于哪个 Citus group。除此之外，还有 ``PATRONI_CITUS_GROUP`` 环境变量，
其值与 ``citus-group`` label 相同。当 Patroni 创建
新的 Kubernetes 对象（ConfigMaps 或 Endpoints）时，会自动在其上设置
``citus-group: ${env.PATRONI_CITUS_GROUP}`` label：

.. code:: YAML

        apiVersion: v1
        kind: ConfigMap
        metadata:
          name: citusdemo-0-leader  # Is generated as ${env.PATRONI_SCOPE}-${env.PATRONI_CITUS_GROUP}-leader
          labels:
            application: patroni    # Is set from the ${env.PATRONI_KUBERNETES_LABELS}
            cluster-name: citusdemo # Is automatically set from the ${env.PATRONI_SCOPE}
            citus-group: '0'        # Is automatically set from the ${env.PATRONI_CITUS_GROUP}

你可以在 Patroni 仓库的 `kubernetes`__ 目录中找到在 Kubernetes 上部署带 Citus 支持的 Patroni 的完整示例。

__ https://github.com/patroni/patroni/tree/master/kubernetes

有两个重要文件：

1. Dockerfile.citus
2. citus_k8s.yaml

Citus 升级与 PostgreSQL 大版本升级
----------------------------------

首先，请阅读 `documentation`__ 中关于升级 Citus 版本的内容。
流程中有一个小的差异：执行升级时，你必须使用 :ref:`patronictl_restart` 而不是 ``systemctl restart`` 来重启
PostgreSQL。

__ https://docs.citusdata.com/en/latest/admin_guide/upgrading_citus.html

Citus 的 PostgreSQL 大版本升级要更复杂一些。你需要结合
Citus 文档中关于大版本升级的技术，以及
Patroni 文档中关于 :ref:`PostgreSQL major upgrade<major_upgrade>` 的内容。
请记住，Citus 集群由多个 Patroni 集群
（coordinator 和 workers）组成，它们都必须独立升级。
