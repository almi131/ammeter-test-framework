import socket
import threading
import time
import random
from abc import ABC, abstractmethod

NotImplementedErrorMsg = "Subclasses must implement this property."


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
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # allow quick restarts (TIME_WAIT)
            s.bind(('localhost', self.port))
            s.listen()
            s.settimeout(0.5)
            print(f"{self.__class__.__name__} is running on port {self.port}")
            while not self._stop.is_set():
                try:
                    conn, addr = s.accept()
                except socket.timeout:
                    continue
                if self._stop.is_set():
                    conn.close()
                    break
                with conn:
                    print(f"Connected by {addr}")
                    data = conn.recv(1024)
                    if data == self.get_current_command:
                        # Call the specific measure_current() method defined in subclasses
                        current = self.measure_current()
                        conn.sendall(str(current).encode('utf-8'))

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

