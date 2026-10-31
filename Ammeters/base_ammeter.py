import socket
import threading
import time
import random
from abc import ABC, abstractmethod

NotImplementedErrorMsg = "Subclasses must implement this property."

# region agent log
import json as _dbg_json
import os as _dbg_os
import sys as _dbg_sys
import traceback as _dbg_tb
_DBG_PATH = _dbg_os.path.join(_dbg_os.path.dirname(_dbg_os.path.dirname(_dbg_os.path.abspath(__file__))), "emulator-debug.log")
_DBG_LOCK = threading.Lock()

def _dbg(location, message, **data):
    entry = {
        "ts": time.time(),
        "thread": threading.current_thread().name,
        "location": location,
        "message": message,
        **data,
    }
    try:
        with _DBG_LOCK:
            with open(_DBG_PATH, "a", encoding="utf-8") as fh:
                fh.write(_dbg_json.dumps(entry, default=repr) + "\n")
    except OSError:
        pass
# endregion


def wait_until_accepting(host, port, timeout=10, name=None):
    """Return once something accepts TCP connections, or raise if the wait expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            socket.create_connection((host, port), timeout=0.5).close()
            return
        except OSError:
            time.sleep(0.05)
    label = name or f"{host}:{port}"
    raise RuntimeError(f"Emulator '{label}' not reachable on {host}:{port}")

class AmmeterEmulatorBase(ABC):
    def __init__(self, port: int):
        self.port = port
        self._stop = threading.Event()
        random.seed(time.time())  # Seed the random number generator for each instance

    def stop(self):
        """Unblock the accept loop so the listening port can be released."""
        self._stop.set()
        try:
            socket.create_connection(("localhost", self.port), timeout=1).close()
        except OSError:
            pass

    def start_server(self):
        """
        Starts the server to listen for client requests.
        The server handles one client at a time until stop() is called.
        """
        # region agent log
        _dbg("base_ammeter.start_server", "enter", hypothesisId="H3", port=self.port, cls=type(self).__name__)
        # endregion
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # allow quick restarts (TIME_WAIT)
                s.bind(('localhost', self.port))
                s.listen()
                s.settimeout(0.5)
                # region agent log
                _dbg("base_ammeter.start_server", "listening", hypothesisId="H3", bound=s.getsockname())
                # endregion
                print(f"{self.__class__.__name__} is running on port {self.port}")
                while not self._stop.is_set():
                    try:
                        conn, addr = s.accept()
                    except socket.timeout:
                        continue
                    # region agent log
                    _dbg("base_ammeter.start_server", "accepted", hypothesisId="H1", addr=addr)
                    # endregion
                    if self._stop.is_set():
                        conn.close()
                        break
                    with conn:
                        print(f"Connected by {addr}")
                        try:
                            data = conn.recv(1024)
                        except OSError as recv_exc:
                            # region agent log
                            _dbg("base_ammeter.start_server", "recv raised OSError", hypothesisId="H1",
                                 addr=addr, exc_type=type(recv_exc).__name__, exc=str(recv_exc))
                            # endregion
                            continue  # Windows resets a client that connects and closes, such as the readiness probe
                        except BaseException as recv_exc:  # instrumentation only: see H1
                            # region agent log
                            _dbg("base_ammeter.start_server", "recv raised non-OSError", hypothesisId="H1",
                                 addr=addr, exc_type=type(recv_exc).__name__, exc=str(recv_exc),
                                 tb=_dbg_tb.format_exc())
                            # endregion
                            raise
                        # region agent log
                        _dbg("base_ammeter.start_server", "recv returned",
                             hypothesisId="H4", addr=addr, nbytes=len(data), head=data[:64],
                             matches=(data == self.get_current_command))
                        # endregion
                        if data == self.get_current_command:
                            current = self.measure_current()
                            try:
                                conn.sendall(str(current).encode('utf-8'))
                                # region agent log
                                _dbg("base_ammeter.start_server", "sendall ok", hypothesisId="H2",
                                     addr=addr, value=current)
                                # endregion
                            except BaseException as send_exc:  # instrumentation only: see H2
                                # region agent log
                                _dbg("base_ammeter.start_server", "sendall raised", hypothesisId="H2",
                                     addr=addr, exc_type=type(send_exc).__name__, exc=str(send_exc),
                                     tb=_dbg_tb.format_exc())
                                # endregion
                                raise
        except BaseException as fatal:
            # region agent log
            _dbg("base_ammeter.start_server", "fatal", hypothesisId="H3",
                 exc_type=type(fatal).__name__, exc=str(fatal), tb=_dbg_tb.format_exc())
            # endregion
            raise

    @property
    @abstractmethod
    def get_current_command(self) -> bytes:
        """
        This property must be implemented by each subclass to provide the specific
        command to get the current measurement.
        """
        raise NotImplementedError(NotImplementedErrorMsg)

    @abstractmethod
    def measure_current(self) -> float:
        """
        This method must be implemented by each subclass to provide the specific
        logic for current measurement.
        """
        raise NotImplementedError(NotImplementedErrorMsg)

