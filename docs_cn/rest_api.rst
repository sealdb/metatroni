.. _rest_api:

Patroni REST API
================

Patroni 拥有功能丰富的 REST API，它在 leader 竞争过程中被 Patroni 自身使用，也被 :ref:`patronictl` 工具用于执行 failover/switchover/reinitialize/restart/reload，还被 HAProxy 或任何其他类型的负载均衡器用于执行 HTTP 健康检查，当然也可以用于监控。下面你将看到 Patroni REST API 端点的列表。

健康检查端点
------------
对于所有健康检查 ``GET`` 请求，Patroni 都会返回一个 JSON 文档，其中包含节点状态以及 HTTP 状态码。如果你不希望或不需要该 JSON 文档，可以考虑使用 ``HEAD`` 或 ``OPTIONS`` 方法，而不是 ``GET``\。

- 仅当 Patroni 节点以 primary 身份运行并持有 leader 锁时，以下对 Patroni REST API 的请求才会返回 HTTP 状态码 **200**\：

  - ``GET /``
  - ``GET /primary``
  - ``GET /read-write``

- ``GET /standby-leader``\：仅当 Patroni 节点在 :ref:`standby cluster <standby_cluster>` 中以 leader 身份运行时，才返回 HTTP 状态码 **200**\。

- ``GET /leader``\：当 Patroni 节点持有 leader 锁时返回 HTTP 状态码 **200**\。与前面两个端点的主要区别在于，它不考虑 PostgreSQL 是作为 ``primary`` 还是 ``standby_leader`` 运行。

- ``GET /replica``\：replica 健康检查端点。仅当 Patroni 节点处于 ``running`` 状态、角色为 ``replica`` 且未设置 ``noloadbalance`` 标签时，才返回 HTTP 状态码 **200**\。

- ``GET /replica?lag=<max-lag>``\：replica 检查端点。除了 ``replica`` 的检查之外，它还会检查复制延迟，并且仅当延迟低于指定值时才返回状态码 **200**\。出于性能考虑，使用 DCS 中的 cluster.last_leader_operation 键获取 Leader 的 wal 位置，并在 replica 上计算延迟。max-lag 可以以字节（整数）或人类可读的值指定，例如 16kB、64MB、1GB。

  - ``GET /replica?lag=1048576``
  - ``GET /replica?lag=1024kB``
  - ``GET /replica?lag=10MB``
  - ``GET /replica?lag=1GB``

- ``GET /replica?tag_key1=value1&tag_key2=value2``\：replica 检查端点。此外，它还会检查用户自定义的标签 ``key1`` 和 ``key2`` 及其在 yaml 配置管理的 **tags** 部分中各自的值。如果某个实例未定义该标签，或者 yaml 配置中的值与查询值不匹配，它将返回 HTTP 状态码 503。

  在以下请求中，由于我们检查的是 leader 或 standby-leader 状态，因此 Patroni 不会应用任何用户自定义的标签，它们将被忽略。

  - ``GET /?tag_key1=value1&tag_key2=value2``
  - ``GET /leader?tag_key1=value1&tag_key2=value2``
  - ``GET /primary?tag_key1=value1&tag_key2=value2``
  - ``GET /read-write?tag_key1=value1&tag_key2=value2``
  - ``GET /standby_leader?tag_key1=value1&tag_key2=value2``
  - ``GET /standby-leader?tag_key1=value1&tag_key2=value2``

- ``GET /read-only``\：与上述端点类似，但同时也包含 primary。

- ``GET /synchronous`` 或 ``GET /sync``\：仅当 Patroni 节点作为 synchronous standby 运行时，才返回 HTTP 状态码 **200**\。

- ``GET /read-only-sync``\：与上述端点类似，但同时也包含 primary。

- ``GET /quorum``\：仅当此 Patroni 节点被列在 primary 的 ``synchronous_standby_names`` 中作为 quorum 节点时，才返回 HTTP 状态码 **200**\。

- ``GET /read-only-quorum``\：与上述端点类似，但同时也包含 primary。

- ``GET /asynchronous`` 或 ``GET /async``\：仅当 Patroni 节点作为 asynchronous standby 运行时，才返回 HTTP 状态码 **200**\。


