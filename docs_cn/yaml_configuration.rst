.. _yaml_configuration:

============================
YAML 配置设置
============================


全局/通用
----------------
-  **thread\_pool\_size**：Patroni 用于执行异步任务以及在 leader race 或 failsafe 检查期间通过 REST API 与其他成员通信的线程池大小。最小值为 ``5``，默认值为 ``5``。
-  **thread\_stack\_size**：指定 Patroni 启动的线程所使用的栈大小。该值必须按 ``64kB`` 对齐。最小值为 ``64kB``，默认值（由 Patroni 设置）为 ``512kB``。
-  **name**：主机名称。在集群中必须唯一。
-  **namespace**：配置存储中 Patroni 保存集群信息的路径。默认值："/service"
-  **scope**：集群名称

.. _log_settings:

日志
----
-  **type**：设置日志格式。可以是 **plain** 或 **json**。要使用 **json** 格式，你必须安装 :ref:`jsonlogger <extras>`。默认值为 **plain**。
-  **level**：设置常规日志级别。默认值为 **INFO** （参见 `Python 日志文档 <https://docs.python.org/3.6/library/logging.html#levels>`_）
-  **traceback\_level**：设置 traceback 可见的级别。默认值为 **ERROR**。如果只想在启用 **log.level=DEBUG** 时看到 traceback，请将其设置为 **DEBUG**。
-  **format**：设置日志格式字符串。如果日志类型是 **plain**，日志格式应为字符串。可用属性请参阅
   `LogRecord 的属性 <https://docs.python.org/3.6/library/logging.html#logrecord-attributes>`_。
   如果日志类型是 **json**，日志格式除了字符串外还可以是列表。列表中的每一项
   应对应 LogRecord 的属性。请注意，只需要字段名，且应省略 **%(**
   和 **)**。如果你希望用不同的 key 名输出某个日志字段，可以使用字典，
   字典的 key 是日志字段，value 是你希望在日志中输出的字段名称。
   默认值为 **%(asctime)s %(levelname)s: %(message)s**
-  **dateformat**：设置日期时间格式字符串。（参见 `formatTime() 文档 <https://docs.python.org/3.6/library/logging.html#logging.Formatter.formatTime>`_）
-  **static_fields**：向日志中添加额外字段。此选项仅在日志类型设置为 **json** 时可用。
-  **max\_queue\_size**：Patroni 使用两阶段日志记录。日志记录先写入内存队列，再由一个独立的线程从队列中取出并写入 stderr 或文件。内部队列的最大大小默认限制为 **1000** 条记录，足以保留过去 1h20m 的日志。
-  **dir**：写入应用程序日志的目录。该目录必须存在，并且执行 Patroni 的用户必须对其有写权限。如果你设置了此值，应用程序默认会保留 4 个 25MB 的日志。你可以通过 `file_num` 和 `file_size` 调整这些保留策略（见下文）。
-  **mode**：日志文件的权限（例如 ``0644``）。如果未指定，将根据当前 umask 值设置权限。
-  **file\_num**：保留的应用程序日志数量。
-  **file\_size**：触发日志滚动（log rolling）的 patroni.log 文件大小（以字节为单位）。
-  **loggers**：该配置段允许按 python 模块重新定义日志级别

   -  **patroni.postmaster: WARNING**
   -  **urllib3: DEBUG**
-  **deduplicate_heartbeat_logs**：如果设置为 ``true``，连续且相同的心跳日志将不会被输出。默认值为 ``false``。

.. warning::
   HA 循环的执行时间点对于诊断因资源耗尽等问题导致的 failover 非常有价值。当 ``deduplicate_heartbeat_logs`` 设置为 ``true`` 时，将不会为 HA 循环的执行生成日志（除非 leader 发生变化），因此这些可能有用的信息将无法从日志中获取。

以下是一个如何配置 patroni 以 json 格式记录日志的示例。

.. code:: YAML

   log:
      type: json
      format:
         - message
         - module
         - asctime: '@timestamp'
         - levelname: level
      static_fields:
         app: patroni

.. _bootstrap_settings:

Bootstrap 配置
-----------------------

.. note::
    一旦 Patroni 首次初始化集群并将设置存储到 DCS 后，之后对 YAML 配置中 ``bootstrap.dcs`` 配置段的任何
    修改都将不再生效！如果你想修改它们，
    请使用 :ref:`patronictl_edit_config` 或 Patroni 的 :ref:`REST API <rest_api>`。

-  **bootstrap**：

   -  **dcs**：初始化新集群后，此配置段将被写入指定配置存储的 `/<namespace>/<scope>/config`，即集群的全局动态配置。你可以将 :ref:`Dynamic Configuration settings <dynamic_configuration>` 中描述的任何参数放在 ``bootstrap.dcs`` 下；在 Patroni 初始化（bootstrap）新集群之后，会将此配置段写入配置存储的 `/<namespace>/<scope>/config`。
   -  **method**：用于 bootstrap 此集群的自定义脚本。

      详细信息请参阅 :ref:`custom bootstrap methods documentation <custom_bootstrap>`。
      当指定 ``initdb`` 时，会回退到默认的 ``initdb`` 命令。当配置文件中没有 ``method``
      参数时，也会触发 ``initdb``。
   -  **initdb**：（可选）传递给 initdb 的选项列表。

      -  **- data-checksums**：在 9.3 上需要 pg_rewind 时必须启用。
      -  **- encoding: UTF8**：新数据库的默认编码。
      -  **- locale: UTF8**：新数据库的默认区域设置。
   -  **post\_bootstrap** 或 **post\_init**：初始化集群后执行的附加脚本。脚本接收一个连接字符串 URL（用户名是集群超级用户）。PGPASSFILE 变量被设置为 pgpass 文件的位置。

