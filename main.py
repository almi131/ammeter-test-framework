import threading

from Ammeters.base_ammeter import wait_until_accepting
from Ammeters.Circutor_Ammeter import CircutorAmmeter
from Ammeters.Entes_Ammeter import EntesAmmeter
from Ammeters.Greenlee_Ammeter import GreenleeAmmeter
from Ammeters.client import request_current_from_ammeter


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