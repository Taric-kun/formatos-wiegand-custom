"use strict";
const $ = (id) => document.getElementById(id);
const api = async (path, body) => {
  const r = await fetch(path, body ? {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
  } : undefined);
  const j = await r.json().catch(() => ({ error: "respuesta no-JSON" }));
  if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));
  return j;
};
const msg = (el, text, kind) => {
  el.textContent = text; el.className = "msg show " + (kind || "");
  if (!text) el.className = "msg";
};

// Estado del editor
let cur = { name: "", card_format: "", parities: [], format_type: 1, status: 1, site_code: 0 };
let tabla = [];          // lista de specs a cargar
let presets = {};        // name -> spec

// ---------- posiciones de paridad ----------
function parityPositions(cf, kind) {
  const ch = kind === "even" ? "E" : "O";
  const out = []; for (let i = 0; i < cf.length; i++) if (cf[i] === ch) out.push(i);
  return out;
}
// índice del propio bit de una paridad (el n-ésimo E/O), según su orden dentro de su tipo
function ownPosition(parity, orderInKind) {
  return parityPositions(cur.card_format, parity.kind)[orderInKind];
}

// ---------- reconciliar parities con el card_format ----------
function reconcileParities() {
  const cf = cur.card_format;
  const nE = parityPositions(cf, "even").length;
  const nO = parityPositions(cf, "odd").length;
  const evens = cur.parities.filter(p => p.kind === "even");
  const odds = cur.parities.filter(p => p.kind === "odd");
  const fix = (arr, kind, n) => {
    const res = [];
    for (let i = 0; i < n; i++) {
      const prev = arr[i] || { kind, covers: [] };
      const pPositions = new Set([...parityPositions(cf, "even"), ...parityPositions(cf, "odd")]);
      prev.kind = kind;
      prev.covers = (prev.covers || []).filter(ix => ix >= 0 && ix < cf.length && !pPositions.has(ix));
      res.push(prev);
    }
    return res;
  };
  cur.parities = fix(evens, "even", nE).concat(fix(odds, "odd", nO));
}

// ---------- render ----------
function charClass(c) { return "EOSC".includes(c) ? c : ""; }

function renderBits() {
  const cf = cur.card_format, box = $("bitsview"); box.innerHTML = "";
  for (let i = 0; i < cf.length; i++) {
    const d = document.createElement("div");
    d.className = "bit " + charClass(cf[i]);
    d.innerHTML = `<span class="ix">${i}</span><span>${cf[i]}</span>`;
    d.title = "Click: alterna S/C";
    d.onclick = () => {
      if (cf[i] === "S") setChar(i, "C");
      else if (cf[i] === "C") setChar(i, "S");
    };
    box.appendChild(d);
  }
}
function setChar(i, c) {
  const a = cur.card_format.split(""); a[i] = c; cur.card_format = a.join("");
  $("cardfmt").value = cur.card_format; onEdit();
}

function renderParities() {
  const box = $("parities"); box.innerHTML = "";
  const cf = cur.card_format;
  const counts = { even: 0, odd: 0 };
  cur.parities.forEach((p) => {
    const order = counts[p.kind]++;
    const own = ownPosition(p, order);
    const pPositions = new Set([...parityPositions(cf, "even"), ...parityPositions(cf, "odd")]);
    const wrap = document.createElement("div"); wrap.className = "parityrow";
    const label = p.kind === "even" ? "Paridad PAR" : "Paridad IMPAR";
    const slot = p.kind === "even" ? (order === 0 ? "First_Even" : "Second_Even")
                                   : (order === 0 ? "First_Odd" : "Second_Odd");
    wrap.innerHTML = `<div class="plabel">${label} #${order + 1} → <b>${slot}</b> (bit ${own}). Click para cubrir/quitar.</div>`;
    const bits = document.createElement("div"); bits.className = "bits";
    for (let i = 0; i < cf.length; i++) {
      const b = document.createElement("div");
      const covered = p.covers.includes(i);
      const disabled = pPositions.has(i);
      b.className = "bit " + charClass(cf[i]) + (covered ? " cov" : "");
      b.style.opacity = disabled ? ".35" : "1";
      b.innerHTML = `<span class="ix">${i}</span><span>${cf[i]}</span>`;
      if (!disabled) b.onclick = () => {
        const k = p.covers.indexOf(i);
        if (k >= 0) p.covers.splice(k, 1); else p.covers.push(i);
        p.covers.sort((a, b) => a - b);
        renderParities(); previewMasks();
      };
      bits.appendChild(b);
    }
    wrap.appendChild(bits); box.appendChild(wrap);
  });
}

