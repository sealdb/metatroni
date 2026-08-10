# Patroni MySQL HA 开发进度

## 环境信息
- MySQL 8.0.35-debug: `/home/wslu/work/mysql/mysql80-debug`
- 工作目录: `/home/wslu/work/github/db/sealdb/metatroni`
- 分支: `dev_base_v4.1.3`
- etcd 3.7 → 必须用 `etcd3:`
- xtrabackup 8.0.35-36 @ `/usr/bin/xtrabackup`

## 已完成

### 主路径
- Handler / Patroni+etcd async GTID HA（failover + rejoin）
- Semi-sync：`AFTER_SYNC` + 3 节点无限 timeout（对齐 xenon）+ quorum→`super_read_only`
- xtrabackup clone E2E + create_replica 失败清理
- `follow()`/`start()` 对齐 PG；sysid/timeline MySQL 适配
- **`patroni_mysql_init`**：模板生成 `patroni.yml`/`my.cnf`，单机多节点端口错开，内存按百分比均分
- **MySQL demote/rejoin**：`Ha._demote_mysql` 跳过 PG rewind；graceful 释放 leader 锁；follow 新主；单测 + switchover 回归

### MGR majority-loss GTID 选举（2026-07-27）
| 项 | 说明 |
|----|------|
| DCS 发布 | `enrich_dcs_data` → `gtid_executed` |
| 比较 | `gtid_relation()` / `GTID_SUBSET` → equal / a_ahead / b_ahead / incomparable |
| 选举 | `select_mgr_bootstrap_winner`：最大 GTID，相等则名字字典序最小 |
| 持锁落后 | 返回 `mgr_yield_lock` → `ha.release_leader_key_voluntarily()` |
| 赢家无锁 | 等待租约；竞锁时 `_is_healthiest_node` 在 MGR 模式下比 GTID |
| 非赢家 | `rejoin_mgr_group`（若 DCS 已有 primary）或等待 |
| REST | `/patroni` 始终带 `binlog.gtid_set`（`@@gtid_executed`） |
| 插件 | `write_my_cnf` 自动 `plugin-load-add=group_replication.so` |
| 单测 | `tests/test_mysql.py` 覆盖选举 / yield / rejoin / enrich / **GTID fork**（61 passed） |
| 集成 | `test_mysql_mgr_election.py` + `test_mysql_mgr_e2e.py` 31/31 + **`test_mysql_mgr_patroni_ha.py` 24/24**（etcd3 + 3 Patroni） |

### GTID 分叉 pause/告警（2026-07-27）
| 项 | 说明 |
|----|------|
| 检测 | `describe_mgr_gtid_fork`：多个 maximal 且 `GTID_SUBSET` 互不包含 |
| 动作 | `run_mgr_cycle` → `mgr_gtid_fork`；强制 `super_read_only`；**不** bootstrap |
| Pause | `ha._handle_mgr_gtid_fork` 默认写 DCS `pause: true` + `mgr_gtid_fork` 面包屑 |
| 开关 | `mysql.parameters.mgr_pause_on_gtid_fork`（默认 true，不进 my.cnf） |
| 可见性 | member DCS / `/patroni` 带 `mgr_gtid_fork`；组恢复健康后清除 |
| 运维 | 修好分叉后 `patronictl resume` |

### 三节点 MGR E2E 踩坑（已修）
- `@@group_replication_primary_member` 不是 sysvar → status 恒空；改查 `replication_group_members`
- `GET_MASTER_PUBLIC_KEY` 在 `group_replication_recovery` 上 ER 3139；且 pymysql 出错后 `cursor.connection=None` 触发 ping AttributeError
- `caching_sha2_password` 无 TLS 无法做 distributed recovery → replicator 用 `mysql_native_password`
- MGR 通信端口改为 `client_port+10`
- 空库 `GROUP_CONCAT` → 字面量 `NULL` 导致 mysqldump 失败
- `rejoin_mgr_group` 须先 `STOP/RESET SLAVE`（单主 MGR 拒绝与异步通道并存）
- 空 GTID 初始 bootstrap；`sync_replication_slots` 签名对齐 PG
- MGR 模式下勿落入 async `follow()`（会触发 PG rewind / 双通道）
- 多数丢失恢复：先让 GTID winner 单独 bootstrap 并写入 DCS `mgr_primary`，再恢复其余节点，避免双主抢 bootstrap

## 待办

### 优先级: 中
1. MGR 与 async GTID 复制模式切换文档

## 测试命令
```bash
python3 -m unittest tests.test_mysql tests.test_mysql_init tests.test_mysql_versioning -q

# 生成 3 节点 semi-sync（默认输出到项目 deploy/mysql-ha）
PYTHONPATH=. python3 -m patroni.mysql.initcmd --force \
  --bin-dir /home/wslu/work/mysql/mysql80-debug/bin \
  --memory-pct 50

# 本地 demote/rejoin 回归（需 etcd + 已生成 deploy/mysql-ha）
# bash deploy/mysql-ha/_reg_failover.sh
```

MYSQL_BASE=/home/wslu/work/mysql/mysql80-debug PYTHONPATH=. \
  python3 -u integration-tests/test_mysql_mgr_election.py

MYSQL_BASE=/home/wslu/work/mysql/mysql80-debug PYTHONPATH=. \
  python3 -u integration-tests/test_mysql_mgr_e2e.py

MYSQL_BASE=/home/wslu/work/mysql/mysql80-debug PYTHONPATH=. \
  python3 -u integration-tests/test_mysql_mgr_patroni_ha.py

MYSQL_BASE=/home/wslu/work/mysql/mysql80-debug PYTHONPATH=. \
  python3 -u integration-tests/test_mysql_patroni_ha.py

MYSQL_BASE=/home/wslu/work/mysql/mysql80-debug PYTHONPATH=. \
  python3 -u integration-tests/test_mysql_semi_sync.py

MYSQL_BASE=/home/wslu/work/mysql/mysql80-debug PYTHONPATH=. \
  python3 -u integration-tests/test_mysql_xtrabackup.py
```
