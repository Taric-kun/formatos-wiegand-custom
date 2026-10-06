#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
zk_panel.py  -  Panel PUSH/ADMS unificado para relojes ZKTeco ZMM (firmware 8.0.x).

Tres funciones en una sola interfaz web:
  1. Enviar archivo al reloj  (shell wget: directo, dos pasos, o solo wget)
  2. Obtener archivo del reloj (GetFile -> se guarda en captures/<sn>/)
  3. Comandos libres           (cualquier texto PUSH: Shell, GetFile, REBOOT...)

Sin dependencias externas. Python 3.6+.

Uso:
  py zk_panel.py --port 8080 --myip 192.168.3.166
  py zk_panel.py --file e_9.wav --port 8080        (precarga un archivo)

El reloj debe apuntar a esta PC:
  SET OPTIONS WebServerURLModel=0,WebServerPort=8080,ICLOCKSVRURL=<TU_IP>,IsSupportSSL=0
  REBOOT

Abre en el navegador:  http://<TU_IP>:8080/
"""

import argparse
import hashlib
import json
import os
import re
import socket
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote, unquote

# ──────────────────────────── estado global ───────────────────────────────────
LOCK = threading.RLock()   # reentrante: evita deadlock en llamadas anidadas
_SEQ = [0]
CAP_DIR = "captures"

G = {
    "myip":     "",
    "port":     8080,
    "file":     None,      # {"name","data","md5","size"}
    "devices":  {},        # sn -> {"ip","last"}
    "queue":    {},        # sn -> [{"id","text"}]   (por equipo)
    "chunks":   {},        # cmdid -> {"packcnt","parts","sn","name"}
    "captures": [],        # [{"id","sn","name","size","type","ts","url"}]
    "log":      [],
}


def next_id():
    with LOCK:
        _SEQ[0] += 1
        return _SEQ[0]


def log(*a):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] " + " ".join(str(x) for x in a)
    with LOCK:
        G["log"].append(line)
        if len(G["log"]) > 600:
            G["log"] = G["log"][-600:]
    print(line, flush=True)


def enqueue(sn, text):
    """Encola un comando PUSH para un SN (o 'all' para todos los conocidos).

    Si sn='all' y hay dispositivos conocidos, distribuye de inmediato a cada uno.
    Si sn='all' y aún no hay dispositivos, guarda bajo la clave 'all'; se
    distribuye automáticamente cuando el primer equipo haga el handshake.
    """
    cid = next_id()
    with LOCK:
        if sn == "all":
            targets = list(G["devices"].keys())
            if targets:
                for t in targets:
                    G["queue"].setdefault(t, []).append({"id": cid, "text": text})
            else:
                # sin dispositivos aun -> distribucion lazy al conectar
                G["queue"].setdefault("all", []).append({"id": cid, "text": text})
        else:
            G["queue"].setdefault(sn, []).append({"id": cid, "text": text})
    log(f"ENCOLA CmdId={cid} -> {sn}: {text}")
    return cid


# ─────────────────────────── archivo a enviar ─────────────────────────────────
def url_dl():
    f = G["file"]
    return (f"http://{G['myip']}:{G['port']}/dl/{quote(f['name'])}"
            if f else None)


def build_send_cmds(dest, modo, staging):
    url = url_dl()
    if not url:
        return []
    if modo == "solo_wget":
        return [f"shell wget {url}"]
    if modo == "directo":
        return [f"shell wget {url} -O {dest}"]
    name = G["file"]["name"]
    staging = (staging or "/mnt/mtdblock").rstrip("/")
    tmp = f"{staging}/{name}"
    return [f"shell wget {url} -O {tmp}", f"shell mv {tmp} {dest}"]


# ─────────────────────────── captura de archivos ──────────────────────────────
def detectar_tipo(data):
    n = len(data)
    if n == 0:
        return "VACÍO", None
    if all(b == 0 for b in data[:min(4096, n)]):
        return f"EN CEROS ({n}b)", None
    if data[:2] == b"\x1f\x8b":
        return "gzip/tgz", ".tgz"
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "WAV", ".wav"
    if data[:15] == b"SQLite format 3":
        return "SQLite", ".db"
    if data[257:262] == b"ustar":
        return "TAR", ".tar"
    if data[:3] == b"\xff\xd8\xff":
        return "JPEG", ".jpg"
    if data[:4] == b"\x89PNG":
        return "PNG", ".png"
    if data[:2] == b"BM":
        return "BMP", ".bmp"
    if data[:4] == b"PK\x03\x04":
        return "ZIP", ".zip"
    try:
        sample = data[:512]
        sample.decode("utf-8")
        if sum(1 for b in sample if 9 <= b <= 126) / len(sample) > 0.85:
            return "texto", ".txt"
    except Exception:
        pass
    return f"binario ({n}b)", None


def sniff_filename(headers, qs):
    for k in ("filename", "FileName", "name"):
        if k in qs and qs[k]:
            return os.path.basename(qs[k][0])
    cd = headers.get("Content-Disposition", "")
    m = re.search(r'filename="?([^"]+)"?', cd)
    return os.path.basename(m.group(1)) if m else None


def extract_multipart(body, ctype):
    m = re.search(r'boundary=(?:"([^"]+)"|([^;]+))', ctype)
    if not m:
        return None, body
    boundary = ("--" + (m.group(1) or m.group(2)).strip()).encode()
    for part in body.split(boundary):
        if b"Content-Disposition" not in part:
            continue
        hdr, _, content = part.partition(b"\r\n\r\n")
        if not content:
            continue
        content = content.rstrip(b"\r\n")
        nm = re.search(rb'filename="?([^"\r\n]+)"?', hdr)
        name = os.path.basename(nm.group(1).decode(errors="replace")) if nm else None
        if name:
            return name, content
    return None, body


def _persistir(sn, fname, data):
    """Escribe el archivo en captures/<sn>/ y registra la captura."""
    desc, ext = detectar_tipo(data)
    if ext and not os.path.splitext(fname)[1]:
        fname += ext
    sn_dir = os.path.join(CAP_DIR, re.sub(r"[^\w\-]", "_", sn or "desconocido"))
    os.makedirs(sn_dir, exist_ok=True)
    ts_str = datetime.now().strftime("%H%M%S")
    fname_safe = re.sub(r"[^\w.\-]", "_", fname)
    ruta = os.path.join(sn_dir, f"{ts_str}_{fname_safe}")
    with open(ruta, "wb") as fh:
        fh.write(data)
    url = f"/captures/{os.path.basename(sn_dir)}/{os.path.basename(ruta)}"
    cap = {
        "id":   next_id(),
        "sn":   sn,
        "name": fname,
        "size": len(data),
        "type": desc,
        "ts":   datetime.now().strftime("%H:%M:%S"),
        "path": ruta,
        "url":  url,
    }
    with LOCK:
        G["captures"].append(cap)
        if len(G["captures"]) > 100:
            G["captures"] = G["captures"][-100:]
    log(f"[{sn}] ✓ CAPTURADO  {ruta}  ({len(data)}b, {desc})")
    return cap


def save_upload(sn, name, data, cmdid=None, packcnt=None, packidx=None):
    if not packcnt or packcnt <= 1:
        fname = name or f"upload_{datetime.now().strftime('%H%M%S')}.bin"
        return _persistir(sn, fname, data)
    key = str(cmdid)
    with LOCK:
        st = G["chunks"].setdefault(
            key, {"packcnt": packcnt, "parts": {}, "sn": sn, "name": name}
        )
        st["parts"][packidx] = data
        recibidas = len(st["parts"])
    log(f"[{sn}] CHUNK CmdId={cmdid} parte {packidx}/{packcnt} [{recibidas}/{packcnt}]")
    if recibidas >= packcnt:
        with LOCK:
            st = G["chunks"].pop(key)
        assembled = b"".join(st["parts"][i] for i in sorted(st["parts"]))
        return _persistir(sn, st["name"] or f"getfile_{key}.bin", assembled)
    return None


# ─────────────────────────────── panel HTML ───────────────────────────────────
PANEL = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ZK Commander</title>
<style>
:root{
  --blue:#00AFF2;--yellow:#FFBD00;
  --bg:#0e1621;--panel:#16222f;--panel2:#1c2b3a;
  --ink:#e8eef4;--muted:#8ba0b3;--line:#243546;
  --ok:#38d39f;--err:#ff5d6c;
  --mono:'Cascadia Code',Consolas,'SF Mono',monospace;
  --sans:'Segoe UI',system-ui,sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:14px}

/* header */
header{display:flex;align-items:center;gap:12px;padding:13px 20px;
  background:linear-gradient(90deg,#0b3a52,#0e1621);border-bottom:2px solid var(--blue)}
.dot{width:11px;height:11px;border-radius:50%;background:var(--yellow);box-shadow:0 0 9px var(--yellow)}
header h1{font-size:15px;font-weight:600;letter-spacing:.2px}
header .sub{color:var(--muted);font-size:12px;margin-left:auto}

/* tabs */
.tab-bar{display:flex;gap:3px;padding:14px 20px 0}
.tab-btn{background:var(--panel2);border:1px solid var(--line);border-bottom:none;
  color:var(--muted);padding:8px 16px;border-radius:8px 8px 0 0;cursor:pointer;
  font:500 13px var(--sans);transition:color .15s}
.tab-btn.active{background:var(--panel);color:var(--ink)}
.tab-pane{display:none;padding:16px 20px;background:var(--panel);
  border:1px solid var(--line);margin:0 20px;border-radius:0 8px 8px 8px}
.tab-pane.active{display:grid;grid-template-columns:1fr 1fr;gap:16px}

/* cards */
.card{background:var(--panel2);border:1px solid var(--line);border-radius:9px;padding:15px}
.full{grid-column:1/-1}
.card h2{font-size:11px;text-transform:uppercase;letter-spacing:1px;
  color:var(--blue);font-weight:700;margin-bottom:11px}

/* forms */
label.lbl{display:block;font-size:12px;color:var(--muted);margin:9px 0 4px}
input[type=text],textarea,select{
  width:100%;background:var(--bg);border:1px solid var(--line);
  color:var(--ink);border-radius:6px;padding:8px 11px;
  font:13px var(--mono)}
input:focus,textarea:focus,select:focus{outline:none;border-color:var(--blue)}
textarea{resize:vertical;min-height:90px}
input[type=file]{color:var(--muted);font-size:13px;width:100%}
select option{background:var(--panel2)}

/* radio */
.radios{display:flex;gap:7px;flex-wrap:wrap;margin-top:5px}
.radios label{display:flex;align-items:center;gap:5px;padding:6px 11px;
  background:var(--bg);border:1px solid var(--line);border-radius:6px;
  cursor:pointer;font-size:12px;color:var(--ink)}
.radios label.sel{border-color:var(--blue);background:#12354a}
.radios input{accent-color:var(--blue)}

/* quick path chips */
.qchips{display:flex;gap:5px;flex-wrap:wrap;margin-top:6px}
.qchip{font-size:11px;padding:4px 10px;background:var(--bg);border:1px solid var(--line);
  border-radius:12px;cursor:pointer;color:var(--muted);font-family:var(--mono)}
.qchip:hover{border-color:var(--blue);color:var(--blue)}

/* cmd preview */
.cmdbox{background:#0a1017;border:1px solid var(--line);border-left:3px solid var(--yellow);
  border-radius:6px;padding:9px 12px;font:12px var(--mono);color:#b9eeb9;
  white-space:pre-wrap;word-break:break-all;line-height:1.7;margin-top:7px;min-height:34px}

/* buttons */
.btn{background:var(--blue);color:#04222f;border:none;border-radius:7px;
  padding:9px 15px;font:700 13px var(--sans);cursor:pointer}
.btn:hover{filter:brightness(1.08)}
.btn.ghost{background:transparent;color:var(--muted);border:1px solid var(--line)}
.btn.yellow{background:var(--yellow)}
.btn:disabled{opacity:.4;cursor:not-allowed}
.row{display:flex;gap:8px;align-items:center;margin-top:11px;flex-wrap:wrap}

/* device chip */
.devchip{display:inline-flex;align-items:center;gap:6px;font-size:12px;
  color:var(--muted);background:var(--bg);border:1px solid var(--line);
  border-radius:20px;padding:4px 11px}
.devchip .d{width:8px;height:8px;border-radius:50%;background:var(--muted)}
.devchip.on .d{background:var(--ok);box-shadow:0 0 7px var(--ok)}

/* captures table */
.captbl{width:100%;border-collapse:collapse;font-size:12px;margin-top:7px}
.captbl th{text-align:left;padding:5px 9px;color:var(--muted);font-weight:600;
  border-bottom:1px solid var(--line)}
.captbl td{padding:5px 9px;border-bottom:1px solid #1a2d3e;word-break:break-all}
.captbl tr:hover td{background:#1a283a}
.badge{display:inline-block;padding:2px 7px;border-radius:10px;font-size:11px;
  background:var(--bg);border:1px solid var(--line);color:var(--muted)}

/* log */
.wrap{padding:14px 20px;display:grid;gap:14px}
#logbox{background:#0a1017;border:1px solid var(--line);border-radius:8px;
  padding:11px;font:12px/1.65 var(--mono);height:260px;overflow:auto;
  white-space:pre-wrap;color:#b0c5d6}
#logbox .ok{color:var(--ok)}
#logbox .err{color:var(--err)}
#logbox .hi{color:var(--yellow)}

.hint{font-size:12px;color:var(--muted);margin-top:8px;line-height:1.6}
.hint b,.hint code{color:var(--ink)}
.meta{font-size:12px;color:var(--muted);margin-top:7px;line-height:1.6}
.meta b{color:var(--ink)}
.empty{color:var(--muted);font-size:12px;padding:10px 0;display:block}

@media(max-width:700px){
  .tab-pane.active{grid-template-columns:1fr}
  .full{grid-column:1}
}
</style>
</head>
<body>

<header>
  <span class="dot"></span>
  <h1>ZK Commander — Panel Unificado</h1>
  <span class="sub" id="hdrsub">—</span>
</header>

<div class="tab-bar">
  <button class="tab-btn active" onclick="setTab('send',this)">📤 Enviar archivo</button>
  <button class="tab-btn"        onclick="setTab('get',this)">📥 Obtener archivo</button>
  <button class="tab-btn"        onclick="setTab('cmd',this)">⌨️ Comando libre</button>
</div>

<!-- ── TAB ENVIAR ─────────────────────────────────────────────────────────── -->
<div id="tab-send" class="tab-pane active">
  <div class="card">
    <h2>Archivo a enviar</h2>
    <label class="lbl">Selecciona el archivo local</label>
    <input type="file" id="filein">
    <div class="meta" id="filemeta">Ningún archivo cargado.</div>
  </div>
  <div class="card">
    <h2>Destino en el reloj</h2>
    <label class="lbl">Ruta destino exacta (se reemplaza si existe)</label>
    <input type="text" id="dest" value="/mnt/mtdblock/wav/e_9.wav">
    <label class="lbl">Modo</label>
    <div class="radios" id="moderow">
      <label class="sel"><input type="radio" name="modo" value="directo" checked> Directo (wget -O)</label>
      <label><input type="radio" name="modo" value="dospasos"> Dos pasos (wget + mv)</label>
      <label><input type="radio" name="modo" value="solo_wget"> Solo wget</label>
    </div>
    <div id="stagewrap" style="display:none;margin-top:9px">
      <label class="lbl">Carpeta temporal (staging)</label>
      <input type="text" id="staging" value="/mnt/mtdblock">
    </div>
    <div class="hint" id="solohint" style="display:none">
      Manda solo <b>shell wget &lt;url&gt;</b> sin destino.<br>
      El archivo cae en el directorio de trabajo del reloj.
    </div>
  </div>
  <div class="card full">
    <h2>Comando que se enviará al reloj</h2>
    <div class="cmdbox" id="preview">— carga un archivo para ver el comando —</div>
    <div class="row">
      <button class="btn" id="btnqueue" disabled>Encolar al reloj</button>
      <button class="btn ghost" onclick="clearAll()">Limpiar log y cola</button>
      <span class="devchip" id="devchip"><span class="d"></span><span id="devtxt">Sin relojes</span></span>
    </div>
  </div>
</div>

<!-- ── TAB OBTENER ────────────────────────────────────────────────────────── -->
<div id="tab-get" class="tab-pane">
  <div class="card">
    <h2>Solicitar archivo al reloj (GetFile)</h2>
    <label class="lbl">Ruta en el reloj</label>
    <input type="text" id="gf-path" value="/mnt/mtdblock/data/ZKDB.db">
    <label class="lbl">Rutas rápidas</label>
    <div class="qchips">
      <span class="qchip" onclick="q('gf-path').value='/mnt/mtdblock/data/ZKDB.db'">ZKDB.db</span>
      <span class="qchip" onclick="q('gf-path').value='/mnt/mtdblock/wav/'">wav/</span>
      <span class="qchip" onclick="q('gf-path').value='/mnt/mtdblock/data/'">data/</span>
      <span class="qchip" onclick="q('gf-path').value='/mnt/mtdblock/app/'">app/</span>
      <span class="qchip" onclick="q('gf-path').value='/mnt/mtdblock/service/'">service/</span>
      <span class="qchip" onclick="q('gf-path').value='/tmp/'">tmp/</span>
    </div>
    <label class="lbl" style="margin-top:10px">SN destino</label>
    <select id="gf-sn"><option value="all">Todos (all)</option></select>
    <div class="row">
      <button class="btn yellow" onclick="sendGetFile()">Obtener archivo del reloj</button>
    </div>
    <div class="hint" style="margin-top:10px">
      El reloj sube el archivo en su próximo <b>getrequest</b>.<br>
      Aparece en la tabla de la derecha para descargar.
    </div>
  </div>
  <div class="card">
    <h2>Archivos capturados</h2>
    <div id="cap-list"><span class="empty">Ningún archivo capturado aún.</span></div>
  </div>
</div>

<!-- ── TAB COMANDO LIBRE ──────────────────────────────────────────────────── -->
<div id="tab-cmd" class="tab-pane">
  <div class="card full">
    <h2>Enviar comando libre</h2>
    <label class="lbl">
      Comando PUSH — el servidor lo envuelve en <code style="color:var(--yellow)">C:&lt;id&gt;:&lt;aquí&gt;</code>
    </label>
    <textarea id="rawcmd" placeholder="Ejemplos (una línea por comando):
shell ls -la /mnt/mtdblock/wav/
GetFile /mnt/mtdblock/data/ZKDB.db
shell tar czf /tmp/backup.tgz /mnt/mtdblock/data/
SET OPTION IRTempDetectionFunOn=1
REBOOT"></textarea>

    <label class="lbl" style="margin-top:10px">Comandos rápidos</label>
    <div class="qchips">
      <span class="qchip" onclick="insertCmd('shell ls -la /mnt/mtdblock/wav/')">ls wav/</span>
      <span class="qchip" onclick="insertCmd('shell ls -la /mnt/mtdblock/data/')">ls data/</span>
      <span class="qchip" onclick="insertCmd('shell ls -la /mnt/mtdblock/')">ls mtdblock/</span>
      <span class="qchip" onclick="insertCmd('shell ls -la /tmp/')">ls /tmp/</span>
      <span class="qchip" onclick="insertCmd('shell df -h')">df -h</span>
      <span class="qchip" onclick="insertCmd('shell free')">free</span>
      <span class="qchip" onclick="insertCmd('shell cat /proc/version')">versión kernel</span>
      <span class="qchip" onclick="insertCmd('shell ps')">ps</span>
      <span class="qchip" onclick="insertCmd('REBOOT')">REBOOT</span>
      <span class="qchip" onclick="insertCmd('INFO')">INFO</span>
      <span class="qchip" onclick="insertCmd('CHECK')">CHECK</span>
    </div>

    <label class="lbl" style="margin-top:10px">SN destino</label>
    <select id="raw-sn"><option value="all">Todos (all)</option></select>

    <div class="row">
      <button class="btn" onclick="sendRaw()">Enviar comando</button>
      <button class="btn ghost" onclick="q('rawcmd').value=''">Limpiar</button>
    </div>
    <div class="hint" style="margin-top:10px">
      Una línea = un comando. Se encolan en orden.<br>
      Si el comando es <b>GetFile</b>, el archivo subido por el reloj
      aparece en la pestaña <b>Obtener archivo</b>.
    </div>
  </div>
</div>

<!-- ── SIEMPRE VISIBLE: LOG ───────────────────────────────────────────────── -->
<div class="wrap">
  <div class="card" style="background:var(--panel);border:1px solid var(--line);
      border-radius:10px;padding:15px">
    <h2 style="color:var(--blue);font-size:11px;text-transform:uppercase;
        letter-spacing:1px;margin-bottom:9px">
      Registro en vivo
      <span style="float:right;font-size:11px;text-transform:none;
          letter-spacing:0;color:var(--muted)" id="devinfo"></span>
    </h2>
    <div id="logbox">Esperando actividad…</div>
    <div class="row" style="margin-top:8px">
      <button class="btn ghost" onclick="clearAll()">Limpiar log</button>
    </div>
  </div>
</div>

<script>
function q(id){return document.getElementById(id)}

// ── tabs ─────────────────────────────────────────────────────────────────────
function setTab(name,btn){
  document.querySelectorAll('.tab-pane').forEach(p=>p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
  q('tab-'+name).classList.add('active');
  btn.classList.add('active');
}

// ── tab: enviar archivo ───────────────────────────────────────────────────────
let FILE_READY=false, DEST='', MODO='directo', STAGING='/mnt/mtdblock';
q('filein').addEventListener('change',async e=>{
  const f=e.target.files[0]; if(!f)return;
  const buf=await f.arrayBuffer();
  const r=await fetch('/api/setfile?name='+encodeURIComponent(f.name),{method:'POST',body:buf});
  const j=await r.json();
  q('filemeta').innerHTML='<b>'+j.name+'</b> &mdash; '+j.size+' bytes<br>MD5: '+j.md5+'<br>URL: <span style="color:#7ec8e3">'+j.url+'</span>';
  FILE_READY=true; refreshPreview();
});
q('dest').addEventListener('input',refreshPreview);
q('staging')&&q('staging').addEventListener('input',refreshPreview);
document.querySelectorAll('input[name=modo]').forEach(r=>r.addEventListener('change',e=>{
  MODO=e.target.value;
  document.querySelectorAll('#moderow label').forEach(l=>l.classList.remove('sel'));
  e.target.closest('label').classList.add('sel');
  q('stagewrap').style.display=MODO==='dospasos'?'block':'none';
  q('solohint').style.display=MODO==='solo_wget'?'block':'none';
  q('dest').disabled=MODO==='solo_wget';
  refreshPreview();
}));
async function refreshPreview(){
  DEST=q('dest').value.trim();
  STAGING=q('staging')?q('staging').value.trim():'/mnt/mtdblock';
  if(!FILE_READY){q('preview').textContent='— carga un archivo para ver el comando —';return;}
  const r=await fetch('/api/preview?dest='+encodeURIComponent(DEST)+'&modo='+MODO+'&staging='+encodeURIComponent(STAGING));
  const j=await r.json();
  q('preview').textContent=j.cmds.map(c=>'C:<id>:'+c).join('\n');
  q('btnqueue').disabled=false;
}
q('btnqueue').addEventListener('click',async ()=>{
  await fetch('/api/queue?dest='+encodeURIComponent(DEST)+'&modo='+MODO+'&staging='+encodeURIComponent(STAGING),{method:'POST'});
  tick();
});

// ── tab: obtener archivo ──────────────────────────────────────────────────────
async function sendGetFile(){
  const path=q('gf-path').value.trim(); if(!path)return;
  const sn=q('gf-sn').value;
  await fetch('/api/getfile',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({path,sn})});
  tick();
}

// ── tab: comando libre ────────────────────────────────────────────────────────
function insertCmd(text){
  const ta=q('rawcmd');
  const val=ta.value.trim();
  ta.value=(val?val+'\n':'')+text;
}
async function sendRaw(){
  const raw=q('rawcmd').value.trim(); if(!raw)return;
  const sn=q('raw-sn').value;
  const lines=raw.split('\n').map(l=>l.trim()).filter(Boolean);
  for(const line of lines){
    await fetch('/api/raw',{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({cmd:line,sn})});
  }
  tick();
}

// ── helpers ───────────────────────────────────────────────────────────────────
async function clearAll(){await fetch('/api/clear',{method:'POST'});tick();}

function paint(line){
  const esc=line.replace(/&/g,'&amp;').replace(/</g,'&lt;');
  if(/Return=0|ÉXITO|✓ CAPTURADO/.test(esc)) return '<span class="ok">'+esc+'</span>';
  if(/Return=-|✗|EN CEROS|VACÍO/.test(esc))  return '<span class="err">'+esc+'</span>';
  if(/ENCOLA|ENTREGA|DESCARGA|CAPTURADO|CHUNK/.test(esc)) return '<span class="hi">'+esc+'</span>';
  return esc;
}

function renderCaptures(caps){
  if(!caps||!caps.length){
    q('cap-list').innerHTML='<span class="empty">Ningún archivo capturado aún.</span>';return;
  }
  let h='<table class="captbl"><thead><tr><th>Hora</th><th>SN</th><th>Archivo</th><th>Tipo</th><th></th></tr></thead><tbody>';
  for(const c of [...caps].reverse()){
    h+=`<tr>
      <td>${c.ts}</td>
      <td style="color:var(--blue);font-family:var(--mono)">${c.sn}</td>
      <td style="font-family:var(--mono)">${c.name} <span class="badge">${c.size}b</span></td>
      <td style="color:var(--muted)">${c.type}</td>
      <td><a href="${c.url}" download="${c.name}"
         style="color:var(--blue);text-decoration:none;font-size:13px">⬇</a></td>
    </tr>`;
  }
  q('cap-list').innerHTML=h+'</tbody></table>';
}

function updateSelects(devices){
  const sns=Object.keys(devices);
  ['gf-sn','raw-sn'].forEach(id=>{
    const sel=q(id); if(!sel)return;
    const cur=sel.value;
    sel.innerHTML='<option value="all">Todos (all)</option>'+
      sns.map(s=>`<option value="${s}">${s}</option>`).join('');
    if(sns.includes(cur))sel.value=cur;
  });
}

async function tick(){
  try{
    const r=await fetch('/api/state'); const s=await r.json();
    q('hdrsub').textContent=(s.myip||'')+(s.port?':'+s.port:'')+(s.file?' · '+s.file:'');
    const lb=q('logbox');
    const atBottom=lb.scrollHeight-lb.scrollTop-lb.clientHeight<40;
    lb.innerHTML=s.log.map(paint).join('\n')||'Esperando actividad…';
    if(atBottom)lb.scrollTop=lb.scrollHeight;
    const n=Object.keys(s.devices).length;
    q('devchip').classList.toggle('on',n>0);
    q('devtxt').textContent=n>0?(n+' reloj'+(n>1?'es':'')+' · '+Object.keys(s.devices).join(', ')):'Sin relojes';
    q('devinfo').textContent=n>0?(n+' reloj'+(n>1?'es':'')+' conectado'+(n>1?'s':'')):'';
    renderCaptures(s.captures);
    updateSelects(s.devices);
  }catch(e){}
}
setInterval(tick,1500); tick();
</script>
</body>
</html>
"""