- ``GET /asynchronous?lag=<max-lag>`` 或 ``GET /async?lag=<max-lag>``\：asynchronous standby 检查端点。除了 ``asynchronous`` 或 ``async`` 的检查之外，它还会检查复制延迟，并且仅当延迟低于指定值时才返回状态码 **200**\。出于性能考虑，使用 DCS 中的 cluster.last_leader_operation 键获取 Leader 的 wal 位置，并在 replica 上计算延迟。max-lag 可以以字节（整数）或人类可读的值指定，例如 16kB、64MB、1GB。

  - ``GET /async?lag=1048576``
  - ``GET /async?lag=1024kB``
  - ``GET /async?lag=10MB``
  - ``GET /async?lag=1GB``

- ``GET /health``\：仅当 PostgreSQL 已启动并正在运行时，才返回 HTTP 状态码 **200**\。

- ``GET /liveness``\：如果 Patroni 的心跳循环正常运行，则返回 HTTP 状态码 **200**\；如果上次运行在 primary 上距今超过 ``ttl`` 秒，或在 replica 上距今超过 ``2*ttl`` 秒，则返回 **503**\。可用于 ``livenessProbe``\。

- ``GET /readiness?lag=<max-lag>&mode=apply|write``\：当 Patroni 节点作为 leader 运行，或者当 PostgreSQL 已启动、正在复制且落后于 leader 的程度没有超出允许范围时，返回 HTTP 状态码 **200**\。lag 参数设置 standby 允许落后的程度，默认为 ``maximum_lag_on_failover``\。lag 可以以字节或人类可读的值指定，例如 16kB、64MB、1GB。mode 设置 WAL 是需要被回放（apply）还是仅需被接收（write）。默认值为 apply。

  当用作 Kubernetes 的 ``readinessProbe`` 时，它可以确保新启动的 pod 只有在追赶上 leader 之后才会变为 ready 状态。这与 PodDisruptionBudget 结合使用，可以防止在节点滚动重启期间 leader 被过早终止。它还能确保无法跟上复制进度的 replica 不承担只读流量。在无法使用 Kubernetes endpoints 进行 leader 选举的环境（如 OpenShift）中，该端点也可用于 ``readinessProbe``\。

``liveness`` 端点非常轻量，不会执行任何 SQL。探针应配置为在 leader 键即将到期时开始失败。使用 ``ttl`` 的默认值 ``30s`` 时，示例探针配置如下：

.. code-block:: yaml

    readinessProbe:
      httpGet:
        scheme: HTTP
        path: /readiness
        port: 8008
      initialDelaySeconds: 3
      periodSeconds: 10
      timeoutSeconds: 5
      successThreshold: 1
      failureThreshold: 3
    livenessProbe:
      httpGet:
        scheme: HTTP
        path: /liveness
        port: 8008
      initialDelaySeconds: 3
      periodSeconds: 10
      timeoutSeconds: 5
      successThreshold: 1
      failureThreshold: 3


监控端点
--------

``GET /patroni`` 在 leader 竞争过程中被 Patroni 使用。它也可以被你的监控系统使用。该端点生成的 JSON 文档与健康检查端点生成的 JSON 具有相同的结构。

**示例：** 一个健康的 cluster

.. code-block:: bash

    $ curl -s http://localhost:8008/patroni | jq .
    {
      "state": "running",
      "postmaster_start_time": "2024-08-28 19:39:26.352526+00:00",
      "role": "primary",
      "server_version": 160004,
      "xlog": {
        "location": 67395656
      },
      "timeline": 1,
      "replication": [
        {
          "usename": "replicator",
          "application_name": "patroni2",
          "client_addr": "10.89.0.6",
          "state": "streaming",
          "sync_state": "async",
          "sync_priority": 0
        },
        {
          "usename": "replicator",
          "application_name": "patroni3",
          "client_addr": "10.89.0.2",
          "state": "streaming",
          "sync_state": "async",
          "sync_priority": 0
        }
      ],
      "dcs_last_seen": 1692356718,
      "tags": {
        "clonefrom": true
      },
      "database_system_identifier": "7268616322854375442",
      "patroni": {
        "version": "4.0.0",
        "scope": "demo",
        "name": "patroni1"
      }
    }

