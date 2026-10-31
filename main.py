import sys
import threading

# Windows PowerShell defaults stdout to cp1252, which cannot encode the ohm symbol printed by Greenlee's measure_current.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

from Ammeters.base_ammeter import wait_until_accepting
from Ammeters.Circutor_Ammeter import CircutorAmmeter
from Ammeters.Entes_Ammeter import EntesAmmeter
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter
from Ammeters.client import request_current_from_ammeter

# region agent log
import sys as _dbg_sys
import traceback as _dbg_tb
from Ammeters.base_ammeter import _dbg as _base_dbg

def _dbg_excepthook(args):
    _base_dbg("main.excepthook", "thread died",
              thread=getattr(args.thread, "name", "?"),
              exc_type=args.exc_type.__name__,
              exc=str(args.exc_value),
              tb="".join(_dbg_tb.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))
    _dbg_sys.__excepthook__(args.exc_type, args.exc_value, args.exc_traceback)

threading.excepthook = _dbg_excepthook
# endregion


def run_greenlee_emulator():
    greenlee = GreenleeAmmeter(5001)
    greenlee.start_server()

def run_entes_emulator():
    entes = EntesAmmeter(5002)
    entes.start_server()

def run_circutor_emulator():
    circutor = CircutorAmmeter(5003)
    circutor.start_server()

if __name__ == "__main__":
    threading.Thread(target=run_greenlee_emulator, daemon=True).start()
    threading.Thread(target=run_entes_emulator, daemon=True).start()
    threading.Thread(target=run_circutor_emulator, daemon=True).start()

    for port in (5001, 5002, 5003):
        wait_until_accepting("localhost", port)

    try:
        request_current_from_ammeter(
            5001,
            b'MEASURE_GREENLEE -get_measurement'
        )

        request_current_from_ammeter(
            5002,
            b'MEASURE_ENTES -get_data'
        )

        request_current_from_ammeter(
            5003,
            b'MEASURE_CIRCUTOR -get_measurement -current'
        )
    except BaseException as _client_exc:  # instrumentation only
        # region agent log
        _base_dbg("main.client", "request raised",
                  exc_type=type(_client_exc).__name__, exc=str(_client_exc),
                  tb=_dbg_tb.format_exc())
        # endregion
        raise