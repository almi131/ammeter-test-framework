import math
import socket

DEFAULT_TIMEOUT = 5.0
MAX_REPLY_BYTES = 1024


class AmmeterError(Exception):
    """Base class for ammeter client errors."""


class AmmeterConnectionError(AmmeterError):
    """Server unreachable or connection refused/reset."""


class AmmeterTimeoutError(AmmeterError):
    """Connect or read timed out."""


class AmmeterNoReplyError(AmmeterError):
    """Server closed the connection without sending data."""


class AmmeterParseError(AmmeterError):
    """Reply is not a valid finite number (or is too large)."""


def request_current_from_ammeter(port: int, command: bytes, host: str = 'localhost',
                                 timeout: float = DEFAULT_TIMEOUT, verbose: bool = True) -> float:
    """Send a command to an ammeter emulator and return the current in amps.

    The reply ends when the server closes the connection; `timeout` applies to each socket operation.
    """
    where = f"{host}:{port}"
    chunks = []
    size = 0
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((host, port))
            s.sendall(command)
            while True:
                chunk = s.recv(1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_REPLY_BYTES:
                    raise AmmeterParseError(f"Reply from {where} too large (over {MAX_REPLY_BYTES} bytes)")
                chunks.append(chunk)
    except socket.timeout as e:
        raise AmmeterTimeoutError(f"Timed out after {timeout}s talking to {where}") from e
    except ConnectionRefusedError as e:
        raise AmmeterConnectionError(f"Connection refused by {where} (is the emulator running?)") from e
    except OSError as e:
        raise AmmeterConnectionError(f"Connection error with {where}: {e}") from e

    data = b"".join(chunks)
    if not data:
        raise AmmeterNoReplyError(f"No reply from {where} (unknown command {command!r}?)")

    try:
        text = data.decode('utf-8').strip()
        value = float(text)
        if not math.isfinite(value):
            raise ValueError("non-finite value")
    except ValueError as e:  # UnicodeDecodeError is a ValueError
        raise AmmeterParseError(f"Unparsable reply from {where}: {data!r}") from e

    if verbose:
        print(f"Received current measurement from port {port}: {text} A")
    return value
