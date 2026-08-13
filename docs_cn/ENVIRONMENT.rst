.. _environment:

环境配置设置
============

可以使用系统环境变量覆盖 Patroni 配置文件中定义的某些配置参数。本文档列出了 Patroni 处理的所有环境变量。通过这些变量设置的值始终优先于 Patroni 配置文件中设置的值。

全局/通用
---------
-  **PATRONI\_CONFIGURATION**\：可以通过 ``PATRONI_CONFIGURATION`` 环境变量为 Patroni 设置完整配置。在这种情况下，任何其他环境变量都将不会被考虑！
-  **PATRONI\_THREAD\_POOL\_SIZE**\：Patroni 用于执行异步任务，以及在 leader 竞争或 failsafe 检查期间通过 REST API 与其他成员通信的线程池大小。最小值为 ``5``\，默认值为 ``5``\。
-  **PATRONI\_THREAD\_STACK\_SIZE**\：指定 Patroni 启动的线程所使用的栈大小。该值必须按 ``64kB`` 对齐。最小值为 ``64kB``\，默认值（由 Patroni 设置）为 ``512kB``\。
-  **PATRONI\_NAME**\：当前运行的 Patroni 实例所在节点的名称。在集群中必须唯一。
-  **PATRONI\_NAMESPACE**\：Patroni 在配置存储中保存集群信息的路径。默认值：「/service」
-  **PATRONI\_SCOPE**\：集群名称
-  **PG\_MALLOC\_ARENA\_MAX**\：``postmaster`` 进程的 ``MALLOC_ARENA_MAX`` 环境变量的自定义值。如果未设置，``postmaster`` 将继承 ``MALLOC_ARENA_MAX`` 的值。

日志
----
-  **PATRONI\_LOG\_TYPE**\：设置日志格式。可以是 **plain** 或 **json**\。要使用 **json** 格式，您必须安装 :ref:`jsonlogger <extras>`。默认值为 **plain**\。
-  **PATRONI\_LOG\_LEVEL**\：设置常规日志级别。默认值为 **INFO** （参见 `Python 日志记录文档 <https://docs.python.org/3.6/library/logging.html#levels>`_）
-  **PATRONI\_LOG\_TRACEBACK\_LEVEL**\：设置 traceback 可见的级别。默认值为 **ERROR**\。如果您只希望在启用 **PATRONI\_LOG\_LEVEL=DEBUG** 时看到 traceback，请将其设置为 **DEBUG**\。
-  **PATRONI\_LOG\_FORMAT**\：设置日志格式字符串。如果日志类型为 **plain**\，日志格式应为字符串。
   可用属性请参阅 `LogRecord 属性 <https://docs.python.org/3.6/library/logging.html#logrecord-attributes>`_。
   如果日志类型为 **json**\，日志格式除了字符串之外还可以是列表。列表中的每个
   项应对应一个 LogRecord 属性。请注意，只需要字段名，并且应省略 **%(**
   和 **)**\。如果您希望以不同的键名打印某个日志字段，可以使用字典，其中
   字典键为日志字段，值为您希望在日志中打印的字段名称。
   默认值为 **%(asctime)s %(levelname)s: %(message)s**
-  **PATRONI\_LOG\_DATEFORMAT**\：设置日期时间格式字符串。（参见 `formatTime() 文档 <https://docs.python.org/3.6/library/logging.html#logging.Formatter.formatTime>`_）
-  **PATRONI\_LOG\_STATIC\_FIELDS**\：向日志添加额外字段。此选项仅在日志类型设置为 **json** 时可用。示例 ``PATRONI_LOG_STATIC_FIELDS="{app: patroni}"``
-  **PATRONI\_LOG\_MAX\_QUEUE\_SIZE**\：Patroni 使用两步日志记录。日志记录被写入内存队列，有一个单独的线程从队列中取出日志并写入 stderr 或文件。内部队列的最大大小默认限制为 **1000** 条记录，这足以保留过去 1 小时 20 分钟的日志。
-  **PATRONI\_LOG\_DIR**\：写入应用程序日志的目录。该目录必须存在，并且对执行 Patroni 的用户可写。如果您设置了此环境变量，应用程序默认将保留 4 个 25MB 的日志。您可以使用 `PATRONI_LOG_FILE_NUM` 和 `PATRONI_LOG_FILE_SIZE` 调整这些保留值（见下文）。
-  **PATRONI\_LOG\_MODE**\：日志文件的权限（例如 ``0644``\）。如果未指定，权限将根据当前的 umask 值设置。
-  **PATRONI\_LOG\_FILE\_NUM**\：要保留的应用程序日志数量。
-  **PATRONI\_LOG\_FILE\_SIZE**\：触发日志轮转的 patroni.log 文件大小（以字节为单位）。
-  **PATRONI\_LOG\_LOGGERS**\：按 python 模块重新定义日志级别。示例 ``PATRONI_LOG_LOGGERS="{patroni.postmaster: WARNING, urllib3: DEBUG}"``
-  **PATRONI\_LOG\_DEDUPLICATE\_HEARTBEAT\_LOGS**\：如果设置为 ``true``\，则不再输出连续且相同的心跳日志。默认值为 ``false``\。