.. _citus_settings:

Citus
-----
启用 Patroni 与 `Citus <https://docs.citusdata.com>`__ 的集成。如果配置了该段，Patroni 将负责在 coordinator 上注册 Citus worker 节点。关于 Citus 支持的更多信息，请参阅 :ref:`here <citus>`。

-  **group**：Citus group id，整数。coordinator 使用 ``0``，workers 使用 ``1``、``2`` 等
-  **database**：应创建 ``citus`` 扩展的数据库。在 coordinator 和所有 workers 上必须相同。目前只支持一个数据库。

.. _consul_settings:

Consul
------
大多数参数都是可选的，但你必须在 **host** 或 **url** 中指定一个

-  **host**：Consul 本地 agent 的 host:port。
-  **url**：Consul 本地 agent 的 url，格式：http(s)://host:port。
-  **port**：（可选）Consul 端口。
-  **scheme**：（可选） **http** 或 **https**，默认为 **http**。
-  **token**：（可选）ACL token。
-  **verify**：（可选）是否验证 HTTPS 请求的 SSL 证书。
-  **cacert**：（可选）CA 证书。如果提供，将启用验证。
-  **cert**：（可选）包含客户端证书的文件。
-  **key**：（可选）包含客户端 key 的文件。如果 key 已包含在 **cert** 中，可以为空。
-  **dc**：（可选）要通信的数据中心。默认使用主机所在的数据中心。
-  **consistency**：（可选）选择 Consul 一致性模式。可选值为 ``default``、``consistent`` 或 ``stale`` （更多细节见 `consul API reference <https://www.consul.io/api/features/consistency.html/>`__）
-  **checks**：（可选）用于 session 的 Consul 健康检查列表。默认使用空列表。
-  **register\_service**：（可选）是否注册一个服务，服务名称由 scope 参数定义，tag 根据节点角色为 master、primary、replica 或 standby-leader。默认为 **false**。
-  **service\_tags**：（可选）除角色（``primary``/``replica``/``standby-leader``）之外，额外添加到 Consul 服务的静态 tags。默认使用空列表。
-  **service\_check\_interval**：（可选）对已注册 url 执行健康检查的频率。默认值为 '5s'。
-  **service\_check\_tls\_server\_name**：（可选）通过 TLS 连接时覆盖 SNI host，另请参见 `consul agent check API reference <https://www.consul.io/api-docs/agent/check#tlsservername>`__。

``token`` 需要具备以下 ACL 权限：

::

    service_prefix "${scope}" {
        policy = "write"
    }
    key_prefix "${namespace}/${scope}" {
        policy = "write"
    }
    session_prefix "" {
        policy = "write"
    }

Etcd
----
大多数参数都是可选的，但你必须在 **host**、**hosts**、**url**、**proxy** 或 **srv** 中指定一个

-  **host**：etcd 端点的 host:port。
-  **hosts**：etcd 端点列表，格式为 host1:port1,host2:port2 等。可以是逗号分隔的字符串，也可以是 yaml 列表。
-  **use\_proxies**：如果此参数设置为 true，Patroni 将把 **hosts** 视为代理列表，并且不会对 etcd 集群执行拓扑发现。
-  **url**：etcd 的 url。
-  **proxy**：etcd 的代理 url。如果你通过代理连接 etcd，请使用此参数而不是 **url**。
-  **srv**：用于集群自动发现的 SRV 记录搜索域名。Patroni 将按以下顺序查询指定域名的 SRV 服务名称（直到第一次成功为止）：``_etcd-client-ssl``、``_etcd-client``、``_etcd-ssl``、``_etcd``、``_etcd-server-ssl``、``_etcd-server``。如果获取到 ``_etcd-server-ssl`` 或 ``_etcd-server`` 的 SRV 记录，则使用 ETCD peer 协议向 ETCD 查询可用成员。否则，将使用 SRV 记录中的 hosts。
-  **srv\_suffix**：为发现过程中查询的 SRV 名称配置后缀。使用此选项来区分同一域名下的多个 etcd 集群。仅与 **srv** 配合使用。例如，如果设置了 ``srv_suffix: foo`` 和 ``srv: example.org``，将发起以下 DNS SRV 查询：``_etcd-client-ssl-foo._tcp.example.com`` （每个可能的 ETCD SRV 服务名称以此类推）。
-  **protocol**：（可选）http 或 https，如果未指定则使用 http。如果指定了 **url** 或 **proxy**，将从它们中获取协议。
-  **username**：（可选）etcd 认证的用户名。
-  **password**：（可选）etcd 认证的密码。
-  **cacert**：（可选）CA 证书。如果提供，将启用验证。
-  **cert**：（可选）包含客户端证书的文件。
-  **key**：（可选）包含客户端 key 的文件。如果 key 已包含在 **cert** 中，可以为空。

Etcdv3
------
如果你希望 Patroni 通过协议版本 3 与 Etcd 集群协作，你需要在 Patroni 配置文件中使用 ``etcd3`` 配置段。所有配置参数与 ``etcd`` 相同。

