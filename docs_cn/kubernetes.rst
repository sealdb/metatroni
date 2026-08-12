.. _kubernetes:

在 Kubernetes 中使用 Patroni
=============================

Patroni 可以使用 Kubernetes 对象来存储集群状态并管理 leader key。这使它能够在没有一致性存储的情况下在 Kubernetes 环境中运行 Postgres，也就是说，无需额外部署 Etcd。Patroni 可以用来存储 leader key 和配置 key 的 Kubernetes 对象有两种不同类型，它们通过 `kubernetes.use_endpoints` 或 `PATRONI_KUBERNETES_USE_ENDPOINTS` 环境变量进行配置。

使用 Endpoints
--------------

尽管这是推荐模式，但出于兼容性原因，它默认是关闭的。启用后，Patroni 将集群配置和 leader key 存储在其创建的相应 `Endpoints` 的 `metadata: annotations` 字段中。切换 leader 比使用 `ConfigMaps` 时更安全，因为包含 leader 信息的 annotations 和指向正在运行的 leader pod 的实际地址会同时一次性更新。

使用 ConfigMaps
---------------

在这种模式下，Patroni 将创建 ConfigMaps 而不是 Endpoints，并将 key 存储在这些 ConfigMaps 的元数据中。切换 leader 至少需要两次更新，一次更新 leader ConfigMap，另一次更新相应的 Endpoint。

要将流量引导到 Postgres leader，你需要配置 Kubernetes Postgres 服务，使用带有 `role_label` （在 patroni 配置中配置）的标签选择器。

请注意，在某些情况下，例如在 OpenShift 上运行时，除了使用 ConfigMaps 之外别无选择。

配置
-------------

Patroni Kubernetes 的 :ref:`settings <kubernetes_settings>` 和 :ref:`environment variables <kubernetes_environment>` 在文档的通用章节中已有介绍。

.. _kubernetes_role_values:

自定义 role label
^^^^^^^^^^^^^^^^^^^^

默认情况下，Patroni 会根据节点的角色，在它运行的 pod 上设置相应的标签，例如 ``role=primary``。标签的 key 和 value 可以通过 `kubernetes.role_label`、`kubernetes.leader_label_value`、`kubernetes.follower_label_value` 和 `kubernetes.standby_leader_label_value` 进行自定义。

请注意，如果你要从默认 role labels 迁移到自定义 labels，可以按照以下迁移步骤减少停机时间：

1. 使用 `kubernetes.tmp_role_label` （如 ``tmp_role``）为 pod 添加一个使用原始角色值的临时标签。pod 重启后，它们将获得 Patroni 设置的以下标签：

  .. code:: YAML

    labels:
      cluster-name: foo
      role: primary
      tmp_role: primary

2. 在所有 pod 都更新之后，修改 service selector，使其选择临时标签。

  .. code:: YAML

    selector:
      cluster-name: foo
      tmp_role: primary

3. 添加你的自定义 role label（例如，设置 `kubernetes.leader_label_value=primary`）。pod 重启后，它们将获得 Patroni 设置的以下新标签：

  .. code:: YAML

    labels:
      cluster-name: foo
      role: primary
      tmp_role: primary

4. 在所有 pod 再次更新之后，修改 service selector，使其使用新的角色值。

  .. code:: YAML

    selector:
      cluster-name: foo
      role: primary

5. 最后，从你的配置中移除临时标签，并更新所有 pod。

  .. code:: YAML

    labels:
      cluster-name: foo
      role: primary

示例
--------

- Patroni 仓库中的 `kubernetes <https://github.com/patroni/patroni/tree/master/kubernetes>`__ 文件夹包含 Docker 镜像示例，以及用于测试 Patroni Kubernetes 部署的 Kubernetes manifest。请注意，在当前状态下，由于权限问题，它无法使用 PersistentVolumes。

- 你可以在 `Spilo Project <https://github.com/zalando/spilo>`_ 中找到可以使用 Persistent Volumes 的全功能 Docker 镜像。

- 还有一个 `Helm chart <https://github.com/kubernetes/charts/tree/master/incubator/patroni>`_，用于部署在 Kubernetes 上运行并配置了 Patroni 的 Spilo 镜像。

- 为了使用 Patroni 和 Spilo 大规模运行你的数据库集群，请查看 `postgres-operator <https://github.com/zalando/postgres-operator>`_ 项目。它实现了 operator 模式来管理 Spilo 集群。