# ──────────────────────────── HTTP handler ────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, body, ctype="text/plain; charset=utf-8", code=200):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.close_connection = True
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def _json(self, obj, code=200):
        self._send(json.dumps(obj, ensure_ascii=False), "application/json; charset=utf-8", code)

    def _sn(self, qs):
        return (qs.get("SN") or qs.get("sn") or [""])[0]

    # ── GET ──────────────────────────────────────────────────────────────────
    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        qs = parse_qs(u.query)
        sn = self._sn(qs)

        # Panel
        if p in ("/", "/index.html"):
            return self._send(PANEL, "text/html; charset=utf-8")

        # API estado
        if p == "/api/state":
            with LOCK:
                return self._json({
                    "myip":     G["myip"],
                    "port":     G["port"],
                    "file":     G["file"]["name"] if G["file"] else None,
                    "devices":  dict(G["devices"]),
                    "captures": list(G["captures"]),
                    "log":      G["log"][-400:],
                })

        # API preview de comandos de envío
        if p == "/api/preview":
            dest    = (qs.get("dest")    or ["/mnt/mtdblock/wav/e_9.wav"])[0]
            modo    = (qs.get("modo")    or ["directo"])[0]
            staging = (qs.get("staging") or ["/mnt/mtdblock"])[0]
            return self._json({"cmds": build_send_cmds(dest, modo, staging)})

        # Servir archivo para que el reloj lo descargue (wget)
        if p.startswith("/dl/"):
            f = G["file"]
            if f and unquote(p) == f"/dl/{f['name']}":
                sn_log = sn or "?"
                log(f"[{sn_log}] DESCARGA del archivo ({f['size']} bytes) ✓ wget entendido")
                return self._send(f["data"], "application/octet-stream")
            return self._send("not found", code=404)

        # Servir archivos capturados (para descargar desde el panel)
        if p.startswith("/captures/"):
            parts = p.lstrip("/").split("/")
            if len(parts) == 3:
                safe_sn  = re.sub(r"[^\w\-]", "_", parts[1])
                safe_fn  = re.sub(r"[^\w.\-]", "_", parts[2])
                ruta = os.path.join(CAP_DIR, safe_sn, safe_fn)
                if os.path.isfile(ruta):
                    with open(ruta, "rb") as fh:
                        data = fh.read()
                    return self._send(data, "application/octet-stream")
            return self._send("not found", code=404)

        # ── Protocolo PUSH ──────────────────────────────────────────────────

        # Handshake
        if p.endswith("/cdata") and ("options" in qs or "pushver" in qs):
            self._touch(sn)
            return self._send(self._options(sn))

        # Polling de comandos
        if p.endswith("/getrequest"):
            self._touch(sn)
            with LOCK:
                pendientes = G["queue"].pop(sn, [])
            if pendientes:
                lineas = "\n".join(f"C:{c['id']}:{c['text']}" for c in pendientes)
                log(f"[{sn}] ENTREGA: {lineas}")
                return self._send(lineas + "\n")
            return self._send("OK")

        if p.endswith(("/cdata", "/ping")):
            self._touch(sn)
            return self._send("OK")

        return self._send("OK")

    # ── POST ─────────────────────────────────────────────────────────────────
    def do_POST(self):
        u = urlparse(self.path)
        p = u.path
        qs = parse_qs(u.query)
        sn = self._sn(qs)
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else b""
        ctype = self.headers.get("Content-Type", "")

        # ── API del panel ────────────────────────────────────────────────────

        if p == "/api/setfile":
            name = os.path.basename((qs.get("name") or ["archivo.bin"])[0])
            md5  = hashlib.md5(body).hexdigest()
            with LOCK:
                G["file"] = {"name": name, "data": body, "md5": md5, "size": len(body)}
            log(f"Archivo cargado: {name} ({len(body)}b, MD5={md5})")
            return self._json({"name": name, "size": len(body), "md5": md5, "url": url_dl()})

        if p == "/api/queue":
            dest    = (qs.get("dest")    or ["/mnt/mtdblock/wav/e_9.wav"])[0]
            modo    = (qs.get("modo")    or ["directo"])[0]
            staging = (qs.get("staging") or ["/mnt/mtdblock"])[0]
            cmds = build_send_cmds(dest, modo, staging)
            if not cmds:
                return self._json({"error": "no hay archivo cargado"}, 400)
            sn_target = "all"
            for c in cmds:
                enqueue(sn_target, c)
            return self._json({"queued": len(cmds)})

        if p == "/api/getfile":
            try:
                data = json.loads(body)
                path   = data.get("path", "").strip()
                target = data.get("sn", "all")
            except Exception:
                return self._json({"error": "json inválido"}, 400)
            if not path:
                return self._json({"error": "path vacío"}, 400)
            cid = enqueue(target, f"GetFile {path}")
            return self._json({"queued": 1, "cmdid": cid})

        if p == "/api/raw":
            try:
                data   = json.loads(body)
                cmd = data.get("cmd", "").strip().replace("\\t", "\t")
                target = data.get("sn", "all")
            except Exception:
                return self._json({"error": "json inválido"}, 400)
            if not cmd:
                return self._json({"error": "cmd vacío"}, 400)
            cid = enqueue(target, cmd)
            return self._json({"queued": 1, "cmdid": cid})

        if p == "/api/clear":
            with LOCK:
                G["queue"].clear()
                G["log"].clear()
                G["captures"].clear()
            log("Cola, capturas y log limpiados.")
            return self._json({"ok": True})

        # ── Protocolo PUSH ────────────────────────────────────────────────────

        if p.endswith("/devicecmd"):
            self._touch(sn)
            # GetFile embebe el archivo en el body con "Content=" (firmware ZMM 8.0.x)
            marca = b"\nContent="
            pos = body.find(marca)
            if pos == -1 and body.startswith(b"Content="):
                pos, marca = 0, b"Content="
            if pos != -1:
                cabecera  = body[:pos].decode(errors="replace")
                contenido = body[pos + len(marca):]
                m = re.search(r"FILENAME=([^\r\n]+)", cabecera)
                nombre = os.path.basename(m.group(1).strip()) if m else \
                         f"getfile_{datetime.now().strftime('%H%M%S')}.bin"
                log(f"[{sn}] GetFile reply: {cabecera.strip()[:160]} ({len(contenido)}b)")
                save_upload(sn, nombre, contenido)
                return self._send("OK")

            # Reporte normal: ID=..&Return=..&CMD=..
            txt = body.decode(errors="replace")
            ret = cid = None
            for tok in txt.replace("\n", "&").split("&"):
                tok = tok.strip()
                if tok.startswith("Return="):
                    try: ret = int(tok.split("=",1)[1])
                    except ValueError: pass
                elif tok.startswith("ID="):
                    try: cid = int(tok.split("=",1)[1])
                    except ValueError: pass
            if ret == 0:
                log(f"[{sn}] ✓ ÉXITO (CmdId={cid}, Return=0)")
            elif ret is not None:
                log(f"[{sn}] ✗ Return={ret} (CmdId={cid}) — revisa ruta/permisos")
            else:
                log(f"[{sn}] devicecmd: {txt.strip()[:200]}")
            return self._send("OK")

        # Subida de archivos (GetFile vía /fdata o /cdata con CmdId)
        if p.endswith(("/fdata", "/cdata")) or "CmdId" in qs:
            self._touch(sn)
            cmdid   = (qs.get("CmdId") or qs.get("cmdid") or [None])[0]
            packcnt = int((qs.get("PackCnt") or ["0"])[0] or 0)
            packidx = int((qs.get("PackIdx") or ["0"])[0] or 0)
            nombre  = sniff_filename(self.headers, qs)
            data_to_save = body
            if "multipart" in ctype:
                nm, data_to_save = extract_multipart(body, ctype)
                nombre = nombre or nm
            if data_to_save:
                save_upload(sn, nombre, data_to_save, cmdid, packcnt, packidx)
            return self._send("OK")

        return self._send("OK")

    # ── helpers ───────────────────────────────────────────────────────────────
    def _touch(self, sn):
        if not sn:
            return
        with LOCK:
            nuevo = sn not in G["devices"]
            G["devices"][sn] = {"ip": self.client_address[0],
                                "last": datetime.now().strftime("%H:%M:%S")}
            if nuevo:
                # distribuir comandos pendientes encolados para "all" antes de conectar
                pendientes_all = G["queue"].pop("all", [])
                if pendientes_all:
                    G["queue"].setdefault(sn, []).extend(pendientes_all)
        if nuevo:
            log(f"NUEVO EQUIPO SN={sn} IP={self.client_address[0]}")

    def _options(self, sn):
        t = int(time.time())
        return (f"GET OPTION FROM: {sn}\nStamp={t}\nOpStamp={t}\n"
                f"ErrorDelay=10\nDelay=3\nTransTimes=00:00;23:59\n"
                f"TransInterval=1\nTransFlag=1111111111\nTimeZone=-4\n"
                f"Realtime=1\nEncrypt=0\nServerVer=1.0 zk_panel\n")