function readFields() {
  cur.name = $("name").value.trim();
  cur.site_code = parseInt($("sitecode").value || "0", 10);
  cur.format_type = parseInt($("ftype").value, 10);
  cur.status = parseInt($("status").value, 10);
}

async function previewMasks() {
  readFields();
  try {
    const body = { formats: [cur], modo: "rewrite" };
    const site = $("smpsite").value, card = $("smpcard").value;
    if (site !== "" || card !== "") body.sample = { site: +site || 0, card: +card || 0 };
    const j = await api("/api/wg/preview", body);
    const row = j.rows[0];
    $("maskview").innerHTML =
      `Card_Bit ${row.Card_Bit}<br>Card_Format&nbsp; ${row.Card_Format}<br>` +
      `First_Even&nbsp; ${row.First_Even ?? "NULL"}<br>` +
      (row.Second_Even ? `Second_Even ${row.Second_Even}<br>` : "") +
      `First_Odd&nbsp;&nbsp; ${row.First_Odd ?? "NULL"}` +
      (row.Second_Odd ? `<br>Second_Odd&nbsp; ${row.Second_Odd}` : "");
    $("frameview").textContent = j.sample_frame ? ("trama: " + j.sample_frame) : "—";
    $("cfbadge").innerHTML = '<span class="badge ok">válido</span>';
    msg($("editmsg"), "", "");
  } catch (e) {
    $("cfbadge").innerHTML = '<span class="badge err">revisar</span>';
    msg($("editmsg"), e.message, "err");
  }
}

function onEdit() {
  cur.card_format = $("cardfmt").value.toUpperCase();
  $("cardfmt").value = cur.card_format;
  reconcileParities();
  renderBits(); renderParities(); previewMasks();
}

function applyPreset(name) {
  const s = JSON.parse(JSON.stringify(presets[name]));
  cur = { name: s.name, card_format: s.card_format, parities: s.parities,
          format_type: s.format_type, status: s.status, site_code: s.site_code };
  $("name").value = cur.name; $("sitecode").value = cur.site_code;
  $("ftype").value = cur.format_type; $("status").value = cur.status;
  $("cardfmt").value = cur.card_format;
  renderBits(); renderParities(); previewMasks();
}

function autoSplit() {
  const cf = cur.card_format;
  const dataIdx = []; for (let i = 0; i < cf.length; i++) if ("SCFM".includes(cf[i])) dataIdx.push(i);
  const half = Math.floor(dataIdx.length / 2);
  let e = 0, o = 0;
  cur.parities.forEach(p => {
    if (p.kind === "even") p.covers = dataIdx.slice(0, half);
    else p.covers = dataIdx.slice(half);
  });
  renderParities(); previewMasks();
}

// ---------- tabla ----------
function addToTabla() {
  readFields();
  tabla.push(JSON.parse(JSON.stringify(cur)));
  renderTabla();
}
function renderTabla() {
  const box = $("tablalist"); box.innerHTML = "";
  if (!tabla.length) { box.innerHTML = '<div class="hint">Sin formatos aún.</div>'; return; }
  tabla.forEach((f, i) => {
    const d = document.createElement("div"); d.className = "item";
    d.innerHTML = `<span class="nm">${f.name}</span>
      <span class="meta">${f.card_format} · tipo ${f.format_type} · Status ${f.status}</span>
      <span class="x" title="quitar">✕</span>`;
    d.querySelector(".x").onclick = () => { tabla.splice(i, 1); renderTabla(); };
    box.appendChild(d);
  });
}

async function generate() {
  try {
    const j = await api("/api/wg/build", {
      formats: tabla, modo: $("modo").value, filename: $("filename").value.trim() || "u.sql"
    });
    $("sqlview").textContent = j.sql;
    msg($("genmsg"), `Generado ${j.name} · ${j.size} bytes · MD5 ${j.md5}`, "ok");
  } catch (e) { msg($("genmsg"), e.message, "err"); }
}