.. warning::
   HA 循环的执行时间对于诊断因资源耗尽等原因引起的 failover 可能是非常有价值的信息。当 ``PATRONI_LOG_DEDUPLICATE_HEARTBEAT_LOGS`` 设置为 ``true`` 时，将不会为 HA 循环执行生成日志（除非 leader 发生变化），因此这些可能有用的信息将无法从日志中获取。

Citus
-----
启用 Patroni 与 `Citus <https://docs.citusdata.com>`__ 的集成。如果配置了，Patroni 将负责在 coordinator 上注册 Citus worker 节点。您可以在 :ref:`here <citus>` 找到有关 Citus 支持的更多信息。

-  **PATRONI\_CITUS\_GROUP**\：Citus 组 ID，整数。coordinator 使用 ``0``\，worker 使用 ``1``\、``2`` 等
-  **PATRONI\_CITUS\_DATABASE**\：应创建 ``citus`` 扩展的数据库。coordinator 和所有 worker 上必须相同。目前仅支持一个数据库。

Consul
------
-  **PATRONI\_CONSUL\_HOST**\：Consul 本地 agent 的 host:port。
-  **PATRONI\_CONSUL\_URL**\：Consul 本地 agent 的 url，格式：http(s)://host:port
-  **PATRONI\_CONSUL\_PORT**\：（可选）Consul 端口
-  **PATRONI\_CONSUL\_SCHEME**\：（可选） **http** 或 **https**\，默认为 **http**
-  **PATRONI\_CONSUL\_TOKEN**\：（可选）ACL token
-  **PATRONI\_CONSUL\_VERIFY**\：（可选）是否验证 HTTPS 请求的 SSL 证书
-  **PATRONI\_CONSUL\_CACERT**\：（可选）CA 证书。如果存在，将启用验证。
-  **PATRONI\_CONSUL\_CERT**\：（可选）包含客户端证书的文件
-  **PATRONI\_CONSUL\_KEY**\：（可选）包含客户端密钥的文件。如果密钥是证书的一部分，可以为空。
-  **PATRONI\_CONSUL\_DC**\：（可选）要通信的数据中心。默认使用主机所在的数据中心。
-  **PATRONI\_CONSUL\_CONSISTENCY**\：（可选）选择 consul 一致性模式。可能的值有 ``default``\、``consistent`` 或 ``stale`` （更多细节见 `consul API 参考 <https://www.consul.io/api/features/consistency.html/>`__）
-  **PATRONI\_CONSUL\_CHECKS**\：（可选）用于 session 的 Consul 健康检查列表。默认使用空列表。
-  **PATRONI\_CONSUL\_REGISTER\_SERVICE**\：（可选）是否注册一个服务，其名称由 scope 参数定义，标签为 master、primary、replica 或 standby-leader（取决于节点的角色）。默认为 **false**
-  **PATRONI\_CONSUL\_SERVICE\_TAGS**\：（可选）除角色（``primary``/``replica``/``standby-leader``\）之外，添加到 Consul 服务的额外静态标签。默认使用空列表。
-  **PATRONI\_CONSUL\_SERVICE\_CHECK\_INTERVAL**\：（可选）对注册的 url 执行健康检查的频率
-  **PATRONI\_CONSUL\_SERVICE\_CHECK\_TLS\_SERVER\_NAME**\：（可选）通过 TLS 连接时覆盖 SNI 主机，另请参见 `consul agent check API 参考 <https://www.consul.io/api-docs/agent/check#tlsservername>`__。

Etcd
----

