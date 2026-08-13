"""MySQL version detection and version-aware mysqld parameter profiles.

Supports families used by xenon / metatroni deployments:

* ``5.6`` — GTID + semi-sync (master/slave plugins)
* ``5.7`` — + AFTER_SYNC, wait_for_slave_count, parallel appliers, super_read_only
* ``8.0`` — MySQL 8.0.x (auto-splits pre/post 8.0.26 naming)
* ``8`` / ``8.x`` — Innovation 8.1+ (source/replica naming)
* ``9`` / ``9.x`` — MySQL 9.x

Call ``resolve_mysql_version()`` then ``build_version_parameters()``.
"""

from __future__ import annotations

import os
import re
import subprocess

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

# (major, minor, patch)
VersionTuple = Tuple[int, int, int]


@dataclass(frozen=True)
class MysqlVersion:
    """Parsed server version."""

    major: int
    minor: int
    patch: int
    raw: str = ''

    @property
    def tuple(self) -> VersionTuple:
        return (self.major, self.minor, self.patch)

    @property
    def family(self) -> str:
        """Coarse family key for templates: 5.6 / 5.7 / 8.0 / 8 / 9."""
        if self.major == 5 and self.minor == 6:
            return '5.6'
        if self.major == 5 and self.minor >= 7:
            return '5.7'
        if self.major == 8 and self.minor == 0:
            return '8.0'
        if self.major == 8:
            return '8'
        if self.major >= 9:
            return '9'
        # Fallback: treat unknown 5.x as 5.7-ish, else modern
        if self.major == 5:
            return '5.7'
        return '8.0'

    @property
    def uses_source_replica_names(self) -> bool:
        """True when semi-sync / replica sysvars use source/replica (8.0.26+)."""
        if self.major > 8:
            return True
        if self.major == 8 and self.minor > 0:
            return True
        if self.major == 8 and self.minor == 0 and self.patch >= 26:
            return True
        return False

    @property
    def uses_innodb_redo_log_capacity(self) -> bool:
        """innodb_redo_log_capacity replaces innodb_log_file_size (8.0.30+)."""
        if self.major > 8:
            return True
        if self.major == 8 and self.minor > 0:
            return True
        if self.major == 8 and self.minor == 0 and self.patch >= 30:
            return True
        return False

    @property
    def uses_binlog_expire_seconds(self) -> bool:
        """binlog_expire_logs_seconds (8.0.3+); else expire_logs_days."""
        if self.major >= 9:
            return True
        if self.major == 8 and self.minor > 0:
            return True
        if self.major == 8 and self.minor == 0 and self.patch >= 3:
            return True
        return False

    @property
    def has_query_cache(self) -> bool:
        return self.major < 8

    @property
    def has_mysqlx(self) -> bool:
        return self.major >= 8

    @property
    def has_after_sync_wait_point(self) -> bool:
        # Introduced in 5.7.2
        if self.major > 5:
            return True
        if self.major == 5 and self.minor >= 7:
            return True
        return False

    @property
    def has_wait_for_replica_count(self) -> bool:
        # 5.7.3+
        if self.major > 5:
            return True
        if self.major == 5 and self.minor >= 7:
            return True
        return False

    @property
    def has_slave_parallel_logical_clock(self) -> bool:
        # LOGICAL_CLOCK from 5.7
        if self.major > 5:
            return True
        if self.major == 5 and self.minor >= 7:
            return True
        return False

    @property
    def has_mgr(self) -> bool:
        # Group Replication GA roughly 5.7.17+ / 8.0+
        if self.major >= 8:
            return True
        if self.major == 5 and self.minor >= 7:
            return True
        return False

    @property
    def default_collation(self) -> str:
        if self.major >= 8:
            return 'utf8mb4_0900_ai_ci'
        return 'utf8mb4_general_ci'

    def __str__(self) -> str:
        return f'{self.major}.{self.minor}.{self.patch}'


_VERSION_RE = re.compile(
    r'(?:Ver\s+)?(?P<maj>\d+)\.(?P<min>\d+)\.(?P<pat>\d+)',
    re.IGNORECASE,
)


def parse_mysql_version(text: str) -> MysqlVersion:
    """Parse a version string like ``8.0.35`` or mysqld ``--version`` output."""
    text = (text or '').strip()
    if not text:
        raise ValueError('empty MySQL version')
    # Prefer the first X.Y.Z after Ver / mysql
    m = _VERSION_RE.search(text)
    if not m:
        raise ValueError(f'cannot parse MySQL version from {text!r}')
    return MysqlVersion(
        major=int(m.group('maj')),
        minor=int(m.group('min')),
        patch=int(m.group('pat')),
        raw=text,
    )


def detect_mysqld_version(bin_dir: str = '', mysqld: str = '') -> MysqlVersion:
    """Run ``mysqld --version`` and parse."""
    path = mysqld or (os.path.join(bin_dir, 'mysqld') if bin_dir else 'mysqld')
    try:
        out = subprocess.run(
            [path, '--version'],
            capture_output=True, text=True, timeout=15, check=False,
        )
        blob = (out.stdout or '') + '\n' + (out.stderr or '')
        return parse_mysql_version(blob)
    except Exception as e:
        raise RuntimeError(f'failed to detect version via {path}: {e}') from e


