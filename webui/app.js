"use strict";

// ---------------- helpers ----------------
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);
const MODE_NAME = { 0: "idle", 1: "fedavg", 2: "gossip" };

function toast(msg, isErr) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast show" + (isErr ? " err" : "");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (t.className = "toast"), 2600);
}

async function api(path, body) {
  try {
    const r = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    const j = await r.json();
    if (!j.ok) { toast(j.error || "error", true); return j; }
    toast("✓ " + path.replace("/api/", ""));
    refresh();
    return j;
  } catch (e) { toast("sin conexión con Federer", true); }
}

// ---------------- navegación ----------------
$$(".nav-item").forEach((b) =>
  b.addEventListener("click", () => {
    $$(".nav-item").forEach((x) => x.classList.remove("active"));
    $$(".view").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    $("#" + b.dataset.view).classList.add("active");
  })
);

// ---------------- acciones ----------------
$("#btn-discover").onclick = () => api("/api/discover");
$("#btn-config").onclick = () =>
  api("/api/config", { lr: $("#cf-lr").value, beta: $("#cf-beta").value, epocas: $("#cf-ep").value });
$$(".btn.mode").forEach((b) => (b.onclick = () => api("/api/mode", { mode: b.dataset.mode })));
$$("[data-cmd]").forEach((b) =>
  (b.onclick = () => api("/api/cmd", { cmd: b.dataset.cmd, node: $("#cmd-node").value || -1 }))
);
$("#btn-fedavg").onclick = () =>
  api("/api/train", { config: "A", N: $("#fa-N").value, max_rondas: $("#fa-rondas").value });
$("#btn-gossip").onclick = () =>
  api("/api/train", { config: "B", N: $("#go-N").value, dur: $("#go-dur").value, t_gossip: $("#go-tg").value });
$("#btn-stop").onclick = () => api("/api/train/stop");
$("#btn-provision").onclick = () =>
  api("/api/provision", { node_id: $("#pv-id").value, N: $("#pv-N").value, port: $("#pv-port").value });
$("#btn-ota").onclick = () =>
  api("/api/ota", { target: $("#ota-target").value || "-1", N: $("#ota-N").value });

// ---------------- render ----------------
function badgeMode(m) {
  const name = typeof m === "number" ? MODE_NAME[m] : m;
  if (name === "fedavg") return '<span class="badge fedavg">fedavg</span>';
  if (name === "gossip") return '<span class="badge gossip">gossip</span>';
  if (name === "idle") return '<span class="badge idle">idle</span>';
  return '<span class="badge idle">–</span>';
}

function render(s) {
  // conexión
  $("#conn").className = "conn on";
  $("#conn").innerHTML = '<span class="dot"></span> conectado';

  // cards
  $("#s-online").textContent = s.online.length;
  $("#s-total").textContent = s.nodes.length;
  const modes = [...new Set(s.nodes.filter((n) => n.online).map((n) => MODE_NAME[n.mode] || "?"))];
  $("#s-mode").textContent = modes.length ? modes.join("/") : "–";
  const tr = s.train;
  $("#s-job").textContent = tr.running ? (tr.kind || "activo") : "inactivo";

  // tabla
  const tb = $("#nodes tbody");
  if (!s.nodes.length) {
    tb.innerHTML = '<tr><td colspan="12" class="empty">sin nodos…</td></tr>';
  } else {
    tb.innerHTML = s.nodes
      .map(
        (n) => `<tr>
        <td>${n.id}</td>
        <td>${n.online ? '<span class="badge on">online</span>' : '<span class="badge off">perdido</span>'}</td>
        <td>${badgeMode(n.mode)}</td>
        <td>${n.ip || "–"}</td>
        <td>${n.n ?? "–"}</td>
        <td>${n.heap ?? "–"}</td>
        <td>${n.rssi ?? "–"}</td>
        <td>${n.round ?? "–"}</td>
        <td>${n.mse != null ? Number(n.mse).toFixed(3) : "–"}</td>
        <td>${n.fw || "–"}</td>
        <td>${n.seen}s</td>
        <td><button class="btn" onclick="api('/api/cmd',{cmd:'reboot',node:${n.id}})">⟳</button></td>
      </tr>`
      )
      .join("");
  }

  // estado de entrenamiento
  const st = $("#train-state");
  if (tr.running) {
    const secs = tr.started ? Math.round(s.ts - tr.started) : 0;
    st.className = "badge run";
    st.textContent = `${tr.kind || "activo"} · ${secs}s`;
    $("#btn-stop").disabled = false;
  } else {
    st.className = "badge idle";
    st.textContent = "inactivo";
    $("#btn-stop").disabled = true;
  }

  // logs
  const logTxt = s.log.join("\n");
  setLog("#full-log", logTxt);
  setLog("#train-log", logTxt);
  setLog("#fw-log", logTxt);

  // charts
  drawConv(s.conv);
  drawGossip(s.gossip);
}