**示例：** 一个未加锁的 cluster

.. code-block:: bash

    $ curl -s http://localhost:8008/patroni  | jq .
    {
      "state": "running",
      "postmaster_start_time": "2024-08-28 19:39:26.352526+00:00",
      "role": "replica",
      "server_version": 160004,
      "xlog": {
        "received_location": 67419744,
        "replayed_location": 67419744,
        "replayed_timestamp": null,
        "paused": false
      },
      "timeline": 1,
      "replication": [
        {
          "usename": "replicator",
          "application_name": "patroni2",
          "client_addr": "10.89.0.6",
          "state": "streaming",
          "sync_state": "async",
          "sync_priority": 0
        },
        {
          "usename": "replicator",
          "application_name": "patroni3",
          "client_addr": "10.89.0.2",
          "state": "streaming",
          "sync_state": "async",
          "sync_priority": 0
        }
      ],
      "cluster_unlocked": true,
      "dcs_last_seen": 1692356928,
      "tags": {
        "clonefrom": true
      },
      "database_system_identifier": "7268616322854375442",
      "patroni": {
        "version": "4.0.0",
        "scope": "demo",
        "name": "patroni1"
      }
    }

**示例：** 一个启用了 :ref:`DCS failsafe mode <dcs_failsafe_mode>` 的未加锁 cluster

.. code-block:: bash

    $ curl -s http://localhost:8008/patroni  | jq .
    {
      "state": "running",
      "postmaster_start_time": "2024-08-28 19:39:26.352526+00:00",
      "role": "replica",
      "server_version": 160004,
      "xlog": {
        "location": 67420024
      },
      "timeline": 1,
      "replication": [
        {
          "usename": "replicator",
          "application_name": "patroni2",
          "client_addr": "10.89.0.6",
          "state": "streaming",
          "sync_state": "async",
          "sync_priority": 0
        },
        {
          "usename": "replicator",
          "application_name": "patroni3",
          "client_addr": "10.89.0.2",
          "state": "streaming",
          "sync_state": "async",
          "sync_priority": 0
        }
      ],
      "cluster_unlocked": true,
      "failsafe_mode_is_active": true,
      "dcs_last_seen": 1692356928,
      "tags": {
        "clonefrom": true
      },
      "database_system_identifier": "7268616322854375442",
      "patroni": {
        "version": "4.0.0",
        "scope": "demo",
        "name": "patroni1"
      }
    }

**示例：** 一个启用了 :ref:`pause mode <pause>` 的 cluster

.. code-block:: bash

    $ curl -s http://localhost:8008/patroni  | jq .
    {
      "state": "running",
      "postmaster_start_time": "2024-08-28 19:39:26.352526+00:00",
      "role": "replica",
      "server_version": 160004,
      "xlog": {
        "location": 67420024
      },
      "timeline": 1,
      "replication": [
        {
          "usename": "replicator",
          "application_name": "patroni2",
          "client_addr": "10.89.0.6",
          "state": "streaming",
          "sync_state": "async",
          "sync_priority": 0
        },
        {
          "usename": "replicator",
          "application_name": "patroni3",
          "client_addr": "10.89.0.2",
          "state": "streaming",
          "sync_state": "async",
          "sync_priority": 0
        }
      ],
      "pause": true,
      "dcs_last_seen": 1724874295,
      "tags": {
        "clonefrom": true
      },
      "database_system_identifier": "7268616322854375442",
      "patroni": {
        "version": "4.0.0",
        "scope": "demo",
        "name": "patroni1"
      }
    }

通过 ``GET /metrics`` 端点以 Prometheus 格式获取 Patroni 指标。

