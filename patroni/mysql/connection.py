import logging
import time

from threading import Lock
from typing import Any, Dict, List, Optional, Tuple, Union

from ..exceptions import PostgresConnectionException

logger = logging.getLogger(__name__)

try:
    import pymysql
    from pymysql.err import Error as MySQLdbError, OperationalError, DatabaseError
    HAS_MYSQL = True
except ImportError:
    HAS_MYSQL = False
    MySQLdbError = Exception
    OperationalError = Exception
    DatabaseError = Exception


class MySQLConnection:
    """A single MySQL connection wrapper."""

    def __init__(self, pool: 'ConnectionPool', name: str,
                 kwargs_override: Optional[Dict[str, Any]] = None):
        self._pool = pool
        self._name = name
        self._kwargs_override = kwargs_override or {}
        self._lock = Lock()
        self._connection = None
        self.server_version: int = 0

    @property
    def _conn_kwargs(self) -> Dict[str, Any]:
        kwargs = dict(self._pool.conn_kwargs)
        kwargs.update(self._kwargs_override)
        kwargs.setdefault('autocommit', True)
        return kwargs

    def get(self) -> Any:
        with self._lock:
            if not self._connection:
                logger.info("establishing a new patroni %s connection to mysql", self._name)
                kwargs = dict(self._conn_kwargs)
                kwargs.setdefault('autocommit', True)
                self._connection = pymysql.connect(**kwargs)
                # Avoid stale REPEATABLE READ snapshots on long-lived heartbeat
                # connections (e.g. after replica catch-up via a different session).
                with self._connection.cursor() as cursor:
                    cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
                    cursor.execute("SET autocommit = 1")
                ver = self._query_one("SELECT VERSION()")
                if ver:
                    from .misc import mysql_version_to_int
                    self.server_version = mysql_version_to_int(ver[0])
            else:
                try:
                    self._connection.ping(reconnect=False)
                except (MySQLdbError, AttributeError):
                    logger.info("re-establishing patroni %s connection to mysql", self._name)
                    try:
                        kwargs = dict(self._pool.conn_kwargs)
                        kwargs.update(self._kwargs_override)
                        kwargs.setdefault('autocommit', True)
                        self._connection = pymysql.connect(**kwargs)
                        with self._connection.cursor() as cursor:
                            cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
                            cursor.execute("SET autocommit = 1")
                    except MySQLdbError as e:
                        raise PostgresConnectionException(f'mysql connection failed: {e}')
            return self._connection

    def _query_one(self, sql: str, *params: Any) -> Optional[Tuple[Any, ...]]:
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(sql, params or None)
                return cursor.fetchone()
        except MySQLdbError:
            return None

    def query(self, sql: str, *params: Any) -> List[Tuple[Any, ...]]:
        cursor = None
        try:
            with self.get().cursor() as cursor:
                cursor.execute(sql, params or None)
                return cursor.fetchall()
        except MySQLdbError as exc:
            if cursor and not self._is_closed(cursor):
                if isinstance(exc, (DatabaseError, OperationalError)):
                    self.close()
                else:
                    raise exc
            raise PostgresConnectionException('connection problems') from exc

    def query_one_dict(self, sql: str, *params: Any) -> Optional[Dict[str, Any]]:
        """Execute a query and return the first row as a dict (column name -> value).

        Uses DictCursor for column-name-based access, useful for statements like
        ``SHOW SLAVE STATUS`` where column positions vary across MySQL versions.
        """
        try:
            conn = self.get()
            with conn.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute(sql, params or None)
                return cursor.fetchone()
        except MySQLdbError:
            return None

    def _is_closed(self, cursor: Any) -> bool:
        try:
            cursor.connection.ping(reconnect=False)
            return False
        except MySQLdbError:
            return True

    def close(self, silent: bool = False) -> bool:
        ret = False
        if self._connection:
            try:
                self._connection.close()
            except MySQLdbError:
                pass
            if not silent:
                logger.info("closed patroni %s connection to mysql", self._name)
            ret = True
        self._connection = None
        return ret

    def closed(self) -> bool:
        return self._connection is None


class ConnectionPool:
    """Manages multiple named MySQL connections."""

    def __init__(self, conn_kwargs: Optional[Dict[str, Any]] = None):
        self._conn_kwargs: Dict[str, Any] = conn_kwargs or {}
        self._connections: Dict[str, MySQLConnection] = {}

    @property
    def conn_kwargs(self) -> Dict[str, Any]:
        return self._conn_kwargs

    def set_conn_kwargs(self, kwargs: Dict[str, Any]) -> None:
        self._conn_kwargs = kwargs

    def get(self, name: str, kwargs_override: Optional[Dict[str, Any]] = None) -> MySQLConnection:
        if name not in self._connections:
            self._connections[name] = MySQLConnection(self, name, kwargs_override)
        return self._connections[name]

    def close(self) -> None:
        for conn in self._connections.values():
            conn.close(silent=True)
        self._connections.clear()
