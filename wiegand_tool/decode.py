"""Decodificacion e identificacion de formatos a partir de una trama leida.

Dada la trama de bits que entrega un lector Wiegand (via el Arduino), prueba
cada formato conocido: valida las paridades, extrae site/card y el valor crudo,
y determina cual formato calza con el numero impreso en la tarjeta.

La trama se representa como un string de '0'/'1', MSB primero (el primer bit que
transmite el lector es el mas significativo), de largo == Card_Bit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from .core import WiegandFormat


class DecodeError(ValueError):
    pass


def bits_from_hex(hex_str: str, card_bit: int) -> str:
    """Convierte un valor hex (ej. '0x2004060' o '2004060') a bits MSB-first.

    Rellena o recorta a ``card_bit`` bits (el lector a veces no incluye ceros a
    la izquierda).
    """
    h = hex_str.strip().lower().replace("0x", "").replace(" ", "")
    if not h:
        raise DecodeError("hex vacio")
    try:
        value = int(h, 16)
    except ValueError as exc:
        raise DecodeError(f"hex invalido: {hex_str!r}") from exc
    return bits_from_int(value, card_bit)


def bits_from_int(value: int, card_bit: int) -> str:
    if value < 0:
        raise DecodeError("valor negativo")
    if value >= (1 << card_bit):
        raise DecodeError(f"el valor no cabe en {card_bit} bits")
    return format(value, f"0{card_bit}b")


def normalize_bits(raw: str) -> str:
    """Limpia una cadena de bits (quita espacios/guiones); valida 0/1."""
    b = "".join(c for c in raw.strip() if c not in " _-")
    if not b or any(c not in "01" for c in b):
        raise DecodeError("la trama debe ser solo 0 y 1")
    return b


@dataclass
class Decoded:
    name: str
    card_bit: int
    parity_ok: bool
    site: Optional[int]
    card: Optional[int]
    raw_decimal: int
    fields: Dict[str, Optional[int]]
    # marcas de coincidencia con el numero buscado (si se dio uno)
    match_card: bool = False
    match_site: bool = False
    match_raw: bool = False

    @property
    def match(self) -> bool:
        return self.match_card or self.match_site or self.match_raw


def _field_value(bits: str, card_format: str, ch: str) -> Optional[int]:
    positions = [i for i, c in enumerate(card_format) if c == ch]
    if not positions:
        return None
    return int("".join(bits[p] for p in positions), 2)


def check_parities(fmt: WiegandFormat, bits: str) -> bool:
    """True si todas las paridades del formato cuadran con la trama."""
    cf = fmt.card_format
    counts = {"even": 0, "odd": 0}
    for p in fmt.parities:
        order = counts[p.kind]
        counts[p.kind] += 1
        ones = sum(1 for idx in p.covers if bits[idx] == "1")
        esperado = (ones % 2) if p.kind == "even" else (0 if ones % 2 else 1)
        target_char = "E" if p.kind == "even" else "O"
        pos = [i for i, c in enumerate(cf) if c == target_char][order]
        if bits[pos] != str(esperado):
            return False
    return True


def decode_frame(fmt: WiegandFormat, bits: str) -> Optional[Decoded]:
    """Decodifica la trama con un formato. None si el largo no coincide."""
    fmt.validate()
    if len(bits) != fmt.card_bit:
        return None
    parity_ok = check_parities(fmt, bits)
    fields = {ch: _field_value(bits, fmt.card_format, ch) for ch in ("S", "C", "F", "M")}
    return Decoded(
        name=fmt.name,
        card_bit=fmt.card_bit,
        parity_ok=parity_ok,
        site=fields["S"],
        card=fields["C"],
        raw_decimal=int(bits, 2),
        fields={k: v for k, v in fields.items() if v is not None},
    )


def identify(
    bits: str, formats: List[WiegandFormat], target: Optional[int] = None
) -> List[Decoded]:
    """Prueba cada formato del mismo largo que la trama y marca coincidencias.

    target: el numero impreso en la tarjeta a buscar (opcional). Se marca el
    formato cuyo card (o site, o valor crudo) coincide con ese numero.
    Ordena primero los que coinciden, luego los de paridad valida.
    """
    bits = normalize_bits(bits)
    out: List[Decoded] = []
    for fmt in formats:
        d = decode_frame(fmt, bits)
        if d is None:
            continue
        if target is not None:
            d.match_card = d.card == target
            d.match_site = d.site == target
            d.match_raw = d.raw_decimal == target
        out.append(d)
    out.sort(key=lambda d: (d.match, d.parity_ok), reverse=True)
    return out