-  **PATRONI\_ETCD\_PROXY**\：etcd 的代理 url。如果您通过代理连接 etcd，请使用此参数而不是 **PATRONI\_ETCD\_URL**
-  **PATRONI\_ETCD\_URL**\：etcd 的 url，格式：http(s)://(username:password@)host:port
-  **PATRONI\_ETCD\_HOSTS**\：etcd 端点列表，格式为 'host1:port1'、'host2:port2' 等
-  **PATRONI\_ETCD\_USE\_PROXIES**\：如果此参数设置为 true，Patroni 会将 **hosts** 视为代理列表，不会对 etcd 集群执行拓扑发现，而是坚持使用固定的 **hosts** 列表。
-  **PATRONI\_ETCD\_PROTOCOL**\：http 或 https，如果未指定则使用 http。如果指定了 **url** 或 **proxy**\，将从它们中获取协议。
-  **PATRONI\_ETCD\_HOST**\：etcd 端点的 host:port。
-  **PATRONI\_ETCD\_SRV**\：用于集群自动发现的、要搜索 SRV 记录的域名。Patroni 将尝试针对指定域名查询以下 SRV 服务名称（按此顺序，直到首次成功为止）：``_etcd-client-ssl``\、``_etcd-client``\、``_etcd-ssl``\、``_etcd``\、``_etcd-server-ssl``\、``_etcd-server``\。如果检索到 ``_etcd-server-ssl`` 或 ``_etcd-server`` 的 SRV 记录，则使用 ETCD peer 协议向 ETCD 查询可用成员。否则将使用 SRV 记录中的主机。
-  **PATRONI\_ETCD\_SRV\_SUFFIX**\：为发现过程中查询的 SRV 名称配置一个后缀。使用此标志可以区分同一域名下的多个 etcd 集群。仅与 **PATRONI\_ETCD\_SRV** 一起使用才有效。例如，如果设置了 ``PATRONI_ETCD_SRV_SUFFIX=foo`` 和 ``PATRONI_ETCD_SRV=example.org``\，将执行以下 DNS SRV 查询：``_etcd-client-ssl-foo._tcp.example.com`` （每个可能的 ETCD SRV 服务名称依次类推）。
-  **PATRONI\_ETCD\_USERNAME**\：etcd 认证的用户名。
-  **PATRONI\_ETCD\_PASSWORD**\：etcd 认证的密码。
-  **PATRONI\_ETCD\_CACERT**\：CA 证书。如果存在，将启用验证。
-  **PATRONI\_ETCD\_CERT**\：包含客户端证书的文件。
-  **PATRONI\_ETCD\_KEY**\：包含客户端密钥的文件。如果密钥是证书的一部分，可以为空。

Etcdv3
------
Etcdv3 的环境变量名称与 Etcd 类似，您只需在变量名中使用 ``ETCD3`` 代替 ``ETCD``\。示例：``PATRONI_ETCD3_HOST``\、``PATRONI_ETCD3_CACERT`` 等。

.. warning::
    使用协议版本 2 创建的键在协议版本 3 中不可见，反之亦然，因此仅通过更新 Patroni 配置无法从 Etcd 切换到 Etcdv3。此外，Patroni 使用 Etcd 的 gRPC-gateway（代理）与 V3 API 通信，这意味着无法使用 TLS 通用名称（common name）认证。


ZooKeeper
---------
-  **PATRONI\_ZOOKEEPER\_HOSTS**\：以逗号分隔的 ZooKeeper 集群成员列表："'host1:port1'、'host2:port2'、'etc...'"。务必将每个条目都用引号括起来！
-  **PATRONI\_ZOOKEEPER\_USE\_SSL**\：（可选）是否使用 SSL。默认为 ``false``\。如果设置为 ``false``\，所有 SSL 特定参数都将被忽略。
-  **PATRONI\_ZOOKEEPER\_CACERT**\：（可选）CA 证书。如果存在，将启用验证。
-  **PATRONI\_ZOOKEEPER\_CERT**\：（可选）包含客户端证书的文件。
-  **PATRONI\_ZOOKEEPER\_KEY**\：（可选）包含客户端密钥的文件。
-  **PATRONI\_ZOOKEEPER\_KEY\_PASSWORD**\：（可选）客户端密钥密码。
-  **PATRONI\_ZOOKEEPER\_VERIFY**\：（可选）是否验证证书。默认为 ``true``\。
-  **PATRONI\_ZOOKEEPER\_SET\_ACLS**\：（可选）如果设置，则配置 Kazoo 为其创建的每个 ZNode 应用默认 ACL。ACL 将采用 'x509' 模式，并应指定为一个字典，其中 principal 为键，值中一个或多个权限为列表。权限可以是 ``CREATE``\、``READ``\、``WRITE``\、``DELETE`` 或 ``ADMIN`` 之一。例如，``set_acls: {CN=principal1: [CREATE, READ], CN=principal2: [ALL]}``\。
-  **PATRONI\_ZOOKEEPER\_AUTH\_DATA**\：（可选）用于连接的身份认证凭据。应为字典形式，其中 `scheme` 为键，`credential` 为值。默认为空字典。

.. note::
    要支持 SSL，必须安装 ``kazoo>=2.6.0``\。


Exhibitor
---------
-  **PATRONI\_EXHIBITOR\_HOSTS**\：Exhibitor（ZooKeeper）节点的初始列表，格式：'host1,host2,etc...'。每当 Exhibitor（ZooKeeper）集群拓扑发生变化时，此列表会自动更新。
-  **PATRONI\_EXHIBITOR\_PORT**\：Exhibitor 端口。

.. _kubernetes_environment:

Kubernetes
----------
-  **PATRONI\_KUBERNETES\_BYPASS\_API\_SERVICE**\：（可选）与 Kubernetes API 通信时，Patroni 通常依赖 `kubernetes` 服务，其地址通过 `KUBERNETES_SERVICE_HOST` 环境变量暴露在 pod 中。如果 `PATRONI_KUBERNETES_BYPASS_API_SERVICE` 设置为 ``true``\，Patroni 将解析该服务后面的 API 节点列表并直接连接它们。
-  **PATRONI\_KUBERNETES\_NAMESPACE**\：（可选）Patroni pod 运行所在的 Kubernetes namespace。默认值为 `default`。
-  **PATRONI\_KUBERNETES\_LABELS**\：格式为 ``{label1: value1, label2: value2}`` 的标签。这些标签将用于查找与当前集群关联的现有对象（Pod 以及 Endpoints 或 ConfigMaps）。此外，Patroni 会在它创建的每个对象（Endpoint 或 ConfigMap）上设置这些标签。
-  **PATRONI\_KUBERNETES\_SCOPE\_LABEL**\：（可选）包含集群名称的标签名称。默认值为 `cluster-name`。
-  **PATRONI\_KUBERNETES\_BOOTSTRAP\_LABELS**\：（可选）格式为 ``{label1: value1, label2: value2}`` 的标签。当 Patroni pod 的状态为 ``initializing new cluster``\、``running custom bootstrap script``\、``starting after custom bootstrap`` 或 ``creating replica`` 时，这些标签将被分配给该 pod。
-  **PATRONI\_KUBERNETES\_ROLE\_LABEL**\：（可选）包含角色（`primary`、`replica` 或其他自定义值）的标签名称。Patroni 会在其运行的 pod 上设置此标签。默认值为 ``role``\。
-  **PATRONI\_KUBERNETES\_LEADER\_LABEL\_VALUE**\：（可选）当 Postgres 角色为 `primary` 时的 pod 标签值。默认值为 `primary`。
-  **PATRONI\_KUBERNETES\_FOLLOWER\_LABEL\_VALUE**\：（可选）当 Postgres 角色为 `replica` 时的 pod 标签值。默认值为 `replica`。
-  **PATRONI\_KUBERNETES\_STANDBY\_LEADER\_LABEL\_VALUE**\：（可选）当 Postgres 角色为 ``standby_leader`` 时的 pod 标签值。默认值为 ``primary``\。
-  **PATRONI\_KUBERNETES\_TMP\_ROLE\_LABEL**\：（可选）包含角色（`primary` 或 `replica`）的临时标签名称。此标签的值始终使用相应角色的默认值。仅在必要时设置。
-  **PATRONI\_KUBERNETES\_USE\_ENDPOINTS**\：（可选）如果设置为 true，Patroni 将使用 Endpoints 而不是 ConfigMaps 来进行 leader 选举和维护集群状态。
-  **PATRONI\_KUBERNETES\_POD\_IP**\：（可选）Patroni 运行所在的 pod 的 IP 地址。当启用 `PATRONI_KUBERNETES_USE_ENDPOINTS` 时需要此值，并且当 pod 的 PostgreSQL 被提升时，用它来填充 leader endpoint 的 subsets。
-  **PATRONI\_KUBERNETES\_PORTS**\：（可选）如果 Service 对象具有端口名称，则 Endpoint 对象中必须出现相同的名称，否则 service 将无法工作。例如，如果您的 service 定义为 ``{Kind: Service, spec: {ports: [{name: postgresql, port: 5432, targetPort: 5432}]}}``\，那么您必须设置 ``PATRONI_KUBERNETES_PORTS='[{"name": "postgresql", "port": 5432}]'``\，Patroni 将使用它来更新 leader Endpoint 的 subsets。仅当设置了 `PATRONI_KUBERNETES_USE_ENDPOINTS` 时才会使用此参数。
-  **PATRONI\_KUBERNETES\_CACERT**\：（可选）指定包含 CA_BUNDLE 的文件，其中包含在验证 Kubernetes API SSL 证书时使用的可信 CA 证书。如果未提供，patroni 将使用 ServiceAccount secret 提供的值。
-  **PATRONI\_RETRIABLE\_HTTP\_CODES**\：（可选）来自 K8s API 的需要重试的 HTTP 状态码列表。默认情况下，Patroni 会在 ``500``\、``503`` 和 ``504`` 时重试，或者当 K8s API 响应带有 ``retry-after`` HTTP 头时重试。

Raft（已弃用）
--------------

