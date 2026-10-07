#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""App web local: editor de formatos Wiegand + carga en el reloj IN01.

Reutiliza el servidor PUSH/ADMS de ``zk_panel.py`` (ZK Commander) como capa de
transporte y le agrega, en la misma app:

  - Editor de formatos Wiegand con presets, previsualizacion de mascaras y del
    archivo de actualizacion ``update.sql``.
  - Generacion del archivo (reescribir tabla o solo activar) y registro como
    archivo a servir por ``/dl/<nombre>``.
  - Carga en el IN01 por SN: respaldo -> wget -> mv -> chmod -> sync -> REBOOT,
    mostrando los comandos exactos antes de encolarlos.
  - Verificacion: traer una copia de ZKDB.db y comparar el formato activo.

Uso:
  python3 app.py --port 8080 --myip 192.168.3.166

El panel crudo de ZK Commander sigue disponible en /panel.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import tempfile
from http.server import ThreadingHTTPServer

import zk_panel
from wiegand_tool import backup, dbedit, decode, loader, sqlgen
from wiegand_tool.core import FormatError, Parity, WiegandFormat
from wiegand_tool.presets import PRESET_STATUS, PRESETS

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webapp")


# --------------------------------------------------------------------------- #
# Conversion spec JSON <-> WiegandFormat
# --------------------------------------------------------------------------- #
def format_from_spec(spec: dict) -> WiegandFormat:
    try:
        parities = [Parity(p["kind"], list(p.get("covers", []))) for p in spec.get("parities", [])]
        fmt = WiegandFormat(
            name=str(spec["name"])[:24],
            card_format=str(spec["card_format"]).upper(),
            parities=parities,
            format_type=int(spec.get("format_type", 1)),
            status=int(spec.get("status", 1)),
            site_code=int(spec.get("site_code", 0)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise FormatError(f"spec invalido: {exc}") from exc
    fmt.validate()
    return fmt


def preset_to_spec(name: str) -> dict:
    fmt = PRESETS[name]()
    return {
        "name": fmt.name,
        "card_format": fmt.card_format,
        "parities": [{"kind": p.kind, "covers": p.covers} for p in fmt.parities],
        "format_type": fmt.format_type,
        "status": fmt.status,
        "site_code": fmt.site_code,
        "estado": PRESET_STATUS.get(name, ""),
    }


def _register_file(name: str, data: bytes) -> dict:
    """Registra el archivo generado en el estado de zk_panel para servirlo en /dl/."""
    md5 = hashlib.md5(data).hexdigest()
    with zk_panel.LOCK:
        zk_panel.G["file"] = {"name": name, "data": data, "md5": md5, "size": len(data)}
    zk_panel.log(f"update.sql generado: {name} ({len(data)}b, MD5={md5})")
    return {"name": name, "size": len(data), "md5": md5, "url": zk_panel.url_dl()}


# --------------------------------------------------------------------------- #
# Handler: extiende el de zk_panel con rutas /api/wg/* y la pagina del editor
# --------------------------------------------------------------------------- #
class Handler(zk_panel.Handler):
    def _static(self, rel: str, ctype: str):
        path = os.path.join(STATIC_DIR, rel)
        if not os.path.isfile(path):
            return self._send("not found", code=404)
        with open(path, "rb") as fh:
            return self._send(fh.read(), ctype)

    def do_GET(self):  # noqa: N802
        from urllib.parse import urlparse

        p = urlparse(self.path).path
        if p in ("/", "/index.html"):
            return self._static("index.html", "text/html; charset=utf-8")
        if p == "/app.js":
            return self._static("app.js", "application/javascript; charset=utf-8")
        if p == "/app.css":
            return self._static("app.css", "text/css; charset=utf-8")
        if p == "/panel":
            return self._send(zk_panel.PANEL, "text/html; charset=utf-8")
        if p == "/api/wg/presets":
            return self._json(
                {"presets": [preset_to_spec(n) for n in PRESETS], "names": list(PRESETS)}
            )
        return super().do_GET()

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b""
        try:
            return json.loads(body or b"{}")
        except Exception:
            return None

    def do_POST(self):  # noqa: N802
        from urllib.parse import urlparse

        p = urlparse(self.path).path
        if not p.startswith("/api/wg/"):
            return super().do_POST()

        data = self._read_json()
        if data is None:
            return self._json({"error": "json invalido"}, 400)

        try:
            if p == "/api/wg/preview":
                return self._wg_preview(data)
            if p == "/api/wg/build":
                return self._wg_build(data)
            if p == "/api/wg/load_preview":
                return self._wg_load_preview(data)
            if p == "/api/wg/load":
                return self._wg_load(data)
            if p == "/api/wg/build_db":
                return self._wg_build_db(data)
            if p == "/api/wg/load_db_preview":
                return self._wg_load_db_preview(data)
            if p == "/api/wg/load_db":
                return self._wg_load_db(data)
            if p == "/api/wg/identify":
                return self._wg_identify(data)
            if p == "/api/wg/verify_fetch":
                return self._wg_verify_fetch(data)
            if p == "/api/wg/verify_result":
                return self._wg_verify_result(data)
            if p == "/api/wg/rollback":
                return self._wg_rollback(data)
        except (FormatError, loader.LoadError, ValueError) as exc:
            return self._json({"error": str(exc)}, 400)
        return self._json({"error": "ruta desconocida"}, 404)

    # -- endpoints --------------------------------------------------------- #
    def _wg_preview(self, data):
        """Devuelve fila, mascaras y bloque update.sql para una lista de formatos."""
        specs = data.get("formats", [])
        modo = data.get("modo", "rewrite")  # rewrite | activate
        fmts = [format_from_spec(s) for s in specs]
        out = {"rows": [f.to_row() for f in fmts]}
        if modo == "activate" and fmts:
            f = fmts[0]
            out["sql"] = sqlgen.build_activate_only_block(
                f.card_bit, f.format_type, format_name=f.name
            )
        else:
            out["sql"] = sqlgen.build_rewrite_block(fmts) if fmts else ""
        # vista previa opcional de la trama para un site/card de ejemplo
        if data.get("sample") and fmts:
            s = data["sample"]
            out["sample_frame"] = fmts[0].encode(
                site=int(s.get("site", 0)), card=int(s.get("card", 0))
            )
        return self._json(out)

    def _wg_build(self, data):
        """Genera el update.sql y lo registra como archivo a servir en /dl/."""
        specs = data.get("formats", [])
        modo = data.get("modo", "rewrite")
        name = os.path.basename(data.get("filename", "u.sql")) or "u.sql"
        fmts = [format_from_spec(s) for s in specs]
        if modo == "activate" and fmts:
            f = fmts[0]
            sql = sqlgen.build_activate_only_block(f.card_bit, f.format_type, format_name=f.name)
        else:
            if not fmts:
                return self._json({"error": "no hay formatos"}, 400)
            sql = sqlgen.build_rewrite_block(fmts)
        normalized = sql.replace("\r\n", "\n").replace("\r", "\n")
        payload = normalized.encode("utf-8")
        if payload.startswith(b"\xef\xbb\xbf"):
            payload = payload[3:]
        info = _register_file(name, payload)
        info["sql"] = sql
        return self._json(info)

    def _load_steps(self, data):
        """Arma backup + secuencia de carga (sin encolar). Requiere archivo construido."""
        url = zk_panel.url_dl()
        if not url:
            raise loader.LoadError("primero construye el update.sql (Generar)")
        short = os.path.basename(zk_panel.G["file"]["name"]) or "u.sql"
        steps = []
        if data.get("backup", True):
            steps += backup.build_backup_sequence()
        steps += loader.build_in01_load_sequence(url, short_name=short)
        return steps

    def _wg_load_preview(self, data):
        steps = self._load_steps(data)
        return self._json(
            {"steps": [{"cmd": s.cmd, "descripcion": s.descripcion} for s in steps]}
        )

    def _wg_load(self, data):
        sn = (data.get("sn") or "").strip()
        if not sn or sn == "all":
            return self._json({"error": "elige un SN especifico (no 'all')"}, 400)
        steps = self._load_steps(data)
        ids = [zk_panel.enqueue(sn, s.cmd) for s in steps]
        return self._json({"queued": len(ids), "sn": sn, "ids": ids})

    # -- metodo reemplazo de ZKDB.db ------------------------------------- #
    def _latest_db_capture(self):
        with zk_panel.LOCK:
            caps = [c for c in zk_panel.G["captures"] if c.get("type", "").startswith("SQLite")]
        return caps[-1] if caps else None

    def _wg_build_db(self, data):
        """Edita una copia de la ZKDB.db capturada y la registra para enviar.

        Requiere haber traido antes la ZKDB.db (Traer copia). Conserva todo y
        solo modifica HID_FORMAT con los formatos indicados.
        """
        cap = self._latest_db_capture()
        if not cap:
            return self._json(
                {"error": "primero trae la ZKDB.db del reloj (Traer copia de ZKDB.db)"}, 400
            )
        specs = data.get("formats", [])
        modo = data.get("modo", "upsert")  # upsert | activate
        name = os.path.basename(data.get("filename", "z.db")) or "z.db"
        fmts = [format_from_spec(s) for s in specs]
        if not fmts:
            return self._json({"error": "no hay formatos"}, 400)

        work = os.path.join(tempfile.gettempdir(), "wg_" + name)
        shutil.copyfile(cap["path"], work)
        summary = dbedit.apply_formats(work, fmts, modo=modo)
        with open(work, "rb") as fh:
            payload = fh.read()
        info = _register_file(name, payload)
        info["origen"] = cap["url"]
        info["insertados"] = summary.insertados
        info["actualizados"] = summary.actualizados
        info["activados"] = summary.activados
        info["filas"] = backup.read_hid_format(work)
        return self._json(info)

    def _db_steps(self):
        url = zk_panel.url_dl()
        if not url:
            raise loader.LoadError("primero genera la ZKDB.db editada (Generar reemplazo)")
        short = os.path.basename(zk_panel.G["file"]["name"]) or "z.db"
        return loader.build_in01_db_replace_sequence(url, short_name=short)

    def _wg_load_db_preview(self, data):
        steps = self._db_steps()
        return self._json(
            {"steps": [{"cmd": s.cmd, "descripcion": s.descripcion} for s in steps]}
        )

    def _wg_load_db(self, data):
        sn = (data.get("sn") or "").strip()
        if not sn or sn == "all":
            return self._json({"error": "elige un SN especifico (no 'all')"}, 400)
        steps = self._db_steps()
        ids = [zk_panel.enqueue(sn, s.cmd) for s in steps]
        return self._json({"queued": len(ids), "sn": sn, "ids": ids})

    # -- identificar formato desde una trama leida (Arduino) ------------- #
    def _wg_identify(self, data):
        """Identifica el formato de una tarjeta a partir de su trama Wiegand.

        Acepta ``bits`` (string de 0/1) o ``hex`` + ``card_bit``. ``target`` es
        el numero impreso en la tarjeta a buscar (opcional).
        """
        bits = (data.get("bits") or "").strip()
        if not bits:
            hx = (data.get("hex") or "").strip()
            cb = data.get("card_bit")
            if not hx or not cb:
                return self._json({"error": "da la trama (bits) o hex + card_bit"}, 400)
            bits = decode.bits_from_hex(hx, int(cb))
        bits = decode.normalize_bits(bits)

        target = data.get("target")
        target = int(target) if target not in (None, "") else None

        # Formatos conocidos (presets) + los que venga en la peticion.
        formats = [PRESETS[n]() for n in PRESETS]
        for s in data.get("formats", []) or []:
            formats.append(format_from_spec(s))

        res = decode.identify(bits, formats, target=target)
        return self._json(
            {
                "bits": bits,
                "card_bit": len(bits),
                "raw_decimal": int(bits, 2),
                "target": target,
                "candidatos": [
                    {
                        "name": d.name,
                        "card_bit": d.card_bit,
                        "parity_ok": d.parity_ok,
                        "site": d.site,
                        "card": d.card,
                        "raw_decimal": d.raw_decimal,
                        "match": d.match,
                        "match_card": d.match_card,
                        "match_site": d.match_site,
                        "match_raw": d.match_raw,
                    }
                    for d in res
                ],
            }
        )

    def _wg_verify_fetch(self, data):
        sn = (data.get("sn") or "").strip()
        if not sn or sn == "all":
            return self._json({"error": "elige un SN especifico"}, 400)
        steps = backup.build_verify_fetch_sequence()
        ids = [zk_panel.enqueue(sn, s.cmd) for s in steps]
        return self._json({"queued": len(ids), "sn": sn})

    def _wg_verify_result(self, data):
        """Lee la ultima copia de ZKDB.db capturada y compara el formato activo."""
        expected = {int(k): v for k, v in (data.get("expected") or {}).items()}
        with zk_panel.LOCK:
            caps = [c for c in zk_panel.G["captures"] if c.get("type", "").startswith("SQLite")]
        if not caps:
            return self._json({"error": "no hay copia de ZKDB.db capturada aun"}, 404)
        path = caps[-1]["path"]
        rows = backup.read_hid_format(path)
        res = backup.verify_active_formats(path, expected) if expected else None
        return self._json(
            {
                "captura": caps[-1]["url"],
                "filas": rows,
                "ok": None if res is None else res.ok,
                "activos": None if res is None else res.activos,
                "problemas": None if res is None else res.problemas,
            }
        )

    def _wg_rollback(self, data):
        sn = (data.get("sn") or "").strip()
        if not sn or sn == "all":
            return self._json({"error": "elige un SN especifico"}, 400)
        steps = backup.build_rollback_sequence()
        ids = [zk_panel.enqueue(sn, s.cmd) for s in steps]
        return self._json({"queued": len(ids), "sn": sn})


def main():
    ap = argparse.ArgumentParser(description="App web local de formatos Wiegand para IN01.")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--myip", help="IP LAN de esta PC (si no se detecta sola)")
    ap.add_argument("--capdir", default="captures")
    args = ap.parse_args()

    zk_panel.CAP_DIR = args.capdir
    os.makedirs(args.capdir, exist_ok=True)

    if args.myip:
        ip = args.myip
    else:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        except Exception:
            ip = "127.0.0.1"
        finally:
            s.close()

    zk_panel.G["myip"] = ip
    zk_panel.G["port"] = args.port

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    zk_panel.log(f"App Wiegand en  http://{ip}:{args.port}/   (panel crudo en /panel)")
    zk_panel.log(
        f"Apunta el reloj: SET OPTIONS WebServerURLModel=0,WebServerPort={args.port},"
        f"ICLOCKSVRURL={ip},IsSupportSSL=0   y luego REBOOT"
    )
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        zk_panel.log("Cerrando.")
        srv.shutdown()


if __name__ == "__main__":
    main()
