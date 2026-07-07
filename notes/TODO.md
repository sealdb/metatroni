# Patroni MySQL HA 开发进度

## 环境信息
- MySQL 8.0.35-debug 源码安装路径: `/home/wslu/work/mysql/mysql80-debug`
- 工作目录: `/home/wslu/work/github/db/patroni`
- 项目分支: `dev_base_v4.1.3` (基于 commit `429972a6`)

## 已完成的工作

### 核心修复 (Step 1)
| 修改 | 文件 | 说明 |
|------|------|------|
| MySQL 继承 `DatabaseHandler` ABC | `patroni/mysql/__init__.py` | 原来是继承 `Tags`，改为 ABC 确保接口完整 |
| `data_directory_empty` → 方法(非 `@property`) | `patroni/mysql/__init__.py`, `patroni/db/__init__.py` | 匹配 PG 实现和 `ha.py` 调用方式 |
| `stop()` 接收 `**kwargs` | `patroni/mysql/__init__.py` | `ha.py` 传递 PG 专有参数(`checkpoint`, `on_safepoint` 等) |
| `restart()` 接收 `timeout, task, **kwargs` | `patroni/mysql/__init__.py` | 同上 |
| `cancellable` 返回 `_NullCancellable` 对象 | `patroni/mysql/__init__.py` | 原来是 `None` → 导致 `AsyncExecutor` 崩溃 |
| `postmaster_start_time` → 方法(非 `@property`) | `patroni/mysql/__init__.py` | `ha.py` 以方法方式调用 |
| `latest_checkpoint_locations()` → 返回 `(None, None)` | `patroni/mysql/__init__.py` | 原来是 `{}` → 解包时崩溃 |
| 连接池初始化时传入 auth kwargs | `patroni/mysql/__init__.py` | 通过 `_build_conn_kwargs()` 从配置读取 |
| `follow()` 从配置读取复制用户密码 | `patroni/mysql/__init__.py` | 原来是硬编码 `replicator/replicator` |
| `start()` 设置 `STARTING` 状态 | `patroni/mysql/__init__.py` | `is_starting()` 才能正确返回 True |
| `stop()` 先通过 `is_running()` 检查 | `patroni/mysql/__init__.py` | 修复进程查找不到时无法停止的问题 |
| ConfigHandler 增加 `replication`/`superuser` 属性 | `patroni/mysql/config.py` | 从 `authentication` 配置段读取 |
| `check_recovery_conf()` 始终返回 `(True, True)` | `patroni/mysql/config.py` | 确保每次 HA 循环都重新配置复制 |
| `post_bootstrap()` 兼容 PG 签名 `(config, task)` | `patroni/mysql/bootstrap.py` | `ha.py` 传递 bootstrap 配置和 async_response |
| 增加 `bootstrap(config)` 方法 | `patroni/mysql/bootstrap.py` | 初始化数据目录 + 启动 MySQL |
| 增加 `clone(member, from_leader)` 方法 | `patroni/mysql/bootstrap.py` | 包装 `create_replica()` |
| `create_replica()` 改进: pipe mysqldump→mysql | `patroni/mysql/bootstrap.py` | 初始化+启动+恢复数据 |
| `can_create_replica_without_replication_connection()` 修正 | `patroni/mysql/__init__.py` | 空列表返回 False |
| `sysid_valid()` 支持 UUID 格式 | `patroni/ha.py` | MySQL 使用 `@@server_uuid` |

### API 修复 (Step 4 partial)
| 修改 | 说明 |
|------|------|
| `/metrics` endpoint 支持 MySQL | `patroni/api.py:do_GET_metrics()` — `xlog`/`binlog` 都支持 |
| MySQL 指标使用 `patroni_binlog_*` 命名 | 内部统一通过 `_xlog_or_binlog()` 辅助函数 |
| PG 专有指标(`standby_leader`, `sync_standby`, `quorum_standby` 等)对 MySQL 隐藏 | |
| state 指标支持 `MySQLState` 枚举 | 备用 `ImportError` 防止 pymysql 未安装时崩溃 |

### 测试 (Step 3)
- `tests/test_mysql.py` — **48 个单元测试**
  - `TestMySQLState` (3): 状态/角色枚举 + 版本解析
  - `TestMySQLConfig` (4): 初始化 + auth + 路径 + check_recovery_conf
  - `TestMySQL` (33): 核心 handler 全部方法
  - `TestMySQLIntegration` (1): start/stop
  - `TestBootstrap` (4): bootstrap + clone + post_bootstrap
  - `TestMySQLConnection` (3): 连接池
