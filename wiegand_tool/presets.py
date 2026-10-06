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
    """HID 35-bit Corporate 1000 (H10320 / C1000-35).

    Layout: 1 par (leading) + 12 company + 20 card + 2 trailing (par, impar).
    OJO: el esquema de paridad real de Corporate 1000 usa patrones intercalados
    y debe confirmarse contra un lector antes de usar en produccion. Aqui se
    deja el layout y una paridad par/impar basica como punto de partida.
    """
    cf = "E" + "S" * 12 + "C" * 20 + "E" + "O"
    data_idx = [i for i, c in enumerate(cf) if c in "SC"]
    half = len(data_idx) // 2
    return WiegandFormat(
        name=name,
        card_format=cf,
        parities=[
            Parity("even", data_idx[:half]),
            Parity("even", data_idx[half:]),
            Parity("odd", data_idx),
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
