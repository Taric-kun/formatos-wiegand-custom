"""Respaldo, rollback y verificacion de la tabla HID_FORMAT en el IN01.

El respaldo y el rollback se expresan como secuencias de comandos PUSH (los
encola quien elige el SN). La verificacion se hace en local: se trae una copia
de ``ZKDB.db`` con GetFile y se lee ``HID_FORMAT`` con sqlite3 (biblioteca
estandar), comparando con lo esperado.

Reglas respetadas (ver README):
  - Nunca escribir sobre ``ZKDB.db`` en vivo: para respaldar se hace ``cp`` de
    la base a una copia ``.bak`` (leer una copia si que esta permitido).
  - El rollback quita el ``update.sql`` pendiente y restaura la copia con ``mv``
    (reemplazo atomico), luego ``sync`` + ``REBOOT``.
  - Comandos cortos (< ~90 chars) por el truncado del firmware.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Dict, List, Optional

from .loader import LoadStep

DB_PATH = "/mnt/mtdblock/data/ZKDB.db"
BAK_PATH = "/mnt/mtdblock/data/ZKDB.bak"
UPDATE_PATH = "/mnt/mtdblock/data/update.sql"
VERIFY_COPY = "/tmp/z.db"


def build_backup_sequence(db: str = DB_PATH, bak: str = BAK_PATH) -> List[LoadStep]:
    """Respalda la base: copia ZKDB.db -> ZKDB.bak (leer copia, no escribir en vivo)."""
    return [LoadStep(f"shell cp {db} {bak}", f"Respaldar {db} en {bak}")]


def build_rollback_sequence(
    db: str = DB_PATH, bak: str = BAK_PATH, update: str = UPDATE_PATH
) -> List[LoadStep]:
    """Deshace un cambio: quita el update.sql pendiente y restaura la copia."""
    return [
        LoadStep(f"shell rm {update}", f"Quitar {update} pendiente"),
        LoadStep(f"shell mv {bak} {db}", f"Restaurar {db} desde la copia"),
        LoadStep("shell sync", "Volcar buffers a disco"),
        LoadStep("REBOOT", "Reiniciar para que quede la base restaurada"),
    ]


def build_verify_fetch_sequence(db: str = DB_PATH, copy: str = VERIFY_COPY) -> List[LoadStep]:
    """Prepara la verificacion: copia la base a /tmp y la pide con GetFile.

    El panel captura el archivo; luego se lee con read_hid_format sobre esa copia.
    """
    return [
        LoadStep(f"shell cp {db} {copy}", f"Copiar base a {copy} para leer"),
        LoadStep(f"GetFile {copy}", f"Traer {copy} al panel"),
    ]


# --------------------------------------------------------------------------- #
# Verificacion local sobre una copia descargada de ZKDB.db
# --------------------------------------------------------------------------- #
_HID_COLUMNS = [
    "ID",
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


def read_hid_format(sqlite_path: str) -> List[Dict]:
    """Lee las filas de HID_FORMAT desde una copia local de ZKDB.db."""
    con = sqlite3.connect(sqlite_path)
    try:
        con.row_factory = sqlite3.Row
        cols = ", ".join(_HID_COLUMNS)
        try:
            cur = con.execute(f"SELECT {cols} FROM HID_FORMAT ORDER BY ID")
        except sqlite3.OperationalError as exc:
            raise ValueError(f"no pude leer HID_FORMAT: {exc}") from exc
        return [dict(r) for r in cur.fetchall()]
    finally:
        con.close()


@dataclass
class VerifyResult:
    ok: bool
    activos: Dict[int, Optional[str]]   # Format_Type -> Format_Name activo (Status=1)
    problemas: List[str]


def verify_active_formats(
    sqlite_path: str, esperado: Dict[int, str]
) -> VerifyResult:
    """Verifica que el formato activo (Status=1) por Format_Type sea el esperado.

    esperado: {Format_Type: Format_Name que deberia estar activo}.
    """
    filas = read_hid_format(sqlite_path)
    activos: Dict[int, Optional[str]] = {}
    problemas: List[str] = []

    por_tipo: Dict[int, List[dict]] = {}
    for f in filas:
        por_tipo.setdefault(f["Format_Type"], []).append(f)

    for ftype, nombre_esperado in esperado.items():
        activas = [f for f in por_tipo.get(ftype, []) if f["Status"] == 1]
        if len(activas) == 0:
            activos[ftype] = None
            problemas.append(f"Format_Type {ftype}: ningun formato activo")
        elif len(activas) > 1:
            activos[ftype] = activas[0]["Format_Name"]
            nombres = ", ".join(a["Format_Name"] for a in activas)
            problemas.append(f"Format_Type {ftype}: hay {len(activas)} activos ({nombres})")
        else:
            nombre = activas[0]["Format_Name"]
            activos[ftype] = nombre
            if nombre != nombre_esperado:
                problemas.append(
                    f"Format_Type {ftype}: activo '{nombre}', se esperaba '{nombre_esperado}'"
                )

    return VerifyResult(ok=not problemas, activos=activos, problemas=problemas)