-  **PATRONI\_RAFT\_SELF\_ADDR**\：Raft 连接监听的 ``ip:port``\。``self_addr`` 必须能被集群中的其他节点访问。如果未设置，该节点将不参与一致性协商。
-  **PATRONI\_RAFT\_BIND\_ADDR**\：（可选）Raft 连接监听的 ``ip:port``\。如果未指定，将使用 ``self_addr``\。
-  **PATRONI\_RAFT\_PARTNER\_ADDRS**\：集群中其他 Patroni 节点的列表，格式为 ``"'ip1:port1','ip2:port2'"``\。务必将每个条目都用引号括起来！
-  **PATRONI\_RAFT\_DATA\_DIR**\：存储 Raft 日志和快照的目录。如果未指定，将使用当前工作目录。
-  **PATRONI\_RAFT\_PASSWORD**\：（可选）使用指定密码加密 Raft 流量，需要 ``cryptography`` python 模块。

PostgreSQL
----------
-  **PATRONI\_POSTGRESQL\_LISTEN**\：Postgres 监听的 IP 地址 + 端口。允许多个以逗号分隔的地址，只要端口组件以冒号附加在最后一个地址之后即可，例如 ``listen: 127.0.0.1,127.0.0.2:5432``\。Patroni 将使用此列表中的第一个地址与 PostgreSQL 节点建立本地连接。
-  **PATRONI\_POSTGRESQL\_CONNECT\_ADDRESS**\：其他节点和应用程序访问 Postgres 所使用的 IP 地址 + 端口。
-  **PATRONI\_POSTGRESQL\_PROXY\_ADDRESS**\：与 Postgres 相邻运行的连接池（例如 pgbouncer）对外访问的 IP 地址 + 端口。该值以 ``proxy_url`` 的形式写入 DCS 中的 member 键，可用于/有助于服务发现。
-  **PATRONI\_POSTGRESQL\_DATA\_DIR**\：Postgres 数据目录的位置，可以是已存在的，也可以是由 Patroni 初始化的。
-  **PATRONI\_POSTGRESQL\_CONFIG\_DIR**\：Postgres 配置目录的位置，默认为数据目录。必须可由 Patroni 写入。
-  **PATRONI\_POSTGRESQL\_BIN\_DIR**\：PostgreSQL 二进制文件的路径。（pg_ctl、initdb、pg_controldata、pg_basebackup、postgres、pg_isready、pg_rewind）默认值为空字符串，表示将使用 PATH 环境变量来查找可执行文件。
-  **PATRONI\_POSTGRESQL\_BIN\_PG\_CTL**\：（可选） ``pg_ctl`` 二进制的自定义名称。
-  **PATRONI\_POSTGRESQL\_BIN\_INITDB**\：（可选） ``initdb`` 二进制的自定义名称。
-  **PATRONI\_POSTGRESQL\_BIN\_PG\_CONTROLDATA**\：（可选） ``pg_controldata`` 二进制的自定义名称。
-  **PATRONI\_POSTGRESQL\_BIN\_PG\_BASEBACKUP**\：（可选） ``pg_basebackup`` 二进制的自定义名称。
-  **PATRONI\_POSTGRESQL\_BIN\_POSTGRES**\：（可选） ``postgres`` 二进制的自定义名称。
-  **PATRONI\_POSTGRESQL\_BIN\_IS\_READY**\：（可选） ``pg_isready`` 二进制的自定义名称。
-  **PATRONI\_POSTGRESQL\_BIN\_PG\_REWIND**\：（可选） ``pg_rewind`` 二进制的自定义名称。
-  **PATRONI\_POSTGRESQL\_PGPASS**\：`.pgpass <https://www.postgresql.org/docs/current/static/libpq-pgpass.html>`__ 密码文件的路径。Patroni 在执行 pg\_basebackup 之前以及在某些其他情况下会创建此文件。该位置必须可由 Patroni 写入。
-  **PATRONI\_REPLICATION\_USERNAME**\：复制用户名；该用户将在初始化期间创建。Replica 将使用此用户通过流式复制访问复制源
-  **PATRONI\_REPLICATION\_PASSWORD**\：复制密码；该用户将在初始化期间创建。
-  **PATRONI\_REPLICATION\_SSLMODE**\：（可选）对应 `sslmode <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLMODE>`__ 连接参数，它允许客户端指定与服务器之间的 TLS 协商模式类型。有关每种模式工作方式的更多信息，请访问 `PostgreSQL 文档 <https://www.postgresql.org/docs/current/libpq-ssl.html#LIBPQ-SSL-SSLMODE-STATEMENTS>`__。默认模式为 ``prefer``\。
-  **PATRONI\_REPLICATION\_SSLKEY**\：（可选）对应 `sslkey <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLKEY>`__ 连接参数，它指定与客户端证书一起使用的密钥的位置。
-  **PATRONI\_REPLICATION\_SSLPASSWORD**\：（可选）对应 `sslpassword <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLPASSWORD>`__ 连接参数，它指定在 ``PATRONI_REPLICATION_SSLKEY`` 中指定的密钥的密码。
-  **PATRONI\_REPLICATION\_SSLCERT**\：（可选）对应 `sslcert <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLCERT>`__ 连接参数，它指定客户端证书的位置。
-  **PATRONI\_REPLICATION\_SSLROOTCERT**\：（可选）对应 `sslrootcert <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLROOTCERT>`__ 连接参数，它指定一个文件的位置，该文件包含一个或多个证书颁发机构（CA）证书，客户端将使用这些证书来验证服务器的证书。
-  **PATRONI\_REPLICATION\_SSLCRL**\：（可选）对应 `sslcrl <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLCRL>`__ 连接参数，它指定包含证书吊销列表的文件的位置。客户端将拒绝连接到任何其证书出现在此列表中的服务器。
-  **PATRONI\_REPLICATION\_SSLCRLDIR**\：（可选）对应 `sslcrldir <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLCRLDIR>`__ 连接参数，它指定一个目录的位置，该目录中的文件包含证书吊销列表。客户端将拒绝连接到任何其证书出现在此列表中的服务器。
-  **PATRONI\_REPLICATION\_SSLNEGOTIATION**\：（可选）对应 `sslnegotiation <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLNEGOTIATION>`__ 连接参数，如果使用 SSL，它控制与服务器协商 SSL 加密的方式。
-  **PATRONI\_REPLICATION\_GSSENCMODE**\：（可选）对应 `gssencmode <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-GSSENCMODE>`__ 连接参数，它决定是否与服务器协商安全的 GSS TCP/IP 连接，以及以何种优先级协商
-  **PATRONI\_REPLICATION\_CHANNEL\_BINDING**\：（可选）对应 `channel_binding <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-CHANNEL-BINDING>`__ 连接参数，它控制客户端对 channel binding 的使用。
-  **PATRONI\_SUPERUSER\_USERNAME**\：超级用户的名称，在初始化（initdb）期间设置，之后由 Patroni 用来连接 postgres。此外，pg_rewind 也使用该用户。
-  **PATRONI\_SUPERUSER\_PASSWORD**\：超级用户的密码，在初始化（initdb）期间设置。
-  **PATRONI\_SUPERUSER\_SSLMODE**\：（可选）对应 `sslmode <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLMODE>`__ 连接参数，它允许客户端指定与服务器之间的 TLS 协商模式类型。有关每种模式工作方式的更多信息，请访问 `PostgreSQL 文档 <https://www.postgresql.org/docs/current/libpq-ssl.html#LIBPQ-SSL-SSLMODE-STATEMENTS>`__。默认模式为 ``prefer``\。
-  **PATRONI\_SUPERUSER\_SSLKEY**\：（可选）对应 `sslkey <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLKEY>`__ 连接参数，它指定与客户端证书一起使用的密钥的位置。
-  **PATRONI\_SUPERUSER\_SSLPASSWORD**\：（可选）对应 `sslpassword <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLPASSWORD>`__ 连接参数，它指定在 ``PATRONI_SUPERUSER_SSLKEY`` 中指定的密钥的密码。
-  **PATRONI\_SUPERUSER\_SSLCERT**\：（可选）对应 `sslcert <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLCERT>`__ 连接参数，它指定客户端证书的位置。
-  **PATRONI\_SUPERUSER\_SSLROOTCERT**\：（可选）对应 `sslrootcert <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLROOTCERT>`__ 连接参数，它指定一个文件的位置，该文件包含一个或多个证书颁发机构（CA）证书，客户端将使用这些证书来验证服务器的证书。
-  **PATRONI\_SUPERUSER\_SSLCRL**\：（可选）对应 `sslcrl <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLCRL>`__ 连接参数，它指定包含证书吊销列表的文件的位置。客户端将拒绝连接到任何其证书出现在此列表中的服务器。
-  **PATRONI\_SUPERUSER\_SSLCRLDIR**\：（可选）对应 `sslcrldir <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLCRLDIR>`__ 连接参数，它指定一个目录的位置，该目录中的文件包含证书吊销列表。客户端将拒绝连接到任何其证书出现在此列表中的服务器。
-  **PATRONI\_SUPERUSER\_SSLNEGOTIATION**\：（可选）对应 `sslnegotiation <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLNEGOTIATION>`__ 连接参数，如果使用 SSL，它控制与服务器协商 SSL 加密的方式。
-  **PATRONI\_SUPERUSER\_GSSENCMODE**\：（可选）对应 `gssencmode <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-GSSENCMODE>`__ 连接参数，它决定是否与服务器协商安全的 GSS TCP/IP 连接，以及以何种优先级协商
-  **PATRONI\_SUPERUSER\_CHANNEL\_BINDING**\：（可选）对应 `channel_binding <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-CHANNEL-BINDING>`__ 连接参数，它控制客户端对 channel binding 的使用。
-  **PATRONI\_REWIND\_USERNAME**\：（可选）用于 ``pg_rewind`` 的用户名；该用户将在 postgres 11+ 的初始化期间创建，并且将授予所有必要的 `权限 <https://www.postgresql.org/docs/11/app-pgrewind.html#id-1.9.5.8.8>`__。
-  **PATRONI\_REWIND\_PASSWORD**\：（可选）用于 ``pg_rewind`` 的用户的密码；该用户将在初始化期间创建。
-  **PATRONI\_REWIND\_SSLMODE**\：（可选）对应 `sslmode <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLMODE>`__ 连接参数，它允许客户端指定与服务器之间的 TLS 协商模式类型。有关每种模式工作方式的更多信息，请访问 `PostgreSQL 文档 <https://www.postgresql.org/docs/current/libpq-ssl.html#LIBPQ-SSL-SSLMODE-STATEMENTS>`__。默认模式为 ``prefer``\。
-  **PATRONI\_REWIND\_SSLKEY**\：（可选）对应 `sslkey <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLKEY>`__ 连接参数，它指定与客户端证书一起使用的密钥的位置。
-  **PATRONI\_REWIND\_SSLPASSWORD**\：（可选）对应 `sslpassword <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLPASSWORD>`__ 连接参数，它指定在 ``PATRONI_REWIND_SSLKEY`` 中指定的密钥的密码。
-  **PATRONI\_REWIND\_SSLCERT**\：（可选）对应 `sslcert <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLCERT>`__ 连接参数，它指定客户端证书的位置。
-  **PATRONI\_REWIND\_SSLROOTCERT**\：（可选）对应 `sslrootcert <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLROOTCERT>`__ 连接参数，它指定一个文件的位置，该文件包含一个或多个证书颁发机构（CA）证书，客户端将使用这些证书来验证服务器的证书。
-  **PATRONI\_REWIND\_SSLCRL**\：（可选）对应 `sslcrl <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLCRL>`__ 连接参数，它指定包含证书吊销列表的文件的位置。客户端将拒绝连接到任何其证书出现在此列表中的服务器。
-  **PATRONI\_REWIND\_SSLCRLDIR**\：（可选）对应 `sslcrldir <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLCRLDIR>`__ 连接参数，它指定一个目录的位置，该目录中的文件包含证书吊销列表。客户端将拒绝连接到任何其证书出现在此列表中的服务器。
-  **PATRONI\_REWIND\_SSLNEGOTIATION**\：（可选）对应 `sslnegotiation <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-SSLNEGOTIATION>`__ 连接参数，如果使用 SSL，它控制与服务器协商 SSL 加密的方式。
-  **PATRONI\_REWIND\_GSSENCMODE**\：（可选）对应 `gssencmode <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-GSSENCMODE>`__ 连接参数，它决定是否与服务器协商安全的 GSS TCP/IP 连接，以及以何种优先级协商
-  **PATRONI\_REWIND\_CHANNEL\_BINDING**\：（可选）对应 `channel_binding <https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNECT-CHANNEL-BINDING>`__ 连接参数，它控制客户端对 channel binding 的使用。

