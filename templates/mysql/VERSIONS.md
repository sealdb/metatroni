# Version matrix for templates/mysql (consumed by patroni.mysql.versioning).
#
# | Family | Semi-sync names        | Expire logs                 | Redo log                    | Query cache | MGR   |
# |--------|------------------------|-----------------------------|-----------------------------|-------------|-------|
# | 5.6    | master/slave           | expire_logs_days            | innodb_log_file_size        | yes (OFF)   | no    |
# | 5.7    | master/slave + AFTER_SYNC | expire_logs_days         | innodb_log_file_size        | yes (OFF)   | 5.7.17+|
# | 8.0 (<26) | master/slave        | binlog_expire_logs_seconds  | log_file_size / redo@30+    | no          | yes   |
# | 8.0 (≥26) / 8.x / 9.x | source/replica | binlog_expire_logs_seconds | innodb_redo_log_capacity   | no          | yes   |
#
# Detection: `mysqld --version` or `--mysql-version 5.7|8.0|8.4|9.0|...`
# Initcmd builds parameters in Python (versioning.py); YAML files below are
# human-readable references, not loaded as the sole source of truth.
