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
    """Arma la secuencia: wget -> mv -> chmod -> sync -> REBOOT.

    download_url: URL desde la que el reloj baja el payload (la que sirve el
                  panel en ``/dl/<nombre>``).
    """
    if not download_url:
        raise LoadError("download_url vacio")
    staging = staging_dir.rstrip("/")
    tmp = f"{staging}/{short_name}"
    steps = [
        LoadStep(f"shell wget {download_url} -O {tmp}", f"Descargar payload a {tmp}"),
        LoadStep(f"shell mv {tmp} {dest}", f"Mover (atomico) a {dest}"),
        LoadStep(f"shell chmod 777 {dest}", f"Permisos 777 a {dest}"),
        LoadStep("shell sync", "Volcar buffers a disco"),
        LoadStep("REBOOT", "Reiniciar para aplicar update.sql al arrancar"),
    ]
    return steps


def commands(steps: List[LoadStep]) -> List[str]:
    """Extrae solo los textos de comando, en orden, para encolar."""
    return [s.cmd for s in steps]