.. code-block:: bash

	$ curl http://localhost:8008/metrics

	# HELP patroni_version Patroni semver without periods. \
	# TYPE patroni_version gauge
	patroni_version{scope="batman",name="patroni1"} 040000
	# HELP patroni_postgres_running Value is 1 if Postgres is running, 0 otherwise.
	# TYPE patroni_postgres_running gauge
	patroni_postgres_running{scope="batman",name="patroni1"} 1
	# HELP patroni_postmaster_start_time Epoch seconds since Postgres started.
	# TYPE patroni_postmaster_start_time gauge
	patroni_postmaster_start_time{scope="batman",name="patroni1"} 1724873966.352526
	# HELP patroni_primary Value is 1 if this node is the leader, 0 otherwise.
	# TYPE patroni_primary gauge
	patroni_primary{scope="batman",name="patroni1"} 1
	# HELP patroni_xlog_location Current location of the Postgres transaction log, 0 if this node is not the leader.
	# TYPE patroni_xlog_location counter
	patroni_xlog_location{scope="batman",name="patroni1"} 22320573386952
	# HELP patroni_standby_leader Value is 1 if this node is the standby_leader, 0 otherwise.
	# TYPE patroni_standby_leader gauge
	patroni_standby_leader{scope="batman",name="patroni1"} 0
	# HELP patroni_replica Value is 1 if this node is a replica, 0 otherwise.
	# TYPE patroni_replica gauge
	patroni_replica{scope="batman",name="patroni1"} 0
	# HELP patroni_sync_standby Value is 1 if this node is a sync standby replica, 0 otherwise.
	# TYPE patroni_sync_standby gauge
	patroni_sync_standby{scope="batman",name="patroni1"} 0
	# HELP patroni_quorum_standby Value is 1 if this node is a quorum standby replica, 0 otherwise.
	# TYPE patroni_quorum_standby gauge
	patroni_quorum_standby{scope="batman",name="patroni1"} 0
	# HELP patroni_xlog_received_location Current location of the received Postgres transaction log, 0 if this node is not a replica.
	# TYPE patroni_xlog_received_location counter
	patroni_xlog_received_location{scope="batman",name="patroni1"} 0
	# HELP patroni_xlog_replayed_location Current location of the replayed Postgres transaction log, 0 if this node is not a replica.
	# TYPE patroni_xlog_replayed_location counter
	patroni_xlog_replayed_location{scope="batman",name="patroni1"} 0
	# HELP patroni_xlog_replayed_timestamp Current timestamp of the replayed Postgres transaction log, 0 if null.
	# TYPE patroni_xlog_replayed_timestamp gauge
	patroni_xlog_replayed_timestamp{scope="batman",name="patroni1"} 0
	# HELP patroni_xlog_paused Value is 1 if the Postgres xlog is paused, 0 otherwise.
	# TYPE patroni_xlog_paused gauge
	patroni_xlog_paused{scope="batman",name="patroni1"} 0
	# HELP patroni_postgres_streaming Value is 1 if Postgres is streaming, 0 otherwise.
	# TYPE patroni_postgres_streaming gauge
	patroni_postgres_streaming{scope="batman",name="patroni1"} 1
	# HELP patroni_postgres_in_archive_recovery Value is 1 if Postgres is replicating from archive, 0 otherwise.
	# TYPE patroni_postgres_in_archive_recovery gauge
	patroni_postgres_in_archive_recovery{scope="batman",name="patroni1"} 0
	# HELP patroni_postgres_server_version Version of Postgres (if running), 0 otherwise.
	# TYPE patroni_postgres_server_version gauge
	patroni_postgres_server_version{scope="batman",name="patroni1"} 160004
	# HELP patroni_cluster_unlocked Value is 1 if the cluster is unlocked, 0 if locked.
	# TYPE patroni_cluster_unlocked gauge
	patroni_cluster_unlocked{scope="batman",name="patroni1"} 0
	# HELP patroni_postgres_timeline Postgres timeline of this node (if running), 0 otherwise.
	# TYPE patroni_postgres_timeline counter
	patroni_failsafe_mode_is_active{scope="batman",name="patroni1"} 0
	# HELP patroni_postgres_timeline Postgres timeline of this node (if running), 0 otherwise.
	# TYPE patroni_postgres_timeline counter
	patroni_postgres_timeline{scope="batman",name="patroni1"} 24
	# HELP patroni_dcs_last_seen Epoch timestamp when DCS was last contacted successfully by Patroni.
	# TYPE patroni_dcs_last_seen gauge
	patroni_dcs_last_seen{scope="batman",name="patroni1"} 1724874235
	# HELP patroni_pending_restart Value is 1 if the node needs a restart, 0 otherwise.
	# TYPE patroni_pending_restart gauge
	patroni_pending_restart{scope="batman",name="patroni1"} 1
	# HELP patroni_is_paused Value is 1 if auto failover is disabled, 0 otherwise.
	# TYPE patroni_is_paused gauge
	patroni_is_paused{scope="batman",name="patroni1"} 1
	# HELP patroni_postgres_state Numeric representation of Postgres state.
	# Values: 0=initdb, 1=initdb_failed, 2=custom_bootstrap, 3=custom_bootstrap_failed, 4=creating_replica, 5=running, 6=starting, 7=bootstrap_starting, 8=start_failed, 9=restarting, 10=restart_failed, 11=stopping, 12=stopped, 13=stop_failed, 14=crashed
	# TYPE patroni_postgres_state gauge
	patroni_postgres_state{scope="batman",name="patroni1"} 5

