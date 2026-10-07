"""Motor de formatos Wiegand.

Modela un formato como una secuencia de campos y calcula el mapa de bits
(``Card_Format``) y las mascaras de paridad (``First_Even`` / ``First_Odd`` y,
si aplica, ``Second_Even`` / ``Second_Odd``) tal como los espera la tabla
``HID_FORMAT`` de ``ZKDB.db``.

Convencion de caracteres de ``Card_Format`` (confirmada desde el equipo):
    E = bit de paridad par
    O = bit de paridad impar
    S = site / facility code
    C = numero de tarjeta
    F = otro campo (fabricante, etc.)
    M = otro campo
    0 = bit fijo / sin usar

Las mascaras tienen el mismo largo que ``Card_Format``: un ``1`` marca los bits
que ENTRAN en el calculo de esa paridad, ``0`` los que no. El propio bit de
paridad nunca se incluye en su mascara.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

# Caracteres validos de campo en Card_Format.
FIELD_CHARS = set("EOSCFM0")
DATA_CHARS = set("SCFM")  # campos que transportan datos (no paridad, no fijo)

# Valores de Format_Type SEGUN EL COMPORTAMIENTO REAL DEL IN01 (verificado en
# equipo): el firmware interpreta los valores al reves de lo que decia la
# ingenieria inversa inicial. Entrada (lectura) = 3, Salida (Wiegand out) = 1,
# Interno (IntWiegand) = 2.
FMT_ENTRADA = 3   # lectura de tarjeta
FMT_SALIDA = 1    # Wiegand out
FMT_INTERNO = 2   # IntWiegand


class FormatError(ValueError):
    """Error de definicion o validacion de un formato."""


@dataclass
class Parity:
    """Definicion de una paridad.

    kind:  "even" u "odd".
    covers: lista de indices (0-based, dentro de Card_Format) que entran en el
            calculo. El indice del propio bit de paridad NO debe estar aqui.
    """

    kind: str
    covers: List[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.kind not in ("even", "odd"):
            raise FormatError(f"paridad desconocida: {self.kind!r}")


@dataclass
class WiegandFormat:
    """Un formato Wiegand completo, listo para volcar a HID_FORMAT.

    card_format: cadena de caracteres de campo (E/O/S/C/F/M/0).
    parities:    lista de Parity. El orden importa: la 1a par -> First_Even,
                 la 2a par -> Second_Even; idem para impar con First/Second_Odd.
    """

    name: str
    card_format: str
    parities: List[Parity] = field(default_factory=list)
    format_type: int = FMT_ENTRADA  # ver constantes: 3=entrada, 1=salida, 2=interno
    status: int = 1  # 1=activo para ese format_type
    site_code: int = 0

    # ------------------------------------------------------------------ #
    # Validacion
    # ------------------------------------------------------------------ #
    @property
    def card_bit(self) -> int:
        return len(self.card_format)

    def validate(self) -> None:
        cf = self.card_format
        if not cf:
            raise FormatError("Card_Format vacio")
        bad = sorted(set(cf) - FIELD_CHARS)
        if bad:
            raise FormatError(
                f"caracteres invalidos en Card_Format: {''.join(bad)} "
                f"(validos: {''.join(sorted(FIELD_CHARS))})"
            )

        even_positions = [i for i, c in enumerate(cf) if c == "E"]
        odd_positions = [i for i, c in enumerate(cf) if c == "O"]
        n_even = sum(1 for p in self.parities if p.kind == "even")
        n_odd = sum(1 for p in self.parities if p.kind == "odd")

        if n_even != len(even_positions):
            raise FormatError(
                f"hay {len(even_positions)} bit(s) 'E' en Card_Format pero "
                f"{n_even} paridad(es) par definida(s)"
            )
        if n_odd != len(odd_positions):
            raise FormatError(
                f"hay {len(odd_positions)} bit(s) 'O' en Card_Format pero "
                f"{n_odd} paridad(es) impar definida(s)"
            )
        if n_even > 2 or n_odd > 2:
            raise FormatError(
                "HID_FORMAT solo admite hasta 2 paridades pares y 2 impares"
            )

        for p in self.parities:
            own = self.own_position(p)
            for idx in p.covers:
                if idx < 0 or idx >= len(cf):
                    raise FormatError(
                        f"la paridad {p.kind} cubre el indice {idx} fuera de rango "
                        f"(0..{len(cf) - 1})"
                    )
                # Puede cubrir OTRO bit de paridad (p.ej. HID Corporate 1000),
                # pero nunca el suyo propio.
                if idx == own:
                    raise FormatError(
                        f"la paridad {p.kind} no puede cubrir su propio bit "
                        f"en el indice {idx}"
                    )
            if not p.covers:
                raise FormatError(f"la paridad {p.kind} no cubre ningun bit")
        self._parity_order()  # detecta paridades que se cubren entre si

    def own_position(self, parity: Parity) -> int:
        """Indice en Card_Format del propio bit de ``parity`` (n-esimo E u O)."""
        target = "E" if parity.kind == "even" else "O"
        same_kind = [p for p in self.parities if p.kind == parity.kind]
        order = next(i for i, p in enumerate(same_kind) if p is parity)
        return [i for i, c in enumerate(self.card_format) if c == target][order]

    def _parity_order(self) -> List[Parity]:
        """Orden de calculo: primero las paridades que no dependen de otras."""
        pending = list(self.parities)
        done_pos: set = set()
        all_pos = {self.own_position(p) for p in self.parities}
        order: List[Parity] = []
        while pending:
            ready = [p for p in pending
                     if not ((set(p.covers) & all_pos) - done_pos)]
            if not ready:
                raise FormatError("hay paridades que se cubren mutuamente")
            for p in ready:
                order.append(p)
                done_pos.add(self.own_position(p))
                pending.remove(p)
        return order

    # ------------------------------------------------------------------ #
    # Generacion de mascaras
    # ------------------------------------------------------------------ #
    def _mask(self, parity: Parity) -> str:
        chars = ["0"] * len(self.card_format)
        for idx in parity.covers:
            chars[idx] = "1"
        return "".join(chars)

    def masks(self) -> dict:
        """Devuelve {First_Even, Second_Even, First_Odd, Second_Odd}.

        Las ausentes quedan como None (lo que en HID_FORMAT va NULL).
        """
        self.validate()
        evens = [p for p in self.parities if p.kind == "even"]
        odds = [p for p in self.parities if p.kind == "odd"]
        out = {
            "First_Even": None,
            "Second_Even": None,
            "First_Odd": None,
            "Second_Odd": None,
        }
        if len(evens) >= 1:
            out["First_Even"] = self._mask(evens[0])
        if len(evens) >= 2:
            out["Second_Even"] = self._mask(evens[1])
        if len(odds) >= 1:
            out["First_Odd"] = self._mask(odds[0])
        if len(odds) >= 2:
            out["Second_Odd"] = self._mask(odds[1])
        return out

    def to_row(self) -> dict:
        """Fila de HID_FORMAT (nombres de columna con guion bajo)."""
        m = self.masks()
        return {
            "Card_Bit": self.card_bit,
            "Format_Name": self.name,
            "Card_Format": self.card_format,
            "First_Even": m["First_Even"],
            "Second_Even": m["Second_Even"],
            "First_Odd": m["First_Odd"],
            "Second_Odd": m["Second_Odd"],
            "Format_Type": self.format_type,
            "Status": self.status,
            # Las filas de fabrica llevan SiteCode NULL; 0 no es lo mismo.
            "SiteCode": self.site_code or None,
        }

    # ------------------------------------------------------------------ #
    # Codificacion de una credencial (para previsualizar / verificar)
    # ------------------------------------------------------------------ #
    def encode(self, *, site: int = 0, card: int = 0) -> str:
        """Construye la trama de bits (como string de 0/1) para un site+card.

        Util para previsualizar un formato y para verificar contra un lector.
        Los bits de datos se colocan MSB primero dentro de cada campo; las
        paridades se calculan con las mascaras.
        """
        self.validate()
        cf = self.card_format
        bits = ["0"] * len(cf)

        # Rellena los campos de datos (S, C) con el valor, MSB primero.
        for ch, value in (("S", site), ("C", card)):
            positions = [i for i, c in enumerate(cf) if c == ch]
            width = len(positions)
            if width == 0:
                continue
            if value < 0 or value >= (1 << width):
                raise FormatError(
                    f"el valor {value} no cabe en {width} bit(s) del campo {ch}"
                )
            vbits = format(value, f"0{width}b")
            for pos, b in zip(positions, vbits):
                bits[pos] = b

        # Calcula las paridades (las que cubren otro bit de paridad, al final).
        for p in self._parity_order():
            ones = sum(1 for idx in p.covers if bits[idx] == "1")
            if p.kind == "even":
                pbit = "1" if ones % 2 else "0"
            else:  # odd
                pbit = "0" if ones % 2 else "1"
            bits[self.own_position(p)] = pbit

        return "".join(bits)