.. warning::
    使用协议版本 2 创建的 keys 在协议版本 3 下不可见，反之亦然，因此仅通过更新 Patroni 配置文件无法从 ``etcd`` 切换到 ``etcd3``。此外，Patroni 使用 Etcd 的 gRPC-gateway（代理）与 V3 API 通信，这意味着无法使用 TLS common name 认证。


ZooKeeper
----------
-  **hosts**：ZooKeeper 集群成员列表，格式：['host1:port1', 'host2:port2', 'etc...']。
-  **use_ssl**：（可选）是否使用 SSL。默认为 ``false``。如果设置为 ``false``，所有 SSL 特定参数都将被忽略。
-  **cacert**：（可选）CA 证书。如果提供，将启用验证。
-  **cert**：（可选）包含客户端证书的文件。
-  **key**：（可选）包含客户端 key 的文件。
-  **key_password**：（可选）客户端 key 的密码。
-  **verify**：（可选）是否验证证书。默认为 ``true``。
-  **set_acls**：（可选）如果设置，配置 Kazoo 为它创建的每个 ZNode 应用默认 ACL。ACL 将采用 'x509' schema，并应以字典形式指定，其中 principal 为 key，一个或多个权限组成的列表为 value。权限可以是 ``CREATE``、``READ``、``WRITE``、``DELETE`` 或 ``ADMIN`` 之一。例如，``set_acls: {CN=principal1: [CREATE, READ], CN=principal2: [ALL]}``。
-  **auth_data**：（可选）连接时使用的认证凭据。应为字典形式，`scheme` 为 key，`credential` 为 value。默认为空字典。

.. note::
    必须安装 ``kazoo>=2.6.0`` 才能支持 SSL。


Exhibitor
---------
-  **hosts**：Exhibitor（ZooKeeper）节点的初始列表，格式：'host1,host2,etc...'。每当 Exhibitor（ZooKeeper）集群拓扑发生变化时，此列表会自动更新。
-  **poll\_interval**：从 Exhibitor 更新 ZooKeeper 和 Exhibitor 节点列表的频率。
-  **port**：Exhibitor 端口。

.. _kubernetes_settings:

Kubernetes
----------
-  **bypass\_api\_service**：（可选）与 Kubernetes API 通信时，Patroni 通常依赖 `kubernetes` 服务，该服务的地址通过 `KUBERNETES_SERVICE_HOST` 环境变量暴露在 Pod 中。如果 `bypass_api_service` 设置为 ``true``，Patroni 将解析该服务后面的 API 节点列表并直接连接它们。
-  **namespace**：（可选）Patroni Pod 运行的 Kubernetes namespace。默认值为 `default`。
-  **labels**：格式为 ``{label1: value1, label2: value2}`` 的 labels。这些 labels 将用于查找与当前集群关联的现有对象（Pods 以及 Endpoints 或 ConfigMaps）。Patroni 也会在它创建的每个对象（Endpoint 或 ConfigMap）上设置这些 labels。
-  **scope\_label**：（可选）包含集群名称的 label 的名称。默认值为 `cluster-name`。
-  **bootstrap\_labels**：（可选）格式为 ``{label1: value1, label2: value2}`` 的 labels。当 Patroni Pod 的状态为 ``initializing new cluster``、``running custom bootstrap script``、``starting after custom bootstrap`` 或 ``creating replica`` 时，这些 labels 将被赋予该 Pod。
-  **role\_label**：（可选）包含角色（`primary`、`replica` 或其他自定义值）的 label 的名称。Patroni 会在其运行的 Pod 上设置此 label。默认值为 ``role``。
-  **leader\_label\_value**：（可选）当 Postgres 角色为 ``primary`` 时 Pod label 的值。默认值为 ``primary``。
-  **follower\_label\_value**：（可选）当 Postgres 角色为 ``replica`` 时 Pod label 的值。默认值为 ``replica``。
-  **standby\_leader\_label\_value**：（可选）当 Postgres 角色为 ``standby_leader`` 时 Pod label 的值。默认值为 ``primary``。
-  **tmp\_role\_label**：（可选）包含角色（`primary` 或 `replica`）的临时 label 的名称。此 label 的值始终使用相应角色的默认值。仅在必要时设置。
-  **use\_endpoints**：（可选）如果设置为 true，Patroni 将使用 Endpoints 而不是 ConfigMaps 来进行 leader 选举和保存集群状态。
-  **pod\_ip**：（可选）Patroni 所在 Pod 的 IP 地址。当 `use_endpoints` 启用时该值必需，用于在 Pod 的 PostgreSQL 被提升时填充 leader endpoint 的 subsets。
-  **ports**：（可选）如果 Service 对象为端口定义了名称，则 Endpoint 对象中必须出现相同的名称，否则服务将无法工作。例如，如果你的服务定义为 ``{Kind: Service, spec: {ports: [{name: postgresql, port: 5432, targetPort: 5432}]}}``，那么你必须设置 ``kubernetes.ports: [{"name": "postgresql", "port": 5432}]``，Patroni 将使用它来更新 leader Endpoint 的 subsets。此参数仅在设置了 `kubernetes.use_endpoints` 时使用。
-  **cacert**：（可选）指定包含 CA_BUNDLE 的文件，即在验证 Kubernetes API SSL 证书时使用的受信任 CA 证书。如果未提供，patroni 将使用 ServiceAccount secret 提供的值。
-  **retriable\_http\_codes**：（可选）K8s API 返回的、需要重试的 HTTP 状态码列表。默认情况下，Patroni 会在 ``500``、``503``、``504`` 上重试，或者在 K8s API 响应包含 ``retry-after`` HTTP 头时重试。


