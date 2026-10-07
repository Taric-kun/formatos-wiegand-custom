"""Presets de formatos Wiegand estandar.

W26 esta confirmado contra una fila real del equipo. Los demas usan la
definicion estandar del formato (paridad par sobre la primera mitad de los
bits de datos, impar sobre la segunda) y son un punto de partida editable:
revisar las mascaras antes de cargarlos en un lector de produccion.
"""

from __future__ import annotations

from typing import Callable, Dict

from .core import Parity, WiegandFormat


def _even_odd_split(card_format: str) -> list:
    """Paridad par sobre la 1a mitad de los bits de datos, impar sobre la 2a.

    Convencion clasica estilo Wiegand26: el bit 'E' va al inicio y cubre la
    primera mitad de los bits entre paridades; el 'O' va al final y cubre la
    segunda mitad. Asume exactamente un 'E' y un 'O'.
    """
    data_idx = [i for i, c in enumerate(card_format) if c in "SCFM"]
    half = len(data_idx) // 2
    even = Parity("even", data_idx[:half])
    odd = Parity("odd", data_idx[half:])
    return [even, odd]


def w26(site_code: int = 0, name: str = "Wiegand26") -> WiegandFormat:
    """Wiegand 26 bits estandar (H10301). Confirmado contra el equipo."""
    cf = "ESSSSSSSSCCCCCCCCCCCCCCCCO"
    return WiegandFormat(
        name=name,
        card_format=cf,
        parities=[
            Parity("even", list(range(1, 13))),   # bits 1..12
            Parity("odd", list(range(13, 25))),    # bits 13..24
        ],
        site_code=site_code,
    )


def w34(site_code: int = 0, name: str = "Wiegand34") -> WiegandFormat:
    """34 bits: 1 par + 16 site + 16 card + 1 impar (split par/impar)."""
    cf = "E" + "S" * 16 + "C" * 16 + "O"
    return WiegandFormat(
        name=name, card_format=cf, parities=_even_odd_split(cf), site_code=site_code
    )


def w37(site_code: int = 0, name: str = "Wiegand37") -> WiegandFormat:
    """37 bits H10304: 1 par + 16 facility + 19 card + 1 impar.

    Paridad solapada estandar HID: par sobre los primeros 18 bits de datos,
    impar sobre los ultimos 18 (comparten el bit central).
    """
    cf = "E" + "S" * 16 + "C" * 19 + "O"
    data_idx = [i for i, c in enumerate(cf) if c in "SC"]
    even = Parity("even", data_idx[:18])
    odd = Parity("odd", data_idx[-18:])
    return WiegandFormat(name=name, card_format=cf, parities=[even, odd], site_code=site_code)


def hid35_corp1000(site_code: int = 0, name: str = "HIDCorp35") -> WiegandFormat:
    """HID 35-bit Corporate 1000 (C1000-35), segun la especificacion de HID.

    Layout (0-based): bit 0 impar, bit 1 par, 2..13 company (12 bits),
    14..33 numero de tarjeta (20 bits), bit 34 impar.
      - par  (bit 1):  bits 2,3,5,6,8,9,...,32,33 (2 de cada 3)
      - impar (bit 34): bits 1,2,4,5,7,8,...,31,32 (incluye el bit 1 de paridad)
      - impar (bit 0):  todos los demas (1..34, incluye los otros dos de paridad)
    El numero que lee el reloj es el de 20 bits (el impreso en la tarjeta).
    """
    cf = "OE" + "S" * 12 + "C" * 20 + "O"
    return WiegandFormat(
        name=name,
        card_format=cf,
        parities=[
            Parity("odd", list(range(1, 35))),                            # bit 0
            Parity("even", [i for i in range(2, 34) if (i - 1) % 3 != 0]),  # bit 1
            Parity("odd", [i for i in range(1, 33) if i % 3 != 0]),         # bit 34
        ],
        site_code=site_code,
    )


PRESETS: Dict[str, Callable[..., WiegandFormat]] = {
    "W26": w26,
    "W34": w34,
    "W37": w37,
    "HID35_Corp1000": hid35_corp1000,
}

# Metadatos para la GUI: cuales estan confirmados vs. a revisar.
PRESET_STATUS: Dict[str, str] = {
    "W26": "confirmado",
    "W34": "a revisar",
    "W37": "a revisar",
    "HID35_Corp1000": "a revisar",
}