# ─────────────────────────────── main ────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(
        description="Panel PUSH/ADMS unificado para relojes ZKTeco ZMM.")
    ap.add_argument("--host",   default="0.0.0.0")
    ap.add_argument("--port",   type=int, default=8080)
    ap.add_argument("--myip",   help="IP LAN de esta PC (si no se detecta sola)")
    ap.add_argument("--file",   help="Archivo local a precargar para envío")
    ap.add_argument("--capdir", default="captures",
                    help="Carpeta donde guardar archivos capturados del reloj")
    args = ap.parse_args()

    global CAP_DIR
    CAP_DIR = args.capdir
    os.makedirs(CAP_DIR, exist_ok=True)

    # Detectar IP
    if args.myip:
        ip = args.myip
    else:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]
        except Exception:
            ip = "127.0.0.1"
        finally:
            s.close()

    G["myip"] = ip
    G["port"] = args.port

    if args.file:
        if not os.path.isfile(args.file):
            raise SystemExit(f"No existe: {args.file}")
        data = open(args.file, "rb").read()
        name = os.path.basename(args.file)
        G["file"] = {"name": name, "data": data,
                     "md5": hashlib.md5(data).hexdigest(), "size": len(data)}

    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    log(f"Panel en  http://{ip}:{args.port}/")
    log(f"Capturas  -> ./{CAP_DIR}/")
    if G["file"]:
        log(f"Archivo precargado: {G['file']['name']} ({G['file']['size']}b)")
    log(f"Apunta el reloj: SET OPTIONS WebServerURLModel=0,WebServerPort={args.port},"
        f"ICLOCKSVRURL={ip},IsSupportSSL=0   y luego REBOOT")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log("Cerrando.")
        srv.shutdown()


if __name__ == "__main__":
    main()