PostgreSQL 状态值
^^^^^^^^^^^^^^^^^

``patroni_postgres_state`` 指标提供了当前 PostgreSQL 实例状态的数值表示。这对于需要随时间跟踪状态变化的监控和告警系统非常有用。这些数值是通过 ``PostgresqlState.get_metrics_description()`` 静态方法生成的。

.. list-table:: PostgreSQL State Values
   :widths: 10 20 50
   :header-rows: 1

   * -  值
     - 状态名称
     - 描述
   * -  0
     - initdb
     - 正在初始化新 cluster
   * -  1
     - initdb_failed
     - 新 cluster 初始化失败
   * -  2
     - custom_bootstrap
     - 正在运行自定义 bootstrap 脚本
   * -  3
     - custom_bootstrap_failed
     - 自定义 bootstrap 脚本失败
   * -  4
     - creating_replica
     - 正在从 primary 创建 replica
   * -  5
     - running
     - PostgreSQL 正在正常运行
   * -  6
     - starting
     - PostgreSQL 正在启动
   * -  7
     - bootstrap_starting
     - 自定义 bootstrap 后启动
   * -  8
     - start_failed
     - PostgreSQL 启动失败
   * -  9
     - restarting
     - PostgreSQL 正在重启
   * -  10
     - restart_failed
     - PostgreSQL 重启失败
   * -  11
     - stopping
     - PostgreSQL 正在停止
   * -  12
     - stopped
     - PostgreSQL 已停止
   * -  13
     - stop_failed
     - PostgreSQL 停止失败
   * -  14
     - crashed
     - PostgreSQL 已崩溃

.. note::
   这些数值是固定的，永远不会改变，以保持与现有监控系统的向后兼容。如果将来添加新的状态，它们将被分配新的数值，而不会改变现有数值。


Cluster 状态端点
----------------

- ``GET /cluster`` 端点会生成一个描述当前 cluster 拓扑和状态的 JSON 文档：

.. code-block:: bash

    $ curl -s http://localhost:8008/cluster | jq .
    {
      "members": [
        {
          "name": "patroni1",
          "role": "leader",
          "state": "running",
          "api_url": "http://10.89.0.4:8008/patroni",
          "host": "10.89.0.4",
          "port": 5432,
          "timeline": 5,
          "tags": {
            "clonefrom": true
          }
        },
        {
          "name": "patroni2",
          "role": "replica",
          "state": "streaming",
          "api_url": "http://10.89.0.6:8008/patroni",
          "host": "10.89.0.6",
          "port": 5433,
          "timeline": 5,
          "tags": {
            "clonefrom": true
          },
          "receive_lag": 0,
          "receive_lsn": "0/4000060",
          "replay_lag": 0,
          "replay_lsn": "0/4000060",
          "lag": 0,
          "lsn": "0/4000060"
        }
      ],
      "scope": "demo",
      "scheduled_switchover": {
        "at": "2023-09-24T10:36:00+02:00",
        "from": "patroni1",
        "to": "patroni3"
      }
    }


