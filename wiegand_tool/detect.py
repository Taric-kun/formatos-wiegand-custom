"""Deteccion de formato Wiegand a partir de lecturas crudas + numero impreso.

Flujo: el Arduino (``arduino/wiegand_lector``) entrega la trama cruda de un
lector (``WG <nbits> <bits>``); el usuario escribe el numero impreso en la
tarjeta. Aqui se buscan las ventanas de bits cuyo valor coincide con ese
numero (card, o site+card), se arma el ``Card_Format`` resultante y se prueban
esquemas de paridad estandar. Devuelve candidatos ordenados por puntaje, listos
para cargarse en el editor.

Numero impreso aceptado (se extraen todos los enteros del texto):
  - ``12345``            -> solo numero de tarjeta
  - ``71,07104``         -> site/facility + tarjeta (tambien ``71-7104``, ``71:7104``)
  - ``0004660736 071,07104`` -> se prueban todas las combinaciones

Con varias tarjetas leidas, cada candidato se verifica contra todas: el que
decodifica bien todas (y con paridad correcta) queda primero.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .core import FormatError, Parity, WiegandFormat
from .presets import PRESETS

# Anchos de campo tarjeta habituales (W26=16, W37=19, Corp1000-35=20, ...).
COMMON_CARD_WIDTHS = (16, 19, 20, 24, 32)
MAX_CANDIDATES = 8
_LINE_RE = re.compile(r"^\s*WG\s+(\d+)\s+([01]+)")


class DetectError(ValueError):
    """Entrada invalida para la deteccion."""


# --------------------------------------------------------------------------- #
# Entrada
# --------------------------------------------------------------------------- #
def parse_reader_line(line: str) -> Optional[str]:
    """Extrae los bits de una linea ``WG <n> <bits> ...`` del Arduino."""
    m = _LINE_RE.match(line or "")
    if not m:
        return None
    n, bits = int(m.group(1)), m.group(2)
    if len(bits) != n:
        raise DetectError(f"la linea dice {n} bits pero trae {len(bits)}")
    return bits


def clean_bits(bits: str) -> str:
    """Acepta bits sueltos o una linea ``WG ...``; devuelve solo 0/1."""
    if bits is None:
        raise DetectError("lectura vacia")
    from_line = parse_reader_line(bits)
    b = from_line if from_line is not None else re.sub(r"\s+", "", bits)
    if not b or set(b) - {"0", "1"}:
        raise DetectError(f"la lectura debe ser solo 0/1: {bits!r}")
    if len(b) < 4:
        raise DetectError("la lectura tiene muy pocos bits")
    return b


def printed_targets(printed: str) -> List[Tuple[Optional[int], int]]:
    """Interpreta el numero impreso como objetivos (site|None, card).

    Primero los pares consecutivos (site, card), luego el ultimo numero solo
    (la tarjeta) y, si hay 3 o mas, tambien el primero.
    """
    nums = [int(x) for x in re.findall(r"\d+", printed or "")]
    if not nums:
        raise DetectError(f"no hay numeros en el texto impreso: {printed!r}")
    out: List[Tuple[Optional[int], int]] = []
    for a, b in zip(nums, nums[1:]):
        out.append((a, b))
    # Numero solo: el ultimo es la tarjeta. Con 3+ numeros el primero suele ser
    # el valor completo (p.ej. "0004660736 071,07104"), tambien se prueba.
    out.append((None, nums[-1]))
    if len(nums) >= 3:
        out.append((None, nums[0]))
    seen, uniq = set(), []
    for t in out:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


# --------------------------------------------------------------------------- #
# Decodificacion con un formato
# --------------------------------------------------------------------------- #
def decode(fmt: WiegandFormat, bits: str) -> Dict:
    """Lee site/card de una trama con el formato dado y valida sus paridades."""
    cf = fmt.card_format
    if len(bits) != len(cf):
        return {"ok_len": False, "site": None, "card": None, "parity_ok": False}

    def field_value(ch: str) -> Optional[int]:
        pos = [i for i, c in enumerate(cf) if c == ch]
        return int("".join(bits[i] for i in pos), 2) if pos else None

    return {
        "ok_len": True,
        "site": field_value("S"),
        "card": field_value("C"),
        "parity_ok": parity_ok(fmt, bits),
    }


def parity_ok(fmt: WiegandFormat, bits: str) -> bool:
    cf = fmt.card_format
    order = {"even": 0, "odd": 0}
    for p in fmt.parities:
        ch = "E" if p.kind == "even" else "O"
        own = [i for i, c in enumerate(cf) if c == ch][order[p.kind]]
        order[p.kind] += 1
        ones = sum(1 for i in p.covers if bits[i] == "1") + (bits[own] == "1")
        if p.kind == "even" and ones % 2 != 0:
            return False
        if p.kind == "odd" and ones % 2 != 1:
            return False
    return True


def _matches_targets(dec: Dict, targets) -> Optional[Tuple[Optional[int], int]]:
    for site, card in targets:
        if dec["card"] != card:
            continue
        if site is None or dec["site"] == site:
            return (site, card)
    return None


# --------------------------------------------------------------------------- #
# Busqueda de candidatos
# --------------------------------------------------------------------------- #
def _windows(bits: str, value: int) -> List[Tuple[int, int]]:
    """Ventanas minimas (inicio, fin inclusive) cuyo valor binario es ``value``."""
    width = max(1, value.bit_length())
    out = []
    for end in range(width - 1, len(bits)):
        start = end - width + 1
        if int(bits[start:end + 1], 2) == value:
            out.append((start, end))
    return out


def _zeros(bits: str, a: int, b: int) -> bool:
    """True si bits[a:b] son todos cero (rango vacio cuenta como cero)."""
    return "1" not in bits[a:b]


def _layouts(bits: str, site: Optional[int], card: int) -> List[Tuple[List[str], str]]:
    """Asignaciones de campos S/C sobre la trama. Devuelve (chars, nota)."""
    n = len(bits)
    res = []
    for cs, ce in _windows(bits, card):
        if site is not None:
            for ss, se in _windows(bits, site):
                # El site va antes de la tarjeta; el hueco se absorbe como ceros
                # a la izquierda de la tarjeta.
                if se >= cs or not _zeros(bits, se + 1, cs):
                    continue
                c_start = se + 1
                # Extiende el site hacia el bit 1 si lo que queda son ceros.
                s_start = 1 if ss >= 1 and _zeros(bits, 1, ss) else ss
                chars = ["0"] * n
                for i in range(s_start, se + 1):
                    chars[i] = "S"
                for i in range(c_start, ce + 1):
                    chars[i] = "C"
                for i in range(1, s_start):
                    chars[i] = "F"
                res.append((chars, "site+card"))
        else:
            starts = {cs}
            for w in COMMON_CARD_WIDTHS:
                s = ce - w + 1
                if 0 <= s <= cs and _zeros(bits, s, cs):
                    starts.add(s)
            if _zeros(bits, 0, cs):
                starts.add(0)
            if cs >= 1 and _zeros(bits, 1, cs):
                starts.add(1)
            for s in sorted(starts):
                chars = ["0"] * n
                for i in range(s, ce + 1):
                    chars[i] = "C"
                # Lo que queda antes de la tarjeta (sin el bit 0) se toma como site.
                for i in range(1, s):
                    chars[i] = "S"
                res.append((chars, "solo card"))
    return res


def _parity_schemes(chars: List[str]) -> List[Tuple[str, str, List[Parity]]]:
    """Esquemas de paridad a probar para un layout. (nombre, card_format, paridades)."""
    n = len(chars)
    data = [i for i, c in enumerate(chars) if c in "SCFM"]
    if not data:
        return []
    lead_free = chars[0] == "0"
    trail_free = chars[-1] == "0" and n > 1
    out = []

    def cf_with(first: Optional[str], last: Optional[str]) -> str:
        a = list(chars)
        if first:
            a[0] = first
        if last:
            a[-1] = last
        return "".join(a)

    if lead_free and trail_free:
        half = len(data) // 2
        ceil_half = (len(data) + 1) // 2
        out.append(("par 1a mitad / impar 2a", cf_with("E", "O"),
                    [Parity("even", data[:half]), Parity("odd", data[half:])]))
        if ceil_half != half or len(data) % 2 == 0:
            out.append(("solapada (estilo W37)", cf_with("E", "O"),
                        [Parity("even", data[:ceil_half]), Parity("odd", data[-ceil_half:])]))
        out.append(("impar 1a mitad / par 2a", cf_with("O", "E"),
                    [Parity("odd", data[:half]), Parity("even", data[half:])]))
        out.append(("par y impar sobre todo", cf_with("E", "O"),
                    [Parity("even", data), Parity("odd", data)]))
    if lead_free and not trail_free:
        out.append(("par al inicio sobre todo", cf_with("E", None), [Parity("even", data)]))
        out.append(("impar al inicio sobre todo", cf_with("O", None), [Parity("odd", data)]))
    if trail_free and not lead_free:
        out.append(("par al final sobre todo", cf_with(None, "E"), [Parity("even", data)]))
        out.append(("impar al final sobre todo", cf_with(None, "O"), [Parity("odd", data)]))
    out.append(("sin paridad", "".join(chars), []))
    return out


def _preset_name(cf: str, parities: List[Parity]) -> Optional[str]:
    key = (cf, tuple((p.kind, tuple(p.covers)) for p in parities))
    for name, factory in PRESETS.items():
        f = factory()
        if (f.card_format, tuple((p.kind, tuple(p.covers)) for p in f.parities)) == key:
            return name
    return None


@dataclass
class Candidate:
    fmt: WiegandFormat
    esquema: str
    score: int
    preset: Optional[str]
    lecturas: List[Dict] = field(default_factory=list)
    notas: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        f = self.fmt
        return {
            "name": f.name,
            "card_format": f.card_format,
            "parities": [{"kind": p.kind, "covers": p.covers} for p in f.parities],
            "format_type": f.format_type,
            "status": f.status,
            "site_code": f.site_code,
            "esquema": self.esquema,
            "preset": self.preset,
            "score": self.score,
            "lecturas": self.lecturas,
            "notas": self.notas,
            "todas_ok": all(r["coincide"] and r["paridad_ok"] for r in self.lecturas),
        }


def detect(reads: List[Dict]) -> List[Dict]:
    """Busca formatos que expliquen las lecturas.

    reads: [{"bits": "0101..." | "WG 26 0101...", "printed": "71,7104"}, ...]
    """
    parsed = []
    for r in reads:
        printed = str(r.get("printed", "")).strip()
        if not printed:
            continue
        parsed.append((clean_bits(str(r.get("bits", ""))), printed_targets(printed), printed))
    if not parsed:
        raise DetectError("falta al menos una lectura con su numero impreso")

    bits0, targets0, _ = parsed[0]
    n = len(bits0)
    seen = set()
    cands: List[Candidate] = []

    for site, card in targets0:
        for chars, nota in _layouts(bits0, site, card):
            for esquema, cf, parities in _parity_schemes(chars):
                key = (cf, tuple((p.kind, tuple(p.covers)) for p in parities))
                if key in seen:
                    continue
                seen.add(key)
                preset = _preset_name(cf, parities)
                name = preset_display(preset) if preset else f"Lector{n}"
                try:
                    fmt = WiegandFormat(name=name[:24], card_format=cf, parities=parities)
                    fmt.validate()
                except FormatError:
                    continue
                cands.append(_score(fmt, esquema, preset, nota, parsed))

    if not cands:
        return []
    # Si algun candidato explica TODAS las lecturas, se descartan los que no.
    full = [c for c in cands if all(r["coincide"] for r in c.lecturas)]
    if full:
        cands = full
    cands.sort(key=lambda c: -c.score)
    return [c.to_dict() for c in cands[:MAX_CANDIDATES]]


def preset_display(preset: str) -> str:
    return PRESETS[preset]().name


def _score(fmt, esquema, preset, nota, parsed) -> Candidate:
    cf = fmt.card_format
    score = 0
    lecturas, notas = [], []
    for bits, targets, printed in parsed:
        dec = decode(fmt, bits)
        hit = _matches_targets(dec, targets) if dec["ok_len"] else None
        lecturas.append({
            "impreso": printed,
            "site": dec["site"],
            "card": dec["card"],
            "coincide": hit is not None,
            "paridad_ok": dec["parity_ok"],
        })
        if hit is not None:
            score += 10
            if hit[0] is not None:
                score += 4  # coincide site Y card: mucho mas especifico
        if dec["parity_ok"] and fmt.parities:
            score += 6
    if nota == "site+card":
        score += 2
    if preset:
        score += 5
        notas.append(f"coincide con el preset {preset}")
    # Trama "limpia": paridad en ambos extremos, sin bits fijos ni otros campos.
    if cf[0] in "EO" and cf[-1] in "EO" and "0" not in cf and "F" not in cf:
        score += 3
    if "F" in cf:
        notas.append("hay bits 'F' (otro campo) antes del site: revisar")
    if "0" in cf:
        notas.append("hay bits fijos '0' sin asignar")
    if cf.count("C") in COMMON_CARD_WIDTHS:
        score += 1
    if esquema == "par y impar sobre todo":
        # Par e impar sobre los mismos bits obliga a que ambos bits difieran:
        # con 1-2 lecturas cuadra por azar y no es un formato real conocido.
        score -= 6
        notas.append("esquema poco comun (par e impar sobre los mismos bits): "
                     "confirmar con varias tarjetas")
    if not fmt.parities:
        notas.append("sin paridad: el IN01 aceptara cualquier trama de este largo")
    elif not all(r["paridad_ok"] for r in lecturas):
        score -= 8
        notas.append("la paridad NO cuadra con todas las lecturas")
    if len(parsed) == 1:
        notas.append("con una sola tarjeta la paridad puede cuadrar por azar: lee 2-3 mas")
    return Candidate(fmt=fmt, esquema=esquema, score=score, preset=preset,
                     lecturas=lecturas, notas=notas)