.. _raft_settings:

Raft（已弃用）
-----------------
-  **self\_addr**：用于监听 Raft 连接的 ``ip:port``。``self_addr`` 必须能被集群中的其他节点访问。如果未设置，该节点将不参与共识（consensus）。
-  **bind\_addr**：（可选）用于监听 Raft 连接的 ``ip:port``。如果未指定，将使用 ``self_addr``。
-  **partner\_addrs**：集群中其他 Patroni 节点的列表，格式：['ip1:port', 'ip2:port', 'etc...']
-  **data\_dir**：存放 Raft 日志和快照的目录。如果未指定，则使用当前工作目录。
-  **password**：（可选）使用指定密码加密 Raft 流量，需要 ``cryptography`` python 模块。

   关于 Raft 实现的简短 FAQ

   - Q：如何列出所有提供共识的节点？

     A：``syncobj_admin -conn host:port -status``，其中 host:port 是某个集群节点的地址

   - Q：曾经参与共识的节点已经消失，我无法将同一个 IP 复用于其他节点。如何将该节点从共识中移除？

     A：``syncobj_admin -conn host:port -remove host2:port2``，其中 ``host2:port2`` 是你要从共识中移除的节点的地址。

   - Q：从哪里获取 ``syncobj_admin`` 工具？

     A：它与 ``pysyncobj`` 模块（python RAFT 实现）一起安装，该模块是 Patroni 的依赖项。

   - Q：可以运行一个不加入共识的 Patroni 节点吗？

     A：可以，只需注释掉或删除 Patroni 配置中的 ``raft.self_addr``。

   - Q：可以只在两个节点上运行 Patroni 和 PostgreSQL 吗？

     A：可以，在第三个节点上你可以运行 ``patroni_raft_controller`` （不需要 Patroni 和 PostgreSQL）。在这种配置下，可以临时失去一个节点而不影响 primary。


.. _postgresql_settings:

PostgreSQL
----------
-  **postgresql**:

   -  **authentication**:

      -  **superuser**：

         -  **username**：超级用户的名称，在初始化（initdb）时设置，之后 Patroni 用它来连接 postgres。
         -  **password**：超级用户的密码，在初始化（initdb）时设置。
         -  **sslmode**：（可选）对应 `sslmode <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLMODE>`__ 连接参数，它允许客户端指定与服务器的 TLS 协商模式类型。有关每种模式的工作方式的更多信息，请访问 `PostgreSQL documentation <https://www.postgresql.org/docs/current/libpq-ssl.html#LIBPQ-SSL-SSLMODE-STATEMENTS>`__。默认模式为 ``prefer``。
         -  **sslkey**：（可选）对应 `sslkey <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLKEY>`__ 连接参数，它指定与客户端证书配合使用的密钥的位置。
         -  **sslpassword**：（可选）对应 `sslpassword <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLPASSWORD>`__ 连接参数，它指定 ``sslkey`` 中指定的密钥的密码。
         -  **sslcert**：（可选）对应 `sslcert <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLCERT>`__ 连接参数，它指定客户端证书的位置。
         -  **sslrootcert**：（可选）对应 `sslrootcert <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLROOTCERT>`__ 连接参数，它指定包含一个或多个证书颁发机构（CA）证书的文件的位置，客户端将使用这些证书来验证服务器的证书。
         -  **sslcrl**：（可选）对应 `sslcrl <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLCRL>`__ 连接参数，它指定包含证书吊销列表的文件的位置。如果服务器使用的证书出现在此列表中，客户端将拒绝与其连接。
         -  **sslcrldir**：（可选）对应 `sslcrldir <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLCRLDIR>`__ 连接参数，它指定包含证书吊销列表文件的目录的位置。如果服务器使用的证书出现在此列表中，客户端将拒绝与其连接。
         -  **sslnegotiation**：（可选）对应 `sslnegotiation <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLNEGOTIATION>`__ 连接参数，它控制如果使用 SSL 时如何与服务器协商 SSL 加密。
         -  **gssencmode**：（可选）对应 `gssencmode <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-GSSENCMODE>`__ 连接参数，它决定是否以及以何种优先级与服务器协商安全的 GSS TCP/IP 连接。
         -  **channel_binding**：（可选）对应 `channel_binding <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-CHANNEL-BINDING>`__ 连接参数，它控制客户端对 channel binding 的使用。
      -  **replication**：

         -  **username**：复制用户名；该用户将在初始化期间创建。Replicas 将使用此用户通过流式复制访问复制源
         -  **password**：复制密码；该用户将在初始化期间创建。
         -  **sslmode**：（可选）对应 `sslmode <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLMODE>`__ 连接参数，它允许客户端指定与服务器的 TLS 协商模式类型。有关每种模式的工作方式的更多信息，请访问 `PostgreSQL documentation <https://www.postgresql.org/docs/current/libpq-ssl.html#LIBPQ-SSL-SSLMODE-STATEMENTS>`__。默认模式为 ``prefer``。
         -  **sslkey**：（可选）对应 `sslkey <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLKEY>`__ 连接参数，它指定与客户端证书配合使用的密钥的位置。
         -  **sslpassword**：（可选）对应 `sslpassword <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLPASSWORD>`__ 连接参数，它指定 ``sslkey`` 中指定的密钥的密码。
         -  **sslcert**：（可选）对应 `sslcert <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLCERT>`__ 连接参数，它指定客户端证书的位置。
         -  **sslrootcert**：（可选）对应 `sslrootcert <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLROOTCERT>`__ 连接参数，它指定包含一个或多个证书颁发机构（CA）证书的文件的位置，客户端将使用这些证书来验证服务器的证书。
         -  **sslcrl**：（可选）对应 `sslcrl <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLCRL>`__ 连接参数，它指定包含证书吊销列表的文件的位置。如果服务器使用的证书出现在此列表中，客户端将拒绝与其连接。
         -  **sslcrldir**：（可选）对应 `sslcrldir <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLCRLDIR>`__ 连接参数，它指定包含证书吊销列表文件的目录的位置。如果服务器使用的证书出现在此列表中，客户端将拒绝与其连接。
         -  **sslnegotiation**：（可选）对应 `sslnegotiation <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLNEGOTIATION>`__ 连接参数，它控制如果使用 SSL 时如何与服务器协商 SSL 加密。
         -  **gssencmode**：（可选）对应 `gssencmode <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-GSSENCMODE>`__ 连接参数，它决定是否以及以何种优先级与服务器协商安全的 GSS TCP/IP 连接。
         -  **channel_binding**：（可选）对应 `channel_binding <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-CHANNEL-BINDING>`__ 连接参数，它控制客户端对 channel binding 的使用。
      -  **rewind**：

         -  **username**：（可选） ``pg_rewind`` 使用的用户名；该用户将在 postgres 11+ 初始化期间创建，并授予所有必要的 `permissions <https://www.postgresql.org/docs/11/app-pgrewind.html#id-1.9.5.8.8>`__。
         -  **password**：（可选） ``pg_rewind`` 使用的用户密码；该用户将在初始化期间创建。
         -  **sslmode**：（可选）对应 `sslmode <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLMODE>`__ 连接参数，它允许客户端指定与服务器的 TLS 协商模式类型。有关每种模式的工作方式的更多信息，请访问 `PostgreSQL documentation <https://www.postgresql.org/docs/current/libpq-ssl.html#LIBPQ-SSL-SSLMODE-STATEMENTS>`__。默认模式为 ``prefer``。
         -  **sslkey**：（可选）对应 `sslkey <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLKEY>`__ 连接参数，它指定与客户端证书配合使用的密钥的位置。
         -  **sslpassword**：（可选）对应 `sslpassword <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLPASSWORD>`__ 连接参数，它指定 ``sslkey`` 中指定的密钥的密码。
         -  **sslcert**：（可选）对应 `sslcert <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLCERT>`__ 连接参数，它指定客户端证书的位置。
         -  **sslrootcert**：（可选）对应 `sslrootcert <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLROOTCERT>`__ 连接参数，它指定包含一个或多个证书颁发机构（CA）证书的文件的位置，客户端将使用这些证书来验证服务器的证书。
         -  **sslcrl**：（可选）对应 `sslcrl <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLCRL>`__ 连接参数，它指定包含证书吊销列表的文件的位置。如果服务器使用的证书出现在此列表中，客户端将拒绝与其连接。
         -  **sslcrldir**：（可选）对应 `sslcrldir <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLCRLDIR>`__ 连接参数，它指定包含证书吊销列表文件的目录的位置。如果服务器使用的证书出现在此列表中，客户端将拒绝与其连接。
         -  **sslnegotiation**：（可选）对应 `sslnegotiation <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLNEGOTIATION>`__ 连接参数，它控制如果使用 SSL 时如何与服务器协商 SSL 加密。
         -  **gssencmode**：（可选）对应 `gssencmode <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-GSSENCMODE>`__ 连接参数，它决定是否以及以何种优先级与服务器协商安全的 GSS TCP/IP 连接。
         -  **channel_binding**：（可选）对应 `channel_binding <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-CHANNEL-BINDING>`__ 连接参数，它控制客户端对 channel binding 的使用。

   -  **callbacks**：在特定操作时运行的回调脚本。Patroni 会传入操作名称、角色和集群名称。（以 scripts/aws.py 为例，了解如何编写它们。）

      -  **on\_reload**：当触发配置重载时运行此脚本。
      -  **on\_restart**：当 postgres 重启时（角色不变）运行此脚本。
      -  **on\_role\_change**：当 postgres 被提升或降级时运行此脚本。
      -  **on\_start**：当 postgres 启动时运行此脚本。
      -  **on\_stop**：当 postgres 停止时运行此脚本。
   -  **connect\_address**：其他节点和应用程序访问 Postgres 所用的 IP 地址 + 端口。
   -  **proxy\_address**：与 Postgres 相邻运行的连接池（例如 pgbouncer）可访问的 IP 地址 + 端口。该值会以 ``proxy_url`` 的形式写入 DCS 中的成员 key，可用于服务发现。
   -  **create\_replica\_methods**：用于将 Patroni 节点变为新 replica 的创建方法的有序列表。
      「basebackup」是默认方法；其他方法被视为引用脚本，每个脚本都作为单独的
      配置项配置。更多说明请参阅 :ref:`custom replica creation methods documentation <custom_replica_creation>`。
   -  **data\_dir**：Postgres 数据目录的位置，可以是 :ref:`existing <existing_data>` 目录，也可以由 Patroni 初始化。
   -  **config\_dir**：Postgres 配置目录的位置，默认为数据目录。必须可由 Patroni 写入。
   -  **bin\_dir**：（可选）PostgreSQL 二进制文件（pg_ctl、initdb、pg_controldata、pg_basebackup、postgres、pg_isready、pg_rewind）的路径。如果未提供或为空字符串，将使用 PATH 环境变量来查找可执行文件。
   -  **bin\_name**：（可选）允许覆盖 Postgres 二进制文件名，适用于你使用自定义 Postgres 发行版的情况：

      - **pg\_ctl**：（可选） ``pg_ctl`` 二进制文件的自定义名称。
      - **initdb**：（可选） ``initdb`` 二进制文件的自定义名称。
      - **pg\controldata**：（可选） ``pg_controldata`` 二进制文件的自定义名称。
      - **pg\_basebackup**：（可选） ``pg_basebackup`` 二进制文件的自定义名称。
      - **postgres**：（可选） ``postgres`` 二进制文件的自定义名称。
      - **pg\_isready**：（可选） ``pg_isready`` 二进制文件的自定义名称。
      - **pg\_rewind**：（可选） ``pg_rewind`` 二进制文件的自定义名称。
   -  **listen**：Postgres 监听的 IP 地址 + 端口；如果使用流式复制，集群中的其他节点必须能够访问该地址。允许使用多个以逗号分隔的地址，前提是端口部分以冒号追加在最后一个地址之后，例如 ``listen: 127.0.0.1,127.0.0.2:5432``。Patroni 将使用此列表中的第一个地址与 PostgreSQL 节点建立本地连接。
   -  **use\_unix\_socket**：指定 Patroni 应优先使用 unix socket 连接集群。默认值为 ``false``。如果定义了 ``unix_socket_directories``，Patroni 将使用其中的第一个合适值连接集群，如果没有合适的值则回退到 tcp。如果在 ``postgresql.parameters`` 中未指定 ``unix_socket_directories``，Patroni 将假定应使用默认值，并从连接参数中省略 ``host``。
   -  **use\_unix\_socket\_repl**：指定 Patroni 应优先使用 unix socket 进行复制用户的集群连接。默认值为 ``false``。如果定义了 ``unix_socket_directories``，Patroni 将使用其中的第一个合适值连接集群，如果没有合适的值则回退到 tcp。如果在 ``postgresql.parameters`` 中未指定 ``unix_socket_directories``，Patroni 将假定应使用默认值，并从连接参数中省略 ``host``。
   -  **pgpass**：`.pgpass <https://www.postgresql.org/docs/current/static/libpq-pgpass.html>`__ 密码文件的路径。Patroni 会在执行 pg\_basebackup、post_init 脚本以及其他一些情况下创建此文件。该位置必须可由 Patroni 写入。
   -  **recovery\_conf**：配置 follower 时写入 recovery.conf 的附加配置设置。
   -  **custom\_conf**：可选的自定义 ``postgresql.conf`` 文件的路径，该文件将替代 ``postgresql.base.conf`` 使用。该文件必须存在于所有集群节点上，PostgreSQL 必须可读，并会从其在真实 ``postgresql.conf`` 中的位置被包含。请注意，Patroni 不会监控此文件的更改，也不会备份它。不过，其设置仍可被 Patroni 自身的配置机制覆盖 —— 详见 :ref:`dynamic configuration <patroni_configuration>`。
   -  **parameters**：Postgres 的配置参数（GUCs），格式为 ``{ssl: "on", ssl_cert_file: "cert_file"}``。
   -  **pg\_hba**：Patroni 用来生成 ``pg_hba.conf`` 的行列表。如果 PostgreSQL 参数 ``hba_file`` 被设置为非默认值，Patroni 将忽略此参数。与 :ref:`dynamic configuration <dynamic_configuration>` 一起使用时，此参数简化了 ``pg_hba.conf`` 的管理。

      -  **- host all all 0.0.0.0/0 md5**
      -  **- host replication replicator 127.0.0.1/32 md5**：复制需要类似这样的行。
   -  **pg\_ident**：Patroni 用来生成 ``pg_ident.conf`` 的行列表。如果 PostgreSQL 参数 ``ident_file`` 被设置为非默认值，Patroni 将忽略此参数。与 :ref:`dynamic configuration <dynamic_configuration>` 一起使用时，此参数简化了 ``pg_ident.conf`` 的管理。

      -  **- mapname1 systemname1 pguser1**
      -  **- mapname1 systemname2 pguser2**
   -  **pg\_ctl\_timeout**：pg_ctl 在执行 ``start``、``stop`` 或 ``restart`` 时应等待多长时间。默认值为 60 秒。
   -  **use\_pg\_rewind**：尝试对以 replica 身份加入集群的原 leader 使用 pg\_rewind。集群必须使用 ``data page checksums``（``initdb`` 的 ``--data-checksums`` 选项）初始化，和/或将 ``wal_log_hints`` 设置为 ``on``，否则 ``pg_rewind`` 将无法工作。
   -  **remove\_data\_directory\_on\_rewind\_failure**：如果启用此选项，Patroni 将删除 PostgreSQL 数据目录并重新创建 replica。否则它将尝试跟随新的 leader。默认值为 **false**。
   -  **remove\_data\_directory\_on\_diverged\_timelines**：如果 Patroni 发现 timeline 发生分歧，且原 primary 无法从新 primary 开始流式复制，它将删除 PostgreSQL 数据目录并重新创建 replica。当无法使用 ``pg_rewind`` 时，此选项非常有用。在 PostgreSQL v10 及更早版本上执行 timeline 分歧检查时，Patroni 将尝试使用复制凭据连接到「postgres」数据库。因此，应允许在 pg_hba.conf 中放行此类访问。默认值为 **false**。
   -  **replica\_method**：对于除 basebackup 之外的每个 create_replica_methods，你需要添加一个同名的配置段。至少应包含「command」，即要执行的实际脚本的完整路径。其他配置参数将以「parameter=value」的形式传递给脚本。
   -  **pre\_promote**：在 failover 期间，获取 leader 锁之后、提升 replica 之前执行的 fencing 脚本。如果脚本以非零退出码退出，Patroni 将不提升该 replica，并从 DCS 中移除 leader key。
   -  **before\_stop**：在停止 postgres 之前立即执行的脚本。与回调不同，此脚本同步运行，会阻塞关闭直到执行完成。此脚本的返回码不会影响之后是否继续关闭。

.. _restapi_settings:

REST API
--------
-  **restapi**:

   -  **thread\_pool\_size**：Patroni 用于处理 REST API 请求的线程池大小。最小值为 ``5``，默认值为 ``5``。
   -  **connect\_address**：访问 Patroni 的 :ref:`REST API <rest_api>` 的 IP 地址（或主机名）和端口。集群的所有成员都必须能够连接到此地址，因此除非 Patroni 的部署仅用于 localhost 内的演示，否则此地址不能是 "localhost" 或环回地址（即 "localhost" 或 "127.0.0.1"）。它可以作为 HTTP 健康检查的端点（请参阅下面关于 "listen" REST API 参数的说明），也可以用于用户查询（直接或通过 REST API），以及集群成员在 leader 选举期间执行的健康检查（例如，判断 leader 是否仍在运行，或者是否存在 WAL 位置领先于发起查询节点的节点等）。connect_address 会被写入 DCS 中的成员 key，从而可以将成员名称解析为连接其 REST API 的地址。
   -  **listen**：Patroni 监听 REST API 的 IP 地址（或主机名）和端口 —— 同时用于提供上述参与节点之间的健康检查和集群消息传递，以及为 HAProxy（或其他任何支持 HTTP "OPTION" 或 "GET" 检查的负载均衡器）提供健康检查信息。
   -  **authentication**：（可选）

      -  **username**：用于保护不安全 REST API 端点的 Basic-auth 用户名。
      -  **password**：用于保护不安全 REST API 端点的 Basic-auth 密码。
   -  **certfile**：（可选）指定 PEM 格式证书的文件。如果未指定或留空 certfile，API server 将在不使用 SSL 的情况下工作。
   -  **keyfile**：（可选）指定 PEM 格式密钥的文件。
   -  **keyfile\_password**：（可选）指定用于解密 keyfile 的密码。
   -  **cafile**：（可选）指定包含 CA_BUNDLE 的文件，即在验证客户端证书时使用的受信任 CA 证书。
   -  **ciphers**：（可选）指定允许的加密套件（例如 "ECDHE-RSA-AES256-GCM-SHA384:DHE-RSA-AES256-GCM-SHA384:ECDHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES128-GCM-SHA256:!SSLv1:!SSLv2:!SSLv3:!TLSv1:!TLSv1.1"）
   -  **verify\_client**：（可选） ``none`` （默认）、``optional`` 或 ``required``。当为 ``none`` 时，REST API 不检查客户端证书。当为 ``required`` 时，所有 REST API 调用都需要客户端证书。当为 ``optional`` 时，所有不安全的 REST API 端点都需要客户端证书。当使用 ``required`` 时，如果证书签名验证成功，客户端认证即成功。对于 ``optional``，客户端证书只会在 ``PUT``、``POST``、``PATCH`` 和 ``DELETE`` 请求时被检查。
   -  **allowlist**：（可选）指定允许调用不安全 REST API 端点的主机集合。单个元素可以是主机名、IP 地址或使用 CIDR 记法的网络地址。默认情况下使用 ``allow all``。如果设置了 ``allowlist`` 或 ``allowlist_include_members``，任何未包含在内的请求都会被拒绝。
   -  **allowlist\_include\_members**：（可选）如果设置为 ``true``，则允许从注册在 DCS 中的其他集群成员访问不安全的 REST API 端点（IP 地址或主机名取自成员的 ``api_url``）。请注意，操作系统可能会为出站连接使用不同的 IP。
   -  **http\_extra\_headers**：（可选）HTTP 头允许 REST API server 通过 HTTP 响应传递附加信息。
   -  **https\_extra\_headers**：（可选）启用 TLS 时，HTTPS 头允许 REST API server 通过 HTTP 响应传递附加信息。这也会传递 ``http_extra_headers`` 中设置的附加信息。
   -  **request_queue_size**：（可选）设置 Patroni REST API 使用的 TCP socket 的请求队列大小。一旦队列已满，后续请求将收到 "Connection denied" 错误。默认值为 5。
   -  **server_tokens**：（可选）配置 ``Server`` HTTP 头的值。
      - ``Minimal``：该头只包含 Patroni 版本，例如 ``Patroni/4.0.0``。
      - ``ProductOnly``：该头只包含产品名称，例如 ``Patroni``。
      - ``Original`` （默认）：该头保持原始行为，显示 BaseHTTP 和 Python 版本，例如 ``BaseHTTP/0.6 Python/3.12.3``。

