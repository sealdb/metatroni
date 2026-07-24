# Patroni MySQL HA 开发进度

## 环境信息
- MySQL 8.0.35-debug 源码安装路径: `/home/wslu/work/mysql/mysql80-debug`
- 工作目录: `/home/wslu/work/github/db/sealdb/metatroni`
- 项目分支: `dev_base_v4.1.3` (基于 commit `429972a6`)
- etcd: `/usr/bin/etcd` **3.7.0-alpha.0**（必须用 `etcd3:`，v2 API 已移除）
- xtrabackup: `/usr/bin/xtrabackup` **8.0.35-36**（与 MySQL 8.0.35 匹配）

## 已完成的工作

### 核心修复 / 能力下沉 / Clone / Failover
见历史条目：ABC、mysqldump/xtrabackup、sysid、follow/start、Patroni+etcd 11/11 等。

### Semi-Sync 安全与集成（2026-07-24）
| 项 | 说明 |
|----|------|
| `ha.process_healthy_cluster` | semi-sync / MGR 检查改到 **持锁主路径**（原先只在无锁路径，主上从不执行） |
| `write_my_cnf` | 配置 `rpl_semi_sync_*` 时自动 `plugin-load-add` semisync_source/replica；忽略 Patroni 专用 `cluster_size` |
| 集成测试 | `integration-tests/test_mysql_semi_sync.py` — **16/16 passed**（quorum RO → 副本恢复 RW → 副本丢失再 RO） |

### xtrabackup E2E（2026-07-24）
| 项 | 说明 |
|----|------|
| `get_xtrabackup_path` | 优先 `bin_dir`，否则 `PATH` / `/usr/bin` |
| `ensure_replication_user` | 增加 `BACKUP_ADMIN` + `performance_schema.log_status` |
| 物理恢复 | 删除捐赠者 `auto.cnf`，避免 UUID 冲突 |
| 失败清理 | `try/finally` 清理 tmp / 半成品 datadir；超时 kill 子进程 |
| 集成测试 | `integration-tests/test_mysql_xtrabackup.py` — **13/13 passed** |

### create_replica 清理（2026-07-24）
- mysqldump：失败时 kill mysqld、删 `clone.sql`、rmtree 半成品 datadir
- xtrabackup：始终清理 `*.xtrabackup_tmp`；失败时清理 datadir

## 测试
- `tests/test_mysql.py` — 53 unit tests
- `integration-tests/test_mysql_ha.py` — 44/44（handler failover + rejoin）
- `integration-tests/test_mysql_patroni_ha.py` — 11/11（Patroni + etcd）
- `integration-tests/test_mysql_semi_sync.py` — **16/16**
- `integration-tests/test_mysql_xtrabackup.py` — **13/13**

## 待办事项

### 优先级: 高（下一阶段）

1. **MGR majority-loss GTID 选举做实**
   - `_handle_mgr_majority_loss` 仍是「持锁节点直接 bootstrap」
   - 需经 DCS 比较各节点 GTID 再选 bootstrap 者
   - 配套 MGR 集成测试（primary 切换、majority loss）

### 优先级: 低

2. 文档/示例 YAML 持续同步（semi-sync / xtrabackup 配置样例）

## 测试命令
```bash
# 单元测试
python3 -m unittest tests.test_mysql -q

# Handler HA（含 failover + rejoin）
MYSQL_BASE=/home/wslu/work/mysql/mysql80-debug python3 integration-tests/test_mysql_ha.py

# Patroni + etcd
MYSQL_BASE=/home/wslu/work/mysql/mysql80-debug PYTHONPATH=. \
  python3 -u integration-tests/test_mysql_patroni_ha.py

# Semi-sync quorum safety
MYSQL_BASE=/home/wslu/work/mysql/mysql80-debug PYTHONPATH=. \
  python3 -u integration-tests/test_mysql_semi_sync.py

# xtrabackup clone
MYSQL_BASE=/home/wslu/work/mysql/mysql80-debug PYTHONPATH=. \
  python3 -u integration-tests/test_mysql_xtrabackup.py
```
