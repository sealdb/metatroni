import logging
import os
import signal
import subprocess
import time

from typing import Dict, List, Optional

import psutil

logger = logging.getLogger(__name__)


class MySQLProcess:
    """Wraps a mysqld process for management by Patroni."""

    def __init__(self, pid: int):
        self._process = psutil.Process(pid)

    @staticmethod
    def from_pidfile(pid_file: str) -> Optional['MySQLProcess']:
        try:
            with open(pid_file) as f:
                pid_str = f.read().strip()
                if pid_str:
                    pid = int(pid_str)
                    proc = psutil.Process(pid)
                    if proc.is_running() and 'mysqld' in proc.name():
                        return MySQLProcess(pid)
        except (IOError, ValueError, psutil.NoSuchProcess):
            return None
        return None

    @staticmethod
    def from_pid(pid: int) -> Optional['MySQLProcess']:
        try:
            proc = psutil.Process(pid)
            if proc.is_running():
                return MySQLProcess(pid)
        except psutil.NoSuchProcess:
            pass
        return None

    def is_running(self) -> bool:
        try:
            return self._process.is_running()
        except psutil.NoSuchProcess:
            return False

    def signal_stop(self, mode: str = 'fast') -> Optional[bool]:
        """Stop the MySQL process.

        :param mode: 'fast' (SIGTERM -> wait), 'immediate' (SIGKILL)
        :returns: None if signaled, True if already gone, False if error
        """
        try:
            if mode == 'immediate':
                self._process.kill()
            else:
                self._process.terminate()
        except psutil.NoSuchProcess:
            return True
        except psutil.AccessDenied as e:
            logger.warning("Could not send stop signal to MySQL: %r", e)
            return False
        return None

    def wait_for_stop(self, timeout: float = 30) -> bool:
        try:
            self._process.wait(timeout=timeout)
            return True
        except psutil.TimeoutExpired:
            logger.warning("MySQL did not stop within %s seconds", timeout)
            return False
        except psutil.NoSuchProcess:
            return True

    @staticmethod
    def start(mysqld_path: str, defaults_file: str, data_dir: str,
              options: Optional[List[str]] = None) -> Optional['MySQLProcess']:
        """Start mysqld with the given configuration."""
        cmdline = [mysqld_path, f'--defaults-file={defaults_file}',
                   f'--datadir={data_dir}', '--daemonize']
        if options:
            cmdline.extend(options)

        logger.info("Starting MySQL: %s", " ".join(cmdline))
        try:
            proc = subprocess.Popen(cmdline, close_fds=True)
            proc.wait()
            pid_file = os.path.join(data_dir, 'mysqld.pid')
            for _ in range(10):
                proc = MySQLProcess.from_pidfile(pid_file)
                if proc:
                    return proc
                time.sleep(1)
        except OSError as e:
            logger.error("Failed to start MySQL: %r", e)
        return None

    def wait_for_ready(self, socket_path: str, timeout: float = 30) -> bool:
        import socket as sock_module
        start = time.time()
        while time.time() - start < timeout:
            try:
                s = sock_module.socket(sock_module.AF_UNIX, sock_module.SOCK_STREAM)
                s.settimeout(2)
                s.connect(socket_path)
                s.close()
                return True
            except (FileNotFoundError, ConnectionRefusedError, OSError):
                time.sleep(0.5)
        return False

    def signal_kill(self) -> bool:
        """Kill MySQL process and all children."""
        try:
            children = self._process.children(recursive=True)
        except psutil.NoSuchProcess:
            return True
        except psutil.Error:
            children = []

        try:
            self._process.kill()
        except psutil.NoSuchProcess:
            return True
        except psutil.Error:
            return False

        for child in children:
            try:
                child.kill()
            except psutil.Error:
                pass
        psutil.wait_procs(children + [self._process])
        return True
