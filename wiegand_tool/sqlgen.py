"""Generador del archivo de actualizacion para el reloj.

Produce el formato de bloques que aplica el firmware al arrancar:

    [CREATE_TABLE]
    {
    delete from HID_FORMAT where ID>0;
    insert into HID_FORMAT(...) VALUES(...);
    ...
    }

Reglas de oro respetadas al escribir el archivo:
  - UTF-8 SIN BOM (un BOM rompe la primera sentencia: ``delete: not found``).
  - Terminadores de linea LF (``\n``), nunca CRLF.
  - Comillas DOBLES para los valores de texto.
  - Nombres de columna CON guion bajo (Card_Bit, First_Even, ...).
"""

from __future__ import annotations

from typing import Iterable, List, Optional

from .core import WiegandFormat
from .factory import FACTORY_ROWS

# Columnas que escribimos en cada INSERT, en orden.
_COLUMNS = [
    "Card_Bit",
    "Format_Name",
    "Card_Format",
    "First_Even",
    "Second_Even",
    "First_Odd",
    "Second_Odd",
    "Format_Type",
    "Status",
    "SiteCode",
]


def _sql_value(v) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, int):
        return str(v)
    # texto: comillas dobles; escapamos comillas dobles internas duplicandolas.
    return '"' + str(v).replace('"', '""') + '"'


def _insert_statement(fmt: WiegandFormat) -> str:
    return _insert_row(fmt.to_row())


def _insert_row(row: dict) -> str:
    cols = ", ".join(_COLUMNS)
    vals = ", ".join(_sql_value(row[c]) for c in _COLUMNS)
    return f"insert into HID_FORMAT({cols}) VALUES({vals});"


def factory_rows_for(formats: List[WiegandFormat]) -> List[dict]:
    """Filas de fabrica a reinsertar junto con ``formats``.

    - Se omite la fila de fabrica con el mismo Format_Type + Format_Name que un
      formato nuestro (lo reemplazamos).
    - Si un formato nuestro queda activo (Status=1), las de fabrica de ese
      Format_Type quedan inactivas: un solo activo por tipo.
    """
    ours = {(f.format_type, f.name) for f in formats}
    activos = {f.format_type for f in formats if f.status == 1}
    rows = []
    for r in FACTORY_ROWS:
        if (r["Format_Type"], r["Format_Name"]) in ours:
            continue
        row = dict(r)
        if row["Format_Type"] in activos:
            row["Status"] = 0
        rows.append(row)
    return rows


def build_rewrite_block(formats: Iterable[WiegandFormat], *, keep_factory: bool = True) -> str:
    """Bloque que reescribe la tabla: delete total + inserts.

    Con ``keep_factory`` (por defecto) reinserta primero las filas de fabrica
    del IN01 (internos tipo 2, salida tipo 1, entradas tipo 3) y luego las
    nuestras: el reloj conserva todos sus formatos y solo cambia el activo.
    Sin ``keep_factory`` la tabla queda SOLO con nuestros formatos; en el IN01
    eso lo deja sin leer tarjetas (sin formatos internos ni de salida).
    """
    formats = list(formats)
    for f in formats:
        f.validate()
    lines: List[str] = ["[CREATE_TABLE]", "{", "delete from HID_FORMAT where ID>0;"]
    if keep_factory:
        lines.extend(_insert_row(r) for r in factory_rows_for(formats))
    lines.extend(_insert_statement(f) for f in formats)
    lines.append("}")
    return "\n".join(lines) + "\n"


def build_activate_only_block(
    card_bit: int, format_type: int, *, format_name: Optional[str] = None
) -> str:
    """Bloque que SOLO cambia Status: activa un formato ya presente en la tabla.

    Pone Status=0 en todas las filas de ese Format_Type y Status=1 en la que
    coincide por Card_Bit (y Format_Name si se indica). No borra ni inserta.
    """
    where = f"Card_Bit={int(card_bit)}"
    if format_name is not None:
        where += f' and Format_Name={_sql_value(format_name)}'
    lines = [
        "[UPDATE]",
        "{",
        f"update HID_FORMAT set Status=0 where Format_Type={int(format_type)};",
        f"update HID_FORMAT set Status=1 where Format_Type={int(format_type)} and {where};",
        "}",
    ]
    return "\n".join(lines) + "\n"


def write_update_file(path: str, content: str) -> None:
    """Escribe el archivo UTF-8 SIN BOM y con LF, pase lo que pase."""
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    data = normalized.encode("utf-8")  # str.encode('utf-8') nunca agrega BOM
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    with open(path, "wb") as fh:
        fh.write(data)


def verify_update_file(path: str) -> dict:
    """Chequeos rapidos sobre un archivo ya escrito."""
    with open(path, "rb") as fh:
        data = fh.read()
    return {
        "bytes": len(data),
        "has_bom": data.startswith(b"\xef\xbb\xbf"),
        "has_crlf": b"\r\n" in data,
        "has_cr": b"\r" in data,
        "ends_with_lf": data.endswith(b"\n"),
    }