- 全量测试: **666 passed**, 3 deselected (pre-existing failure)

### 集成测试验证
通过真实 MySQL 8.0.35-debug 二进制验证:
- ✅ 数据目录初始化 (`mysqld --initialize-insecure`)
- ✅ MySQL 启动/停止 (`daemonize`)
- ✅ 状态检查: `is_running()`, `is_primary()`, `is_healthy()`
- ✅ 复制用户创建
- ✅ `SHOW MASTER STATUS` → binlog 位置
- ✅ `SELECT @@server_uuid` → UUID
- ✅ `replication_state()` → `'primary'`
- ✅ `timeline_wal_position()` → `(0, pos, 0, 0, 0)`
- ✅ `last_operation()` → binlog 位置
- ✅ `promote()` → 已是主库时返回 True
- ✅ 克隆: `bootstrap.clone()` → 初始化+启动+mysqldump→mysql 管道恢复
- ❌ 克隆后数据查询失败 (testdb 不存在) — 管道管道方式可能需要修正

## 待办事项

### 优先级: 高

1. **修复 clone 的数据恢复逻辑**
   - 当前 `create_replica()` 使用 `mysqldump | mysql` 管道
   - 测试中发现数据未正常恢复 (`Unknown database 'testdb'`)
   - 需要排查: 使用临时文件保存 dump 然后通过 `mysql < file` 恢复，避免管道问题
   - 或改用 `subprocess.run()` 分步执行而非 `Popen` 管道

2. **`ha.py` 中 Rewind 相关代码审计**
   - `self._rewind.checkpoint_after_promote()` — MySQL 返回 False
   - `self._rewind.ensure_checkpoint_after_promote()` — MySQL 会执行但无实际效果
   - `self._rewind.trigger_check_diverged_lsn()` — MySQL 不应触发
   - 目前有 `is_mysql` 守卫但需要验证所有路径
   - `_handle_rewind_or_reinitialize()` — MySQL 会进入但 Rewind.state=INITIAL 所以返回 None

3. **`bootstrap.initialize()` 增加 `--basedir` 参数**
   - MySQL 8.0 debug 编译版可能需要 `--basedir` 才能找到安装目录
   - 从测试来看 `--initialize-insecure` 和启动都正常工作，暂不需要

### 优先级: 中

4. **xtrabackup clone 支持**
   - 在 `create_replica_methods` 中支持 `xtrabackup` 做物理备份
   - 物理备份比 mysqldump 快得多，且不需要启动 MySQL 来恢复

5. **`setup.py` mysql extra**
   - 添加 `extras_require = {'mysql': ['pymysql']}`

6. **`create_replica()` 错误处理改进**
   - 管道方式需要更好的错误捕获和日志
   - 超时后的进程清理

### 优先级: 低

7. **文档**
   - MySQL 配置说明
   - 使用示例

8. **`mysqlx=OFF` 默认参数**
   - MySQL 8.0 默认启用 X Plugin，绑定 33060 端口
   - 多实例运行时可能冲突
   - 可在 `write_my_cnf()` 中默认添加 `mysqlx=OFF`

## 测试命令
```bash
# 所有测试(排除可选的 raft/zookeeper)
python -m pytest tests/ -q --ignore=tests/test_aws.py --ignore=tests/test_exhibitor.py --ignore=tests/test_raft.py --ignore=tests/test_raft_controller.py --ignore=tests/test_zookeeper.py --deselect tests/test_ha.py::TestHa::test_manual_failover_process_no_leader

# 仅 MySQL 测试
python -m pytest tests/test_mysql.py -v

# 集成测试(需要 MySQL 8.0 二进制)
python3 /tmp/test_mysql_integration.py
python3 /tmp/test_mysql_replication.py
```

## 调试 MySQL
```bash
# 查看 MySQL 错误日志
cat data/<node>/*.err

# 手动初始化并启动
/home/wslu/work/mysql/mysql80-debug/bin/mysqld --initialize-insecure --datadir=/tmp/test_data --user=$USER
/home/wslu/work/mysql/mysql80-debug/bin/mysqld --datadir=/tmp/test_data --port=33307 --socket=/tmp/test_data/mysql.sock --daemonize

# 连接
/home/wslu/work/mysql/mysql80-debug/bin/mysql -h127.0.0.1 -P33307 -uroot
```
