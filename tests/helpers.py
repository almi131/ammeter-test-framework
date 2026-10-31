"""Shared test data and helpers."""
import contextlib
import socket
import threading
import time

from Ammeters.Circutor_Ammeter import CircutorAmmeter
from Ammeters.Entes_Ammeter import EntesAmmeter
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter
from Ammeters.client import request_current_from_ammeter

def fake_reader(values):
    """Reader that returns the given values one by one."""
    it = iter(values)
    return lambda: next(it)


def serve_once(reply, hold=0.0):
    """One-shot TCP server on a free port; sends `reply` (None = close silently) after `hold` s."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)

    def run():
        conn, _ = srv.accept()
        with conn:
            conn.recv(1024)
            if hold:
                threading.Event().wait(hold)
            if reply is not None:
                try:
                    conn.sendall(reply)
                except OSError:
                    pass  # client already gave up (timeout test)
        srv.close()

    threading.Thread(target=run, daemon=True).start()
    return srv.getsockname()[1]


def ask(port, **kwargs):
    return request_current_from_ammeter(port, b"X", host="127.0.0.1", verbose=False, **kwargs)


METERS = (
    ("greenlee", GreenleeAmmeter, "MEASURE_GREENLEE -get_measurement"),
    ("entes", EntesAmmeter, "MEASURE_ENTES -get_data"),
    ("circutor", CircutorAmmeter, "MEASURE_CIRCUTOR -get_measurement -current"),
)


class ManualClock:
    """Clock that jumps to each sample deadline. Sampling tests use it so they do not sleep."""

    def __init__(self, start=0.0):
        self.t = start

    def __call__(self):
        return self.t

    def advance_to(self, deadline):
        if deadline > self.t:
            self.t = deadline


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("localhost", 0))
        return s.getsockname()[1]


def serve_holding(hold, accepts=4):
    """Accept `accepts` clients and stay silent for `hold` seconds each."""
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(accepts)

    def run():
        for _ in range(accepts):
            try:
                conn, _ = srv.accept()
            except OSError:
                break
            with conn:
                try:
                    conn.recv(1024)
                except OSError:
                    pass
                threading.Event().wait(hold)
        srv.close()

    threading.Thread(target=run, daemon=True).start()
    return srv.getsockname()[1]


@contextlib.contextmanager
def running_emulator(cls):
    """Start one emulator on a free port and stop it when the block ends."""
    port = free_port()
    emu = cls(port)
    thread = threading.Thread(target=emu.start_server, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    last_error = None
    while time.monotonic() < deadline:
        try:
            socket.create_connection(("localhost", port), timeout=0.2).close()
            break
        except OSError as exc:
            last_error = exc
            time.sleep(0.05)
    else:
        emu.stop()
        raise RuntimeError(f"{cls.__name__} did not start on port {port}: {last_error}")
    try:
        yield emu
    finally:
        emu.stop()
        thread.join(timeout=2)
        if thread.is_alive():
            raise RuntimeError(f"{cls.__name__} did not stop")
