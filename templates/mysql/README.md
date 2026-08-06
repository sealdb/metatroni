# MySQL / Patroni config templates (xenon-aligned)

Source of truth for `patroni_mysql_init`. Values follow:

| Source | What we take |
|--------|----------------|
| `xenon/docs/config/MySQL.md` | GTID, semi-sync timeout/`wait_no_slave`, `skip-slave-start`, parallel workers |
| `radondb-ansible/.../my.cnf.Debian.j2` | Production my.cnf used with Xenon (relay/master info TABLE, buffer pool, caches) |
| Xenon ops docs (`AFTER_SYNC`) | `rpl_semi_sync_*_wait_point=AFTER_SYNC` (financial-grade) |
| `xenon` leader runtime | 3+ nodes → timeout `10**18` ms; wait count `(N-1)//2` |
| `xenon-mgr` | MGR bootstrap/join channel semantics; single-primary group |

MySQL 8.0 naming (`source`/`replica`) is used in generated files; xenon docs still show 5.7 `master`/`slave` names.

Generate under the repo (default)::

    PYTHONPATH=. python3 -m patroni.mysql.initcmd --force \\
      --bin-dir /path/to/mysql/bin
    # → detects mysqld version, writes deploy/mysql-ha/

    # Explicit family (5.6 / 5.7 / 8.0 / 8.x / 9.x)
    PYTHONPATH=. python3 -m patroni.mysql.initcmd --force --mysql-version 5.7

See ``VERSIONS.md`` for the per-version parameter matrix.