REST API
--------
-  **PATRONI\_RESTAPI\_THREAD\_POOL\_SIZE**\：Patroni 用于处理 REST API 请求的线程池大小。最小值为 ``5``\，默认值为 ``5``\。
-  **PATRONI\_RESTAPI\_CONNECT\_ADDRESS**\：访问 REST API 的 IP 地址和端口。
-  **PATRONI\_RESTAPI\_LISTEN**\：Patroni 监听以向 HAProxy 提供健康检查信息的 IP 地址和端口。
-  **PATRONI\_RESTAPI\_USERNAME**\：用于保护不安全的 REST API 端点的 Basic-auth 用户名。
-  **PATRONI\_RESTAPI\_PASSWORD**\：用于保护不安全的 REST API 端点的 Basic-auth 密码。
-  **PATRONI\_RESTAPI\_CERTFILE**\：指定包含 PEM 格式证书的文件。如果未指定 certfile 或将其留空，API 服务器将在不使用 SSL 的情况下工作。
-  **PATRONI\_RESTAPI\_KEYFILE**\：指定包含 PEM 格式密钥的文件。
-  **PATRONI\_RESTAPI\_KEYFILE\_PASSWORD**\：指定用于解密 keyfile 的密码。
-  **PATRONI\_RESTAPI\_CAFILE**\：指定包含 CA_BUNDLE 的文件，其中包含验证客户端证书时使用的可信 CA 证书。
-  **PATRONI\_RESTAPI\_CIPHERS**\：（可选）指定允许的加密套件（例如 "ECDHE-RSA-AES256-GCM-SHA384:DHE-RSA-AES256-GCM-SHA384:ECDHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES128-GCM-SHA256:!SSLv1:!SSLv2:!SSLv3:!TLSv1:!TLSv1.1"）
-  **PATRONI\_RESTAPI\_VERIFY\_CLIENT**\：``none``\（默认）、``optional`` 或 ``required``\。当为 ``none`` 时，REST API 不检查客户端证书。当为 ``required`` 时，所有 REST API 调用都需要客户端证书。当为 ``optional`` 时，所有不安全的 REST API 端点都需要客户端证书。当使用 ``required`` 时，如果证书签名验证成功，则客户端认证成功。对于 ``optional``\，只会对 ``PUT``\、``POST``\、``PATCH`` 和 ``DELETE`` 请求检查客户端证书。
-  **PATRONI\_RESTAPI\_ALLOWLIST**\：（可选）指定允许调用不安全 REST API 端点的主机集合。单个元素可以是主机名、IP 地址或使用 CIDR 表示法的网络地址。默认使用 ``allow all``\。如果设置了 ``allowlist`` 或 ``allowlist_include_members``\，任何未包含在内的内容都将被拒绝。
-  **PATRONI\_RESTAPI\_ALLOWLIST\_INCLUDE\_MEMBERS**\：（可选）如果设置为 ``true``\，则允许从 DCS 中注册的其他集群成员访问不安全的 REST API 端点（IP 地址或主机名取自成员的 ``api_url``\）。请注意，操作系统可能会为出站连接使用不同的 IP。
-  **PATRONI\_RESTAPI\_HTTP\_EXTRA\_HEADERS**\：（可选）HTTP 头允许 REST API 服务器随 HTTP 响应传递附加信息。
-  **PATRONI\_RESTAPI\_HTTPS\_EXTRA\_HEADERS**\：（可选）启用 TLS 时，HTTPS 头允许 REST API 服务器随 HTTP 响应传递附加信息。这也将传递在 ``http_extra_headers`` 中设置的附加信息。
-  **PATRONI\_RESTAPI\_REQUEST\_QUEUE\_SIZE**\：（可选）设置 Patroni REST API 使用的 TCP socket 的请求队列大小。一旦队列已满，进一步的请求将收到「Connection denied」错误。默认值为 5。
-  **PATRONI\_RESTAPI\_SERVER\_TOKENS**\：（可选）配置 ``Server`` HTTP 头的值。``Original``\（默认）将暴露原始行为并显示 BaseHTTP 和 Python 版本，例如 ``BaseHTTP/0.6 Python/3.12.3``\。``Minimal``\：该头将仅包含 Patroni 版本，例如 ``Patroni/4.0.0``\。``ProductOnly``\：该头将仅包含产品名称，例如 ``Patroni``\。

