"""Edicion de HID_FORMAT sobre una copia local de ZKDB.db.

Este es el metodo recomendado para el IN01: en vez de reescribir la tabla a
ciegas con un ``update.sql`` (``delete`` + ``insert``, que borra lo que no
reinsertamos), se trae una copia real de ``ZKDB.db``, se modifica SOLO lo
necesario de ``HID_FORMAT`` conservando el resto de filas y de tablas, y se
devuelve la base para reemplazarla con ``mv`` + reboot.

Operaciones:
  - upsert: agrega o actualiza cada formato (match por Format_Type+Format_Name).
    Si el formato viene con Status=1, deja ese como unico activo de su
    Format_Type (pone Status=0 en los demas de ese tipo).
  - activate: no inserta nada; solo mueve el Status=1 al formato indicado
    dentro de su Format_Type.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import List

from .core import WiegandFormat

# Columnas que escribimos (las mismas del insert de fabrica; el resto queda por
# defecto o NULL). ID es autoincremental.
_WRITE_COLS = [
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


class DbEditError(ValueError):
    pass


@dataclass
class EditSummary:
    insertados: List[str] = field(default_factory=list)
    actualizados: List[str] = field(default_factory=list)
    activados: List[str] = field(default_factory=list)   # "tipo N -> Nombre"


def _table_exists(con: sqlite3.Connection, name: str) -> bool:
    cur = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    )
    return cur.fetchone() is not None


def _existing_columns(con: sqlite3.Connection) -> List[str]:
    cur = con.execute("PRAGMA table_info(HID_FORMAT)")
    return [r[1] for r in cur.fetchall()]


def apply_formats(db_path: str, formats: List[WiegandFormat], modo: str = "upsert") -> EditSummary:
    """Modifica HID_FORMAT en la copia local ``db_path``. Devuelve un resumen."""
    if modo not in ("upsert", "activate"):
        raise DbEditError(f"modo desconocido: {modo}")
    for f in formats:
        f.validate()

    con = sqlite3.connect(db_path)
    summary = EditSummary()
    try:
        if not _table_exists(con, "HID_FORMAT"):
            raise DbEditError("la copia de ZKDB.db no tiene la tabla HID_FORMAT")
        cols = set(_existing_columns(con))
        write_cols = [c for c in _WRITE_COLS if c in cols]

        for fmt in formats:
            row = fmt.to_row()
            cur = con.execute(
                "SELECT ID FROM HID_FORMAT WHERE Format_Type=? AND Format_Name=?",
                (fmt.format_type, fmt.name),
            )
            found = cur.fetchone()

            if modo == "activate":
                if not found:
                    raise DbEditError(
                        f"no existe el formato '{fmt.name}' tipo {fmt.format_type} para activar"
                    )
            else:  # upsert
                if found:
                    sets = ", ".join(f"{c}=?" for c in write_cols)
                    vals = [row[c] for c in write_cols] + [found[0]]
                    con.execute(f"UPDATE HID_FORMAT SET {sets} WHERE ID=?", vals)
                    summary.actualizados.append(fmt.name)
                else:
                    placeholders = ", ".join("?" for _ in write_cols)
                    vals = [row[c] for c in write_cols]
                    con.execute(
                        f"INSERT INTO HID_FORMAT({', '.join(write_cols)}) VALUES({placeholders})",
                        vals,
                    )
                    summary.insertados.append(fmt.name)

            # Dejar un unico activo por Format_Type si este formato debe quedar activo.
            if fmt.status == 1:
                con.execute(
                    "UPDATE HID_FORMAT SET Status=0 WHERE Format_Type=?", (fmt.format_type,)
                )
                con.execute(
                    "UPDATE HID_FORMAT SET Status=1 WHERE Format_Type=? AND Format_Name=?",
                    (fmt.format_type, fmt.name),
                )
                summary.activados.append(f"tipo {fmt.format_type} -> {fmt.name}")

        con.commit()
    finally:
        con.close()
    return summary