function setLog(sel, txt) {
  const el = $(sel);
  if (!el) return;
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  el.textContent = txt;
  if (atBottom) el.scrollTop = el.scrollHeight;
}

// ---------------- charts (canvas vanilla) ----------------
function lineChart(canvas, series, opts) {
  opts = opts || {};
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.height;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);
  const pad = { l: 44, r: 12, t: 12, b: 24 };
  const W = w - pad.l - pad.r, H = h - pad.t - pad.b;

  const all = series.flatMap((s) => s.pts);
  if (!all.length) {
    ctx.fillStyle = "#8b97a7"; ctx.font = "13px sans-serif";
    ctx.fillText("sin datos todavía…", pad.l, pad.t + H / 2);
    return;
  }
  const xs = all.map((p) => p.x), ys = all.map((p) => p.y);
  let minX = Math.min(...xs), maxX = Math.max(...xs);
  let minY = Math.min(...ys), maxY = Math.max(...ys);
  if (minX === maxX) maxX += 1;
  if (minY === maxY) maxY += 1;
  const padY = (maxY - minY) * 0.1; minY -= padY; maxY += padY;
  const X = (x) => pad.l + ((x - minX) / (maxX - minX)) * W;
  const Y = (y) => pad.t + H - ((y - minY) / (maxY - minY)) * H;

  // grid + ejes Y
  ctx.strokeStyle = "#2b3340"; ctx.fillStyle = "#8b97a7";
  ctx.font = "11px monospace"; ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const yy = pad.t + (H / 4) * i;
    const val = maxY - ((maxY - minY) / 4) * i;
    ctx.beginPath(); ctx.moveTo(pad.l, yy); ctx.lineTo(w - pad.r, yy); ctx.stroke();
    ctx.fillText(val.toFixed(2), 4, yy + 3);
  }

  // series
  series.forEach((s) => {
    if (!s.pts.length) return;
    ctx.strokeStyle = s.color; ctx.lineWidth = 2; ctx.beginPath();
    s.pts.forEach((p, i) => (i ? ctx.lineTo(X(p.x), Y(p.y)) : ctx.moveTo(X(p.x), Y(p.y))));
    ctx.stroke();
    ctx.fillStyle = s.color;
    s.pts.forEach((p) => { ctx.beginPath(); ctx.arc(X(p.x), Y(p.y), 2.5, 0, 7); ctx.fill(); });
  });

  // leyenda
  let lx = pad.l;
  series.forEach((s) => {
    ctx.fillStyle = s.color; ctx.fillRect(lx, h - 14, 12, 4);
    ctx.fillStyle = "#b9c4d2"; ctx.font = "11px sans-serif";
    ctx.fillText(s.label, lx + 16, h - 10);
    lx += 24 + ctx.measureText(s.label).width + 16;
  });
}

function drawConv(conv) {
  lineChart($("#chart-conv"), [
    { pts: conv.map((d) => ({ x: d.ronda, y: d.rmse })), color: "#2ecc71", label: "RMSE global" },
  ]);
}
function drawGossip(g) {
  lineChart($("#chart-gossip"), [
    { pts: g.map((d) => ({ x: d.t, y: d.rmse_prom })), color: "#3b82f6", label: "RMSE prom" },
    { pts: g.map((d) => ({ x: d.t, y: d.disp })), color: "#EE7623", label: "dispersión" },
  ]);
}

// ---------------- loop ----------------
async function refresh() {
  try {
    const r = await fetch("/api/state");
    render(await r.json());
  } catch (e) {
    $("#conn").className = "conn off";
    $("#conn").innerHTML = '<span class="dot"></span> sin conexión';
  }
}
window.api = api; // usado por botones inline
refresh();
setInterval(refresh, 1500);