.. warning::

    - 给定 Patroni 集群的所有节点都必须能够访问 ``PATRONI_RESTAPI_CONNECT_ADDRESS``\。Patroni 在内部使用它，在 leader 竞争期间查找复制延迟最小的节点。
    - 如果您启用了客户端证书验证（``PATRONI_RESTAPI_VERIFY_CLIENT`` 设置为 ``required``\），您还 **必须** 在 ``PATRONI_CTL_CERTFILE``\、``PATRONI_CTL_KEYFILE``\、``PATRONI_CTL_KEYFILE_PASSWORD`` 中提供 **有效的客户端证书**\。如果未提供，Patroni 将无法正常工作。


CTL
---
-  **PATRONICTL\_CONFIG\_FILE**\：（可选）配置文件的位置。
-  **PATRONI\_CTL\_USERNAME**\：（可选）访问受保护的 REST API 端点的 Basic-auth 用户名。如果未提供，:ref:`patronictl` 将使用为 REST API「username」参数提供的值。
-  **PATRONI\_CTL\_PASSWORD**\：（可选）访问受保护的 REST API 端点的 Basic-auth 密码。如果未提供，:ref:`patronictl` 将使用为 REST API「password」参数提供的值。
-  **PATRONI\_CTL\_INSECURE**\：（可选）允许在不对 SSL 证书进行验证的情况下连接到 REST API。
-  **PATRONI\_CTL\_CACERT**\：（可选）指定包含 CA_BUNDLE 的文件或包含可信 CA 证书的目录，用于验证 REST API SSL 证书。如果未提供，:ref:`patronictl` 将使用为 REST API「cafile」参数提供的值。
-  **PATRONI\_CTL\_CERTFILE**\：（可选）指定包含 PEM 格式客户端证书的文件。
-  **PATRONI\_CTL\_KEYFILE**\：（可选）指定包含 PEM 格式客户端密钥的文件。
-  **PATRONI\_CTL\_KEYFILE\_PASSWORD**\：（可选）指定用于解密客户端 keyfile 的密码。