// ---------- carga ----------
async function loadPreview() {
  try {
    const j = await api("/api/wg/load_preview", { sn: $("sn").value, backup: $("dobackup").checked });
    $("loadview").style.display = "block";
    $("loadview").textContent = j.steps.map(s => `${s.cmd}\n   # ${s.descripcion}`).join("\n");
    msg($("loadmsg"), "", "");
  } catch (e) { msg($("loadmsg"), e.message, "err"); }
}
async function doLoad() {
  const sn = $("sn").value;
  if (!sn || sn === "all") { msg($("loadmsg"), "Elige un SN específico.", "err"); return; }
  if (!confirm(`Cargar en ${sn} y REINICIAR el reloj. ¿Continuar?`)) return;
  try {
    const j = await api("/api/wg/load", { sn, backup: $("dobackup").checked });
    msg($("loadmsg"), `Encolados ${j.queued} comandos a ${j.sn}. El reloj los ejecuta en su próximo sondeo.`, "ok");
  } catch (e) { msg($("loadmsg"), e.message, "err"); }
}
async function doRollback() {
  const sn = $("sn").value;
  if (!sn || sn === "all") { msg($("loadmsg"), "Elige un SN específico.", "err"); return; }
  if (!confirm(`Rollback en ${sn}: quita update.sql, restaura ZKDB desde la copia y reinicia. ¿Continuar?`)) return;
  try {
    const j = await api("/api/wg/rollback", { sn });
    msg($("loadmsg"), `Rollback encolado (${j.queued} comandos) a ${j.sn}.`, "ok");
  } catch (e) { msg($("loadmsg"), e.message, "err"); }
}

// ---------- verificación ----------
async function verifyFetch() {
  const sn = $("sn").value;
  if (!sn || sn === "all") { msg($("vmsg"), "Elige un SN específico.", "err"); return; }
  try {
    const j = await api("/api/wg/verify_fetch", { sn });
    msg($("vmsg"), `Solicitada copia de ZKDB.db a ${j.sn}. Aparecerá en el panel al próximo sondeo.`, "ok");
  } catch (e) { msg($("vmsg"), e.message, "err"); }
}
async function verifyCheck() {
  const expected = {}; expected[cur.format_type] = cur.name;
  try {
    const j = await api("/api/wg/verify_result", { expected });
    $("vview").style.display = "block";
    const lines = j.filas.map(f => `${f.Status === 1 ? "●" : "○"} tipo ${f.Format_Type}  ${f.Format_Name}  (${f.Card_Bit}b)`).join("\n");
    $("vview").textContent = lines || "(sin filas)";
    if (j.ok === true) msg($("vmsg"), "Formato activo esperado: OK", "ok");
    else if (j.ok === false) msg($("vmsg"), "Problemas: " + (j.problemas || []).join("; "), "err");
    else msg($("vmsg"), "Copia leída; sin comparación.", "ok");
  } catch (e) { msg($("vmsg"), e.message, "err"); }
}

// ---------- dispositivos (poll) ----------
async function tick() {
  try {
    const s = await (await fetch("/api/state")).json();
    const sns = Object.keys(s.devices || {});
    const sel = $("sn"), cur_sn = sel.value;
    sel.innerHTML = sns.length ? sns.map(x => `<option value="${x}">${x}</option>`).join("")
                               : '<option value="">(sin relojes)</option>';
    if (sns.includes(cur_sn)) sel.value = cur_sn;
    const n = sns.length;
    $("devchip").classList.toggle("on", n > 0);
    $("devtxt").textContent = n ? (n + " reloj" + (n > 1 ? "es" : "") + " · " + sns.join(", ")) : "Sin relojes";
    $("hdrsub").innerHTML = `${s.myip || ""}${s.port ? ":" + s.port : ""} · <a href="/panel">Panel ZK Commander →</a>`;
  } catch (e) {}
}

// ---------- init ----------
async function init() {
  const j = await api("/api/wg/presets");
  presets = {}; j.presets.forEach(p => presets[p.name] = p);
  $("preset").innerHTML = j.presets.map(p =>
    `<option value="${p.name}">${p.name}${p.estado ? " (" + p.estado + ")" : ""}</option>`).join("");
  $("preset").onchange = () => applyPreset($("preset").value);
  $("cardfmt").oninput = onEdit;
  $("name").oninput = previewMasks; $("sitecode").oninput = previewMasks;
  $("ftype").onchange = previewMasks; $("status").onchange = previewMasks;
  $("smpsite").oninput = previewMasks; $("smpcard").oninput = previewMasks;
  $("btnautosplit").onclick = autoSplit;
  $("btnadd").onclick = addToTabla;
  $("btngen").onclick = generate;
  $("btnloadprev").onclick = loadPreview;
  $("btnload").onclick = doLoad;
  $("btnrollback").onclick = doRollback;
  $("btnvfetch").onclick = verifyFetch;
  $("btnvcheck").onclick = verifyCheck;
  applyPreset(j.presets[0].name);
  renderTabla();
  setInterval(tick, 2000); tick();
}
init();