- ``GET /history`` 端点提供 cluster 的 switchover/failover 历史视图。其格式与 ``pg_wal`` 目录中 history 文件的内容非常相似。唯一的区别在于 timestamp 字段，它显示了新 timeline 的创建时间。

.. code-block:: bash

    $ curl -s http://localhost:8008/history | jq .
    [
      [
        1,
        25623960,
        "no recovery target specified",
        "2019-09-23T16:57:57+02:00"
      ],
      [
        2,
        25624344,
        "no recovery target specified",
        "2019-09-24T09:22:33+02:00"
      ],
      [
        3,
        25624752,
        "no recovery target specified",
        "2019-09-24T09:26:15+02:00"
      ],
      [
        4,
        50331856,
        "no recovery target specified",
        "2019-09-24T09:35:52+02:00"
      ]
    ]

.. _config_endpoint:

Config 端点
-----------

``GET /config``\：获取当前版本的动态配置：

.. code-block:: bash

	$ curl -s http://localhost:8008/config | jq .
	{
	  "ttl": 30,
	  "loop_wait": 10,
	  "retry_timeout": 10,
	  "maximum_lag_on_failover": 1048576,
	  "postgresql": {
	    "use_slots": true,
	    "use_pg_rewind": true,
	    "parameters": {
	      "hot_standby": "on",
	      "wal_level": "hot_standby",
	      "max_wal_senders": 5,
	      "max_replication_slots": 5,
	      "max_connections": "100"
	    }
	  }
	}


``PATCH /config``\：更改现有配置。

.. code-block:: bash

	$ curl -s -XPATCH -d \
		'{"loop_wait":5,"ttl":20,"postgresql":{"parameters":{"max_connections":"101"}}}' \
		http://localhost:8008/config | jq .
	{
	  "ttl": 20,
	  "loop_wait": 5,
	  "maximum_lag_on_failover": 1048576,
	  "retry_timeout": 10,
	  "postgresql": {
	    "use_slots": true,
	    "use_pg_rewind": true,
	    "parameters": {
	      "hot_standby": "on",
	      "wal_level": "hot_standby",
	      "max_wal_senders": 5,
	      "max_replication_slots": 5,
	      "max_connections": "101"
	    }
	  }
	}

上述 REST API 调用会修改现有配置，并返回新配置。

让我们检查节点是否已处理此配置。首先，它应该开始每 5 秒打印一次日志（loop_wait=5）。修改 "max_connections" 需要重启，因此应该暴露 "pending_restart" 标志：

.. code-block:: bash

	$ curl -s http://localhost:8008/patroni | jq .
	{
	  "database_system_identifier": "6287881213849985952",
	  "postmaster_start_time": "2024-08-28 19:39:26.352526+00:00",
	  "xlog": {
	    "location": 2197818976
	  },
	  "timeline": 1,
	  "dcs_last_seen": 1724874545,
	  "database_system_identifier": "7408277255830290455",
	  "pending_restart": true,
	  "pending_restart_reason": {
	    "max_connections": {
	      "old_value": "100",
	      "new_value": "101"
	    }
	  },
	  "patroni": {
	    "version": "4.0.0",
	    "scope": "batman",
	    "name": "patroni1"
	  },
	  "state": "running",
	  "role": "primary",
	  "server_version": 160004
	}

移除参数：

如果你想要移除（重置）某个设置，只需用 ``null`` 对其进行 patch 即可：

.. code-block:: bash

	$ curl -s -XPATCH -d \
		'{"postgresql":{"parameters":{"max_connections":null}}}' \
		http://localhost:8008/config | jq .
	{
	  "ttl": 20,
	  "loop_wait": 5,
	  "retry_timeout": 10,
	  "maximum_lag_on_failover": 1048576,
	  "postgresql": {
	    "use_slots": true,
	    "use_pg_rewind": true,
	    "parameters": {
	      "hot_standby": "on",
	      "unix_socket_directories": ".",
	      "wal_level": "hot_standby",
	      "max_wal_senders": 5,
	      "max_replication_slots": 5
	    }
	  }
	}

上述调用会从动态配置中移除 ``postgresql.parameters.max_connections``\。

``PUT /config``\：也可以无条件地完整重写现有的动态配置：

