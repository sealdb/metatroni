# Patroni Integration Tests

## MySQL HA Test

```bash
# Default MySQL path is /usr/local/mysql
python integration-tests/test_mysql_ha.py

# Or specify a custom path:
MYSQL_BASE=/path/to/mysql python integration-tests/test_mysql_ha.py
python integration-tests/test_mysql_ha.py /path/to/mysql
```

Tests the complete MySQL HA flow: bootstrap, clone, replication, failover.
