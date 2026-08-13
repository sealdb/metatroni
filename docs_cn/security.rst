.. _security:

========
安全考量
========

Patroni 集群有两个需要防止未授权访问的接口：分布式配置存储（DCS）和 Patroni REST API。

保护 DCS
========

Patroni 和 :ref:`patronictl` 都会向 DCS 存储数据并从 DCS 检索数据。

尽管 DCS 不包含任何敏感信息，但它允许修改部分 Patroni/Postgres 配置。因此，首先应该保护的正是 DCS 本身。

具体的保护细节取决于所使用的 DCS 类型。针对受支持的 DCS 类型的认证和加密参数（tokens/basic-auth/client certificates）在 :ref:`settings <yaml_configuration>` 中有详细介绍。

通常的建议是为所有 DCS 通信启用 TLS。

保护 REST API
=============

保护 REST API 是一项更复杂的任务。

Patroni REST API 被 Patroni 自身在 leader 竞争期间使用，被 :ref:`patronictl` 工具用来执行 failover/switchover/reinitialize/restart/reload，被 HAProxy 或任何其他类型的负载均衡器用来执行 HTTP 健康检查，当然也可以用于监控。

从安全的角度来看，REST API 包含安全端点（``GET`` 请求，仅检索信息）和不安全端点（``PUT``\、``POST``\、``PATCH`` 和 ``DELETE`` 请求，会改变节点的状态）。

通过设置 ``restapi.authentication.username`` 和 ``restapi.authentication.password`` 参数，可以使用 HTTP basic-auth 保护不安全端点。在不启用 TLS 的情况下，无法保护安全端点。

当 REST API 启用了 TLS 并建立了 PKI 时，所有端点都可以在 API 服务器和 API 客户端之间进行双向认证。

``restapi`` 部分的参数用于向服务器启用 TLS 客户端认证。根据 ``verify_client`` 参数的值，API 服务器会要求安全和不安全的 API 调用都必须通过客户端证书验证（``verify_client: required``\），或仅要求不安全的 API 调用通过验证（``verify_client: optional``\），或对任何 API 调用都不做要求（``verify_client: none``\）。

``ctl`` 部分的参数用于向客户端启用 TLS 服务器认证（即使用与 patroni 相同配置的 :ref:`patronictl` 工具）。设置 ``insecure: true`` 可以禁用客户端对服务器证书的验证。关于 TLS 客户端参数的详细描述，请参阅 :ref:`settings <patronictl_settings>`。

保护 PostgreSQL 数据库本身免受未授权访问不在本文档的讨论范围内，相关内容请参阅 https://www.postgresql.org/docs/current/client-authentication.html