.. code-block:: bash

	$ curl -s -XPUT -d \
		'{"maximum_lag_on_failover":1048576,"retry_timeout":10,"postgresql":{"use_slots":true,"use_pg_rewind":true,"parameters":{"hot_standby":"on","wal_level":"hot_standby","unix_socket_directories":".","max_wal_senders":5}},"loop_wait":3,"ttl":20}' \
		http://localhost:8008/config | jq .
	{
	  "ttl": 20,
	  "maximum_lag_on_failover": 1048576,
	  "retry_timeout": 10,
	  "postgresql": {
	    "use_slots": true,
	    "parameters": {
	      "hot_standby": "on",
	      "unix_socket_directories": ".",
	      "wal_level": "hot_standby",
	      "max_wal_senders": 5
	    },
	    "use_pg_rewind": true
	  },
	  "loop_wait": 3
	}


Switchover 和 failover 端点
---------------------------

.. _switchover_api:

Switchover
^^^^^^^^^^

``/switchover`` 端点仅在 cluster 健康（存在 leader）时有效。它还允许在指定时间计划执行 switchover。

与 ``/failover`` 端点不同，在调用 ``/switchover`` 端点时可以指定 candidate，但并非必须。如果未提供 candidate，则在 leader 退位之后，cluster 中所有符合条件的节点都将参与 leader 竞争。

在 ``POST`` 请求的 JSON body 中，你必须指定 ``leader`` 字段。``candidate`` 和 ``scheduled_at`` 字段是可选的，可用于在特定时间计划执行 switchover。

根据情况不同，请求可能返回不同的 HTTP 状态码和响应体。当 switchover 或 failover 成功完成时返回状态码 **200**\。如果 switchover 成功计划，Patroni 将返回 HTTP 状态码 **202**\。如果出现错误，将返回错误状态码（**400**\、**412** 或 **503** 之一），并在响应体中包含一些详细信息。

``DELETE /switchover`` 可用于删除当前已计划的 switchover。

**示例：** 向任意健康的 standby 执行 switchover

.. code-block:: bash

	$ curl -s http://localhost:8008/switchover -XPOST -d '{"leader":"postgresql1"}'
	Successfully switched over to "postgresql2"


**示例：** 向指定节点执行 switchover

.. code-block:: bash

	$ curl -s http://localhost:8008/switchover -XPOST -d \
		'{"leader":"postgresql1","candidate":"postgresql2"}'
	Successfully switched over to "postgresql2"


**示例：** 在指定时间计划一次从 leader 到 cluster 中任意其他健康 standby 的 switchover。

.. code-block:: bash

	$ curl -s http://localhost:8008/switchover -XPOST -d \
		'{"leader":"postgresql0","scheduled_at":"2019-09-24T12:00+00"}'
	Switchover scheduled


Failover
^^^^^^^^

当没有健康节点时（例如，如果所有 synchronous standby 都不够健康而无法提升，则可切换到 asynchronous standby），可以使用 ``/failover`` 端点执行手动 failover。不过并不要求 cluster 没有 leader——failover 也可以在健康的 cluster 上执行。

在 ``POST`` 请求的 JSON body 中，你必须指定 ``candidate`` 字段。如果指定了 ``leader`` 字段，则会改为触发 switchover。

**示例：**

.. code-block:: bash

	$ curl -s http://localhost:8008/failover -XPOST -d '{"candidate":"postgresql1"}'
	Successfully failed over to "postgresql1"

.. warning::
	使用此端点时请 :ref:`务必小心 <failover_healthcheck>`，因为在某些情况下它可能导致数据丢失。在大多数情况下，:ref:`switchover 端点 <switchover_api>` 就能满足管理员的需求。


``POST /switchover`` 和 ``POST /failover`` 端点分别由 :ref:`patronictl_switchover` 和 :ref:`patronictl_failover` 使用。

``DELETE /switchover`` 由 :ref:`patronictl flush cluster-name switchover <patronictl_flush_parameters>` 使用。