下面是 **http_extra_headers** 和 **https_extra_headers** 的示例：

.. code:: YAML

        restapi:
          listen: <listen>
          connect_address: <connect_address>
          authentication:
            username: <username>
            password: <password>
          http_extra_headers:
            'X-Frame-Options': 'SAMEORIGIN'
            'X-XSS-Protection': '1; mode=block'
            'X-Content-Type-Options': 'nosniff'
          cafile: <ca file>
          certfile: <cert>
          keyfile: <key>
          https_extra_headers:
            'Strict-Transport-Security': 'max-age=31536000; includeSubDomains'

.. warning::

    - 给定 Patroni 集群的所有节点都必须能够访问 ``restapi.connect_address``。Patroni 在内部会使用它，在 leader race 期间查找复制延迟最小的节点。
    - 如果你启用了客户端证书验证（``restapi.verify_client`` 设置为 ``required``），你还 **必须** 在 ``ctl.certfile``、``ctl.keyfile``、``ctl.keyfile_password`` 中提供 **有效的客户端证书**。如果不提供，Patroni 将无法正常工作。


.. _patronictl_settings:

CTL
---
-  **ctl**:（可选）

   -  **authentication**：

      -  **username**：用于访问受保护 REST API 端点的 Basic-auth 用户名。如果未提供，:ref:`patronictl` 将使用 REST API 的 "username" 参数值。
      -  **password**：用于访问受保护 REST API 端点的 Basic-auth 密码。如果未提供，:ref:`patronictl` 将使用 REST API 的 "password" 参数值。
   -  **insecure**：允许在未验证 SSL 证书的情况下连接 REST API。
   -  **cacert**：指定包含 CA_BUNDLE 的文件或目录，即在验证 REST API SSL 证书时使用的受信任 CA 证书。如果未提供，:ref:`patronictl` 将使用 REST API 的 "cafile" 参数值。
   -  **certfile**：指定 PEM 格式的客户端证书文件。
   -  **keyfile**：指定 PEM 格式的客户端密钥文件。
   -  **keyfile\_password**：指定用于解密客户端 keyfile 的密码。

