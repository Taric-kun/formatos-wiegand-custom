"""Secuencia de carga del archivo de actualizacion en un reloj IN01.

Genera la lista de comandos PUSH que deja el ``update.sql`` en el equipo y lo
aplica al reiniciar. NO decide el SN: eso lo maneja quien encola (``enqueue``);
aqui solo se arma el texto de cada comando, respetando los gotchas del firmware:

  - Nombres y rutas CORTOS en el staging (el firmware trunca el comando shell
    por encima de ~90-100 caracteres).
  - ``wget -O`` para sobrescribir sin el error ``File exists`` de BusyBox.
  - ``mv`` (reemplazo atomico) para dejar el archivo en su ruta final, nunca
    ``cp`` sobre un archivo bloqueado.
  - ``sync`` + ``REBOOT`` para que el firmware aplique ``data/update.sql`` al
    arrancar.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

# El IN01 aplica este archivo (relativo a /mnt/mtdblock) al arrancar.
DEFAULT_STAGING = "/mnt/mtdblock"
DEFAULT_SHORT_NAME = "u.sql"
DEFAULT_DEST = "/mnt/mtdblock/data/update.sql"

# Umbral conservador de largo para el texto del comando (sin el prefijo C:<id>:).
MAX_CMD_LEN = 90


class LoadError(ValueError):
    """Error al construir la secuencia de carga."""


@dataclass
class LoadStep:
    """Un paso de la secuencia: el comando PUSH y una descripcion legible."""

    cmd: str
    descripcion: str

    def __post_init__(self) -> None:
        if len(self.cmd) > MAX_CMD_LEN:
            raise LoadError(
                f"el comando excede {MAX_CMD_LEN} caracteres ({len(self.cmd)}) y el "
                f"firmware lo truncaria: {self.cmd!r}. Usa rutas o nombres mas cortos."
            )


def build_in01_load_sequence(
    download_url: str,
    *,
    staging_dir: str = DEFAULT_STAGING,
    short_name: str = DEFAULT_SHORT_NAME,
    dest: str = DEFAULT_DEST,
) -> List[LoadStep]:
    """Secuencia probada en el IN01 para dejar ``update.sql`` y aplicarlo al boot.

    Reproduce exactamente el flujo que funciono en el equipo:
      rm -f staging  ->  cd staging && wget (SIN -O)  ->  verificar (ls, od -c)
      ->  mv a dest  ->  chmod 777  ->  verificar (ls)  ->  sync  ->  REBOOT

    Clave: ``cd`` + ``wget`` sin ``-O`` (BusyBox guarda con el nombre del URL) y
    el ``rm -f`` previo evitan el ``File exists`` y el archivo vacio/truncado que
    daba el ``wget -O``. La verificacion con ``od -c`` confirma que no hay BOM ni
    truncado. ``download_url`` debe terminar en ``/<short_name>``.
    """
    if not download_url:
        raise LoadError("download_url vacio")
    staging = staging_dir.rstrip("/")
    tmp = f"{staging}/{short_name}"
    return [
        LoadStep(f"shell rm -f {tmp}", f"Limpiar {tmp} previo"),
        LoadStep(f"shell cd {staging} && wget {download_url}", f"Descargar a {staging} (sin -O)"),
        LoadStep(f"shell ls -la {tmp}", "Verificar que el archivo llego"),
        LoadStep(f"shell head -c 16 {tmp} | od -c", "Verificar inicio (sin BOM, no vacio)"),
        LoadStep(f"shell mv {tmp} {dest}", f"Mover (atomico) a {dest}"),
        LoadStep(f"shell chmod 777 {dest}", f"Permisos 777 a {dest}"),
        LoadStep(f"shell ls -la {dest}", "Verificar el destino"),
        LoadStep("shell sync", "Volcar buffers a disco"),
        LoadStep("REBOOT", "Reiniciar para aplicar update.sql al arrancar"),
    ]


DEFAULT_DB_SHORT = "z.db"
DEFAULT_DB_DEST = "/mnt/mtdblock/data/ZKDB.db"


def build_in01_db_replace_sequence(
    download_url: str,
    *,
    staging_dir: str = DEFAULT_STAGING,
    short_name: str = DEFAULT_DB_SHORT,
    dest: str = DEFAULT_DB_DEST,
) -> List[LoadStep]:
    """Secuencia que reemplaza ZKDB.db completa: wget -> mv -> chmod -> sync -> REBOOT.

    Se usa con una copia de ZKDB.db ya editada en la PC (ver dbedit). El ``mv``
    (atomico) reemplaza la base bloqueada; el firmware la toma al reiniciar.
    """
    if not download_url:
        raise LoadError("download_url vacio")
    staging = staging_dir.rstrip("/")
    tmp = f"{staging}/{short_name}"
    return [
        LoadStep(f"shell rm -f {tmp}", f"Limpiar {tmp} previo"),
        LoadStep(f"shell cd {staging} && wget {download_url}", f"Descargar ZKDB.db a {staging} (sin -O)"),
        LoadStep(f"shell ls -la {tmp}", "Verificar que la base llego"),
        LoadStep(f"shell mv {tmp} {dest}", f"Reemplazar (atomico) {dest}"),
        LoadStep(f"shell chmod 777 {dest}", f"Permisos 777 a {dest}"),
        LoadStep(f"shell ls -la {dest}", "Verificar el destino"),
        LoadStep("shell sync", "Volcar buffers a disco"),
        LoadStep("REBOOT", "Reiniciar para que el firmware tome la base nueva"),
    ]


def commands(steps: List[LoadStep]) -> List[str]:
    """Extrae solo los textos de comando, en orden, para encolar."""
    return [s.cmd for s in steps]