.. list-table:: Failover/Switchover comparison
   :widths: 25 25 25
   :header-rows: 1

   * - 
     - Failover
     - Switchover
   * -  需要指定 leader
     - 否
     - 是
   * -  需要指定 candidate
     - 是
     - 否
   * -  可在 pause 模式下运行
     - 是
     - 是（仅可指定候选节点）
   * -  可计划执行
     - 否
     - 是（如果不在 pause 模式下）

.. _failover_healthcheck:

健康的 standby
^^^^^^^^^^^^^^

cluster 的一个 member 需要满足以下几项检查，才能在 switchover 期间参与 leader 竞争，或作为 failover/switchover 候选节点成为 leader：

- 可以通过 Patroni API 访问；
- 未将 ``nofailover`` 标签设置为 ``true``\；
- watchdog 完全正常（如果配置要求的话）；
- 在健康 cluster 中执行 switchover 或自动 failover 时，不超过最大复制延迟（``maximum_lag_on_failover`` :ref:`配置参数 <dynamic_configuration>`）；
- 在健康 cluster 中执行 switchover 或自动 failover 时，如果 ``check_timeline`` :ref:`配置参数 <dynamic_configuration>` 设置为 ``true``\，则 timeline 号不能小于 cluster 的 timeline；
- 在 :ref:`synchronous mode <synchronous_mode>` 下：

  - 在执行 switchover 时（无论是否指定候选节点）：必须出现在 ``/sync`` key 的 members 中；
  - 对于健康或不健康 cluster 中的 failover，此检查会被省略。

.. warning::
    在无 leader 的 cluster 中执行手动 failover 时，即使候选节点存在以下情况，也允许其提升：
	- 当启用 synchronous mode 时，它不在 ``/sync`` key 的 members 中；
	- 它的 lag 超过了允许的最大复制延迟；
	- 它的 timeline 号小于最后已知的 cluster timeline。

.. _restart_endpoint:

Restart 端点
------------

- ``POST /restart``\：通过执行 ``POST /restart`` 调用，你可以重启指定节点上的 Postgres。在 ``POST`` 请求的 JSON body 中，可以可选地指定一些重启条件：

  - **restart_pending**\：布尔值，如果设置为 ``true``\，则 Patroni 只会在需要重启以应用 PostgreSQL 配置中的某些更改时重启 PostgreSQL。
  - **role**\：仅当节点的当前角色与 POST 请求中的角色匹配时才执行重启。
  - **postgres_version**\：仅当当前 postgres 版本低于 POST 请求中指定的版本时才执行重启。
  - **timeout**\：在 PostgreSQL 开始接受连接之前我们应该等待多长时间。覆盖 ``primary_start_timeout``\。
  - **schedule**\：带时区的 timestamp，将重启计划到将来的某个时间。

- ``DELETE /restart``\：删除已计划的重启

``POST /restart`` 和 ``DELETE /restart`` 端点分别由 :ref:`patronictl_restart` 和 :ref:`patronictl flush cluster-name restart <patronictl_flush_parameters>` 使用。

.. _reload_endpoint:

Reload 端点
-----------

``POST /reload`` 调用将指示 Patroni 重新读取并应用配置文件。这相当于向 Patroni 进程发送 ``SIGHUP`` 信号。如果你更改了某些需要重启才能生效的 Postgres 参数（例如 **shared_buffers**\），你仍然必须通过调用 ``POST /restart`` 端点或借助 :ref:`patronictl_restart` 显式地重启 Postgres。

reload 端点由 :ref:`patronictl_reload` 使用。


Reinitialize 端点
-----------------

``POST /reinitialize``\：重新初始化指定节点上的 PostgreSQL 数据目录。它只允许在 replica 上执行。调用后，它将删除数据目录并启动 ``pg_basebackup`` 或某种替代的 :ref:`replica 创建方法 <custom_replica_creation>`。

如果 Patroni 正处于尝试恢复（重启）故障 Postgres 的循环中，该调用可能会失败。为了克服此问题，可以在请求 body 中指定 ``{"force":true}``\。

你可以在请求 body 中指定 {"from-leader":true}，以直接从 leader 节点获取 basebackup。当所有 replica 节点都故障时执行 reinit，此选项非常有用。

reinitialize 端点由 :ref:`patronictl_reinit` 使用。
