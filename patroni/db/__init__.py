"""Abstract Database Handler interface for Patroni.

This module defines the abstract base class that all database backends
(PostgreSQL, MySQL, etc.) must implement to be managed by Patroni's HA loop.
"""

import abc
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from ..dcs import Leader, Member, RemoteMember


class DatabaseHandler(abc.ABC):
    """Abstract interface for database backends managed by Patroni."""

    # --- Properties ---

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Node name."""

    @property
    @abc.abstractmethod
    def role(self) -> str:
        """Current database role (e.g., 'primary', 'replica')."""

    @property
    @abc.abstractmethod
    def state(self) -> str:
        """Current database state (e.g., 'running', 'stopped', 'starting')."""

    @property
    @abc.abstractmethod
    def connection_string(self) -> str:
        """Connection URL for other nodes to reach this database."""

    @property
    @abc.abstractmethod
    def proxy_url(self) -> Optional[str]:
        """Optional proxy URL for routing connections."""

    @property
    @abc.abstractmethod
    def pending_restart_reason(self) -> Dict[str, Any]:
        """Reasons a restart is pending, if any."""

    @abc.abstractmethod
    def data_directory_empty(self) -> bool:
        """Whether the data directory is empty."""

    @property
    @abc.abstractmethod
    def server_version(self) -> int:
        """Server version as integer (e.g., 80031 for MySQL 8.0.31)."""

    @property
    @abc.abstractmethod
    def sysid(self) -> Optional[str]:
        """Database system identifier, if applicable."""

    # --- Lifecycle Methods ---

    @abc.abstractmethod
    def start(self, timeout: Optional[int] = None,
              task: Optional[Any] = None,
              block_callbacks: bool = True) -> bool:
        """Start the database instance."""

    @abc.abstractmethod
    def stop(self, mode: str = 'fast', block_callbacks: bool = True,
             check_executor: bool = True) -> bool:
        """Stop the database instance."""

    @abc.abstractmethod
    def restart(self) -> bool:
        """Restart the database instance."""

    @abc.abstractmethod
    def reload(self) -> None:
        """Reload database configuration."""

    @abc.abstractmethod
    def reload_config(self, config: Dict[str, Any], sighup: bool = False) -> None:
        """Reload configuration from Patroni config."""

    # --- Role Management ---

    @abc.abstractmethod
    def promote(self, loop_wait: float,
                async_response: Optional[Any] = None,
                before_promote: Optional[Callable[[], None]] = None) -> bool:
        """Promote this node to primary/leader."""

    @abc.abstractmethod
    def demote(self) -> bool:
        """Demote this node from primary to replica."""

    @abc.abstractmethod
    def follow(self, node_to_follow: Union[Leader, Member, RemoteMember, None],
               role: Optional[str] = None,
               do_reload: bool = False) -> Optional[bool]:
        """Configure this node to follow a leader."""

    @abc.abstractmethod
    def set_role(self, role: str) -> None:
        """Set the current role."""

    # --- State Checks ---

    @abc.abstractmethod
    def is_running(self) -> bool:
        """Whether the database process is running."""

    @abc.abstractmethod
    def is_primary(self) -> bool:
        """Whether this node is a primary/leader."""

    @abc.abstractmethod
    def is_healthy(self) -> bool:
        """Whether the database is healthy."""

    @abc.abstractmethod
    def is_starting(self) -> bool:
        """Whether the database is in the process of starting."""

    # --- Replication / Position Info ---

    @abc.abstractmethod
    def last_operation(self) -> int:
        """Return the last operation position (WAL/binlog/GTID as integer)."""

    @abc.abstractmethod
    def timeline_wal_position(self) -> Tuple[Optional[int], int, int, int, int]:
        """Return timeline (or equivalent), write_position, control_timeline, receive_position, replay_position.

        For databases without timelines (MySQL), the timeline value is always 0
        or None and positions refer to binlog positions.
        """

    @abc.abstractmethod
    def replication_state(self) -> Optional[str]:
        """Return the current replication state (e.g., 'streaming', 'connecting')."""

    @abc.abstractmethod
    def received_timeline(self) -> Optional[int]:
        """Return the timeline from replication receiver. 0/None if N/A."""

    @abc.abstractmethod
    def replica_cached_timeline(self, leader_timeline: Optional[int]) -> Optional[int]:
        """Return cached timeline for a replica."""

    @abc.abstractmethod
    def pg_control_timeline(self) -> Optional[int]:
        """Return timeline from control data. 0/None if N/A."""

    @abc.abstractmethod
    def get_primary_timeline(self) -> Optional[int]:
        """Get primary timeline. 0/None if N/A."""

    @abc.abstractmethod
    def get_history(self, timeline: int) -> List[Any]:
        """Get history entries for a given timeline."""

    # --- Bootstrap / Clone ---

    @abc.abstractmethod
    def can_create_replica_without_replication_connection(
            self, create_replica_methods: Optional[List[str]] = None) -> bool:
        """Whether a replica can be created without a direct replication connection."""

    @abc.abstractmethod
    def remove_data_directory(self) -> None:
        """Remove the data directory."""

    @abc.abstractmethod
    def move_data_directory(self) -> None:
        """Move the data directory (e.g., on failed start)."""

    @abc.abstractmethod
    def was_restored_from_backup(self) -> bool:
        """Whether the data directory was restored from backup."""

    @abc.abstractmethod
    def controldata(self) -> Dict[str, Any]:
        """Return control data / metadata about the database instance."""

    @abc.abstractmethod
    def slots(self) -> Dict[str, int]:
        """Return replication slot information (or equivalent)."""

    # --- Parameter Management ---

    @abc.abstractmethod
    def handle_parameter_change(self) -> bool:
        """Handle dynamic parameter changes. Returns True if restart is needed."""

    @abc.abstractmethod
    def set_state(self, state: str) -> None:
        """Set the current state."""

    @abc.abstractmethod
    def check_for_startup(self) -> None:
        """Check if the database has started up."""

    @abc.abstractmethod
    def terminate_starting_postmaster(self) -> None:
        """Terminate a database that's in the starting state."""

    @abc.abstractmethod
    def call_nowait(self, action: Any, *args: Any, **kwargs: Any) -> None:
        """Execute a callback action without waiting."""

    @abc.abstractmethod
    def schedule_sanity_checks_after_pause(self) -> None:
        """Schedule sanity checks after maintenance mode."""

    @abc.abstractmethod
    def reset_cluster_info_state(self, state: Optional[str]) -> None:
        """Reset cluster info state."""

    @abc.abstractmethod
    def latest_checkpoint_locations(self) -> Tuple[Optional[int], Optional[int]]:
        """Get latest checkpoint location information.

        :returns: a tuple of ``(checkpoint_lsn, restart_lsn)``, both ``None`` if not applicable.
        """


def get_db_handler(config: Dict[str, Any], dcs_mpp: Any = None) -> 'DatabaseHandler':
    """Factory function to get the appropriate database handler.

    :param config: The database configuration section.
    :param dcs_mpp: Optional MPP handler.
    :returns: A DatabaseHandler implementation instance.
    """
    from ..config import Config
    if isinstance(config, Config):
        db_type = config.get('database', {}).get('type', 'postgresql')
    else:
        db_type = config.get('database', {}).get('type', 'postgresql') if config else 'postgresql'

    if db_type == 'postgresql':
        from ..postgresql import Postgresql
        return Postgresql(config['postgresql'], dcs_mpp)
    elif db_type == 'mysql':
        from ..mysql import MySQL
        return MySQL(config['mysql'], dcs_mpp)
    else:
        raise ValueError(f"Unsupported database type: {db_type}")