def resolve_mysql_version(
        explicit: Optional[str] = None,
        bin_dir: str = '',
        default: str = '8.0.35') -> MysqlVersion:
    """Resolve version from ``--mysql-version``, else ``mysqld --version``, else default."""
    if explicit:
        # Allow family shortcuts: 5.6, 5.7, 8.0, 8, 8.x, 9, 9.x
        shortcuts = {
            '5.6': '5.6.51',
            '5.7': '5.7.44',
            '8.0': '8.0.35',
            '8': '8.4.0',
            '8.x': '8.4.0',
            '9': '9.0.0',
            '9.x': '9.0.0',
        }
        key = explicit.strip().lower()
        return parse_mysql_version(shortcuts.get(key, explicit))
    if bin_dir:
        return detect_mysqld_version(bin_dir=bin_dir)
    try:
        return detect_mysqld_version(bin_dir='')
    except Exception:
        return parse_mysql_version(default)


def semi_sync_plugin_names(version: MysqlVersion) -> Tuple[str, str]:
    """Return ``(source_or_master.so, replica_or_slave.so)``."""
    if version.uses_source_replica_names:
        return ('semisync_source.so', 'semisync_replica.so')
    return ('semisync_master.so', 'semisync_slave.so')


def apply_semi_sync_params(version: MysqlVersion, nodes: int,
                           timeout_ms: int,
                           wait_count: int) -> Dict[str, str]:
    """Build semi-sync my.cnf keys for *version* (xenon posture)."""
    params: Dict[str, str] = {'cluster_size': str(nodes)}
    if version.uses_source_replica_names:
        params.update({
            'rpl_semi_sync_source_enabled': 'OFF',
            'rpl_semi_sync_replica_enabled': 'ON',
            'rpl_semi_sync_source_timeout': str(timeout_ms),
            'rpl_semi_sync_source_wait_no_replica': 'ON',
        })
        if version.has_after_sync_wait_point:
            params['rpl_semi_sync_source_wait_point'] = 'AFTER_SYNC'
        if version.has_wait_for_replica_count:
            params['rpl_semi_sync_source_wait_for_replica_count'] = str(wait_count)
    else:
        params.update({
            'rpl_semi_sync_master_enabled': 'OFF',
            'rpl_semi_sync_slave_enabled': 'ON',
            'rpl_semi_sync_master_timeout': str(timeout_ms),
            'rpl_semi_sync_master_wait_no_slave': 'ON',
        })
        if version.has_after_sync_wait_point:
            params['rpl_semi_sync_master_wait_point'] = 'AFTER_SYNC'
        if version.has_wait_for_replica_count:
            params['rpl_semi_sync_master_wait_for_slave_count'] = str(wait_count)
    return params


def build_base_parameters(version: MysqlVersion) -> Dict[str, str]:
    """Version-aware shared mysqld parameters (xenon / ansible aligned)."""
    p: Dict[str, str] = {
        'gtid_mode': 'ON',
        'enforce_gtid_consistency': 'ON',
        'log-bin': 'mysql-bin',
        'binlog_format': 'ROW',
        'sync_binlog': '1',
        'innodb_flush_log_at_trx_commit': '1',
        'innodb_flush_method': 'O_DIRECT',
        'read_only': 'ON',
        'open_files_limit': '65536',
        'slow_query_log': '1',
        'long_query_time': '1',
        'tmp_table_size': '32M',
        'max_heap_table_size': '32M',
        'thread_cache_size': '128',
        'table_open_cache': '2000',
        'table_definition_cache': '2000',
        'max_allowed_packet': '4194304',
        'max_connect_errors': '655360',
        'back_log': '2048',
        'key_buffer_size': '33554432',
        'max_binlog_size': '100M',
        'character_set_server': 'utf8mb4',
        'collation_server': version.default_collation,
        'skip_name_resolve': 'ON',
        'log_bin_trust_function_creators': '1',
        'sync_relay_log': '1000',
    }

    # Replica naming / skip start
    if version.uses_source_replica_names:
        p['log_replica_updates'] = 'ON'
        p['skip_replica_start'] = 'ON'
        p['sync_source_info'] = '1000'
        if version.has_slave_parallel_logical_clock:
            p['replica_parallel_type'] = 'LOGICAL_CLOCK'
            p['replica_parallel_workers'] = '64'
    else:
        p['log_slave_updates'] = 'ON'
        p['skip_slave_start'] = 'ON'
        p['sync_master_info'] = '1000'
        p['sync_relay_log_info'] = '1000'
        # TABLE repos: valid through 5.7/early 8.0; ignored/warned later
        if version.major < 8 or (version.major == 8 and version.minor == 0 and version.patch < 26):
            p['master_info_repository'] = 'TABLE'
            p['relay_log_info_repository'] = 'TABLE'
        if version.has_slave_parallel_logical_clock:
            p['slave_parallel_type'] = 'LOGICAL_CLOCK'
            p['slave_parallel_workers'] = '64'
        elif version.family == '5.6':
            # 5.6: database parallel only
            p['slave_parallel_workers'] = '4'

    if version.uses_binlog_expire_seconds:
        p['binlog_expire_logs_seconds'] = '86400'
    else:
        p['expire_logs_days'] = '1'

    if version.has_query_cache:
        p['query_cache_type'] = 'OFF'
        p['query_cache_size'] = '0'

    if version.has_mysqlx:
        p['mysqlx'] = 'OFF'

    return p


