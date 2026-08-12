import logging

from enum import Enum
from typing import Tuple

logger = logging.getLogger(__name__)


class MySQLState(str, Enum):
    """Possible values of MySQL.state."""

    CUSTOM_BOOTSTRAP = ('running custom bootstrap script', 0)
    CUSTOM_BOOTSTRAP_FAILED = ('custom bootstrap failed', 1)
    CREATING_REPLICA = ('creating replica', 2)
    RUNNING = ('running', 3)
    STARTING = ('starting', 4)
    BOOTSTRAP_STARTING = ('starting after custom bootstrap', 5)
    START_FAILED = ('start failed', 6)
    RESTARTING = ('restarting', 7)
    RESTART_FAILED = ('restart failed', 8)
    STOPPING = ('stopping', 9)
    STOPPED = ('stopped', 10)
    STOP_FAILED = ('stop failed', 11)
    CRASHED = ('crashed', 12)

    def __new__(cls, value: str, index: int) -> 'MySQLState':
        obj = str.__new__(cls, value)
        obj._value_ = value
        setattr(obj, 'index', index)
        return obj

    def __repr__(self) -> str:
        return self.value

    def __str__(self) -> str:
        return self.__repr__()


class MySQLRole(str, Enum):
    """Possible values of MySQL.role."""

    PRIMARY = 'primary'
    REPLICA = 'replica'
    STANDBY_LEADER = 'standby_leader'  # DCS lock holder in a standby cluster
    DEMOTED = 'demoted'
    UNINITIALIZED = 'uninitialized'
    PROMOTED = 'promoted'
    MGR_PRIMARY = 'mgr_primary'       # node is the MGR primary
    MGR_SECONDARY = 'mgr_secondary'   # node is an MGR secondary

    def __repr__(self) -> str:
        return self.value

    def __str__(self) -> str:
        return self.__repr__()


class CreateReplicaMethod(str, Enum):
    """Identifiers for ``mysql.create_replica_methods`` / standby clone.

    Prefer these over bare strings so rename/add is a single edit.
    Values match YAML / DCS configuration.
    """

    XTRABACKUP = 'xtrabackup'
    MYSQLDUMP = 'mysqldump'
    CLONE_PLUGIN = 'clone_plugin'  # reserved; not implemented in Phase 1

    def __repr__(self) -> str:
        return self.value

    def __str__(self) -> str:
        return self.__repr__()

    @classmethod
    def known(cls) -> frozenset:
        """Set of valid method name strings (YAML / DCS values)."""
        return frozenset(m.value for m in cls)


# Default order: physical first, logical fallback.
DEFAULT_CREATE_REPLICA_METHODS: Tuple[str, ...] = (
    CreateReplicaMethod.XTRABACKUP,
    CreateReplicaMethod.MYSQLDUMP,
)


class MGRMemberState(str, Enum):
    """Mirrors performance_schema.replication_group_members.MEMBER_STATE."""

    ONLINE = 'ONLINE'
    RECOVERING = 'RECOVERING'
    OFFLINE = 'OFFLINE'
    ERROR = 'ERROR'
    UNREACHABLE = 'UNREACHABLE'


class MGRMemberRole(str, Enum):
    """Mirrors performance_schema.replication_group_members.MEMBER_ROLE (MySQL 8.0+)."""

    PRIMARY = 'PRIMARY'
    SECONDARY = 'SECONDARY'


def parse_binlog_position(position_str: str) -> int:
    """Parse a MySQL binlog position string to integer.

    MySQL binlog positions are simple integer file offsets.
    For GTID-based positions, we return a hash of the GTID set.
    """
    try:
        return int(position_str)
    except (ValueError, TypeError):
        return 0


def mysql_version_to_int(version_str: str) -> int:
    """Convert MySQL version string to integer.

    >>> mysql_version_to_int('8.0.31')
    80031
    >>> mysql_version_to_int('5.7.40')
    50740
    >>> mysql_version_to_int('8.0.35-debug')
    80035
    """
    try:
        parts = version_str.split('.')
        major = int(parts[0])
        minor = int(parts[1])
        patch_part = parts[2].split('-')[0] if len(parts) > 2 else '0'
        return major * 10000 + minor * 100 + int(patch_part)
    except (ValueError, IndexError):
        return 0


def parse_gtid_set(gtid_set: str) -> str:
    """Normalize a GTID set string.

    GTID sets look like: 'uuid1:1-100,uuid2:200-300'
    """
    return gtid_set.strip()
