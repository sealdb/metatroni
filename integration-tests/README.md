# Patroni Integration Tests

## MySQL HA Test

Handler-level end-to-end test (bootstrap → clone → replicate → failover → rejoin).

```bash
MYSQL_BASE=/home/wslu/work/mysql/mysql80-debug python3 integration-tests/test_mysql_ha.py

# Preserve datadir on failure
MYSQL_KEEP_DATA=1 MYSQL_BASE=/home/wslu/work/mysql/mysql80-debug \
  python3 integration-tests/test_mysql_ha.py --keep-data
```