Watchdog
--------
-  **mode**：``off``、``automatic`` 或 ``required``。当为 ``off`` 时，watchdog 被禁用。当为 ``automatic`` 时，如果可用则使用 watchdog，不可用则忽略。当为 ``required`` 时，除非 watchdog 能成功启用，否则该节点不会成为 leader。
-  **device**：watchdog 设备的路径。默认为 ``/dev/watchdog``。
-  **safety_margin**：watchdog 触发与 leader key 过期之间的安全余量秒数。

.. _tags_settings:

Tags
----
-  **clonefrom**：``true`` 或 ``false``。如果设置为 ``true``，其他节点可能会优先使用此节点进行 bootstrap（从中获取 ``pg_basebackup``）。如果有多个节点的 ``clonefrom`` tag 设置为 ``true``，将随机选择 bootstrap 源节点。默认值为 ``false``。
-  **noloadbalance**：``true`` 或 ``false``。如果设置为 ``true``，该节点将对 ``GET /replica`` REST API 健康检查返回 HTTP 状态码 503，因此将被排除在负载均衡之外。默认为 ``false``。
-  **replicatefrom**：要从中复制的另一个 replica 的名称。用于支持级联复制。
-  **nosync**：``true`` 或 ``false``。如果设置为 ``true``，该节点永远不会被选为同步 replica。
-  **sync_priority**：整数，控制当 ``synchronous_mode`` 设置为 ``on`` 时，此节点在同步 replica 选择中应具有的优先级。优先级较高的节点将优先于优先级较低的节点。如果 ``sync_priority`` 为 0 或负数，则不允许将该节点写入 ``synchronous_standby_names`` PostgreSQL 参数（类似于 ``nosync: true``）。请注意，此参数与 ``pg_stat_replication`` 视图中报告的 ``sync_priority`` 值的含义相反。
-  **nofailover**：``true`` 或 ``false``，控制是否允许此节点参与 leader race 并成为 leader。默认为 ``false``，即此节点_可以_参与 leader race。
-  **failover_priority**：整数，控制此节点在 failover 期间应具有的优先级。如果节点接收/重放了相同数量的 WAL，则优先级较高的节点将优先于优先级较低的节点。不过，无论优先级如何，receive/replay LSN 值较高的节点都会被优先选择。如果 ``failover_priority`` 为 0 或负数，则不允许该节点参与 leader race 并成为 leader（类似于 ``nofailover: true``）。已知限制：``failover_priority`` 目前不适用于 :ref:`quorum-based synchronous replication <quorum_mode>`。
-  **nostream**：``true`` 或 ``false``。如果设置为 ``true``，该节点将不会使用复制协议流式复制 WAL。它将转而依赖归档恢复（如果配置了 ``restore_command``）和 ``pg_wal``/``pg_xlog`` 轮询。它还会禁用该节点自身及其所有级联 replica 上永久逻辑复制 slot 的复制和同步。在 primary 节点上设置此 tag 没有效果。

.. warning::
   只能提供 ``nofailover`` 或 ``failover_priority`` 之一。提供 ``nofailover: true`` 等同于 ``failover_priority: 0``，而提供 ``nofailover: false`` 将使节点获得优先级 1。

除了这些预定义的 tags，你还可以添加自定义的 tags：

-  **key1**：``true``
-  **key2**：``false``
-  **key3**：``1.4``
-  **key4**：``"RandomString"``

Tags 在 :ref:`REST API <rest_api>` 和 :ref:`patronictl_list` 中可见。你还可以使用这些 tags 检查实例的健康状况。如果某个实例未定义该 tag，或者相应的值与查询值不匹配，将返回 HTTP 状态码 503。