def apply_memory_params(version: MysqlVersion, buffer_pool: int,
                        format_size, align_down) -> Dict[str, str]:
    """InnoDB memory knobs respecting redo-log variable rename."""
    params: Dict[str, str] = {
        'innodb_buffer_pool_size': format_size(buffer_pool),
    }
    pool_gb = max(1, buffer_pool // (1024 ** 3))
    instances = 2 if pool_gb < 8 else min(8, pool_gb)
    # 5.6 buffer pool instances only meaningfully >1 for large pools
    if version.family == '5.6' and pool_gb < 2:
        instances = 1
    params['innodb_buffer_pool_instances'] = str(instances)

    redo = max(256 * 1024 * 1024, min(4 * 1024 ** 3, buffer_pool // 4))
    redo = align_down(redo, 16 * 1024 * 1024)
    if version.uses_innodb_redo_log_capacity:
        params['innodb_redo_log_capacity'] = format_size(redo)
    else:
        # Classic pair: file size + files (default 2 → total ≈ 2 * file)
        file_size = max(128 * 1024 * 1024, min(2 * 1024 ** 3, redo // 2))
        file_size = align_down(file_size, 16 * 1024 * 1024)
        params['innodb_log_file_size'] = format_size(file_size)
        params['innodb_log_files_in_group'] = '2'

    params['innodb_io_capacity'] = '2000'
    params['innodb_io_capacity_max'] = '4000'
    if version.major >= 5 and not (version.major == 5 and version.minor < 7):
        params['innodb_read_io_threads'] = '4'
        params['innodb_write_io_threads'] = '4'

    if buffer_pool >= 8 * 1024 ** 3:
        params['max_connections'] = '1000'
    elif buffer_pool >= 2 * 1024 ** 3:
        params['max_connections'] = '500'
    else:
        params['max_connections'] = '200'
    return params


def apply_mgr_params(version: MysqlVersion, group_name: str,
                     local_host: str, mysql_port: int, seeds: str,
                     nodes: int) -> Dict[str, str]:
    if not version.has_mgr:
        raise ValueError(f'MGR is not supported on MySQL {version} (need 5.7.17+/8.0+)')
    mgr_port = mysql_port + 10
    params: Dict[str, str] = {
        'group_replication_group_name': group_name,
        'loose-group_replication_start_on_boot': 'OFF',
        'loose-group_replication_bootstrap_group': 'OFF',
        'loose-group_replication_single_primary_mode': 'ON',
        'loose-group_replication_local_address': f'{local_host}:{mgr_port}',
        'loose-group_replication_group_seeds': seeds,
        'loose-group_replication_ip_allowlist': '127.0.0.1/32,::1/128',
        'loose-group_replication_recovery_use_ssl': 'OFF',
        'binlog_checksum': 'NONE',
        'cluster_size': str(nodes),
    }
    # WRITESET dependency tracking: 8.0+ preferred; 5.7 uses different knobs
    if version.major >= 8:
        params['loose-binlog_transaction_dependency_tracking'] = 'WRITESET'
        params['transaction_write_set_extraction'] = 'XXHASH64'
    else:
        params['transaction_write_set_extraction'] = 'XXHASH64'
    return params


def build_mysqld_parameters(
        version: MysqlVersion,
        *,
        mode: str,
        nodes: int,
        buffer_pool: int,
        format_size,
        align_down,
        timeout_infinite_ms: int,
        timeout_two_node_ms: int,
        group_name: str = '',
        local_host: str = '127.0.0.1',
        mysql_port: int = 3306,
        seeds: str = '') -> Dict[str, str]:
    """Assemble full ``mysql.parameters`` dict for initcmd."""
    params = build_base_parameters(version)
    params.update(apply_memory_params(version, buffer_pool, format_size, align_down))

    if mode == 'semi-sync':
        timeout = timeout_infinite_ms if nodes >= 3 else timeout_two_node_ms
        wait_count = max(1, (nodes - 1) // 2)
        params.update(apply_semi_sync_params(version, nodes, timeout, wait_count))
    elif mode == 'mgr':
        params.update(apply_mgr_params(
            version, group_name, local_host, mysql_port, seeds, nodes))

    return params


def version_summary(version: MysqlVersion) -> Dict[str, Any]:
    return {
        'version': str(version),
        'family': version.family,
        'source_replica_names': version.uses_source_replica_names,
        'innodb_redo_log_capacity': version.uses_innodb_redo_log_capacity,
        'binlog_expire_seconds': version.uses_binlog_expire_seconds,
        'query_cache': version.has_query_cache,
        'mgr_capable': version.has_mgr,
        'semi_sync_plugins': list(semi_sync_plugin_names(version)),
    }
