#!/usr/bin/env python3
"""
federer_web.py  -  Panel web ligero de Federer.
==================================================================
UI tipo Docker Desktop / Airflow (ligera) que corre en el navegador
para ver y configurar el cluster visualmente. Solo usa la libreria
estandar de Python + el Manager MQTT de federer.py; el frontend es
HTML/CSS/JS vanilla servido desde ./webui (sin build, sin CDN).

Se lanza EXPLICITAMENTE desde la CLI:
  python federer.py --web                 (modo dedicado, bloqueante)
  python federer.py --web --port 9000
  python federer.py --web --no-browser
o desde el menu interactivo con la opcion  'web'.
==================================================================
"""
import os, sys, json, time, threading, subprocess, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import federer as fed   # reutiliza Manager, helpers y constantes

WEBDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webui")
_server = {"httpd": None, "state": None, "url": None}

_CTYPES = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8", ".png": "image/png",
    ".svg": "image/svg+xml", ".ico": "image/x-icon", ".json": "application/json",
}

def _ctype(path):
    return _CTYPES.get(os.path.splitext(path)[1].lower(), "application/octet-stream")

def _f(x): return float(x) if x not in (None, "") else None
def _i(x): return int(x) if x not in (None, "") else None


# ===================== Estado compartido del panel =====================
class WebState:
    def __init__(self):
        self.lock = threading.Lock()
        self.log = []     # consola de eventos (texto)
        self.conv = []    # FedAvg: [{ronda, rmse, dw, n}]
        self.gossip = []  # gossip: [{t, rmse_prom, disp, n}]
        self.train = {"running": False, "kind": None, "started": None, "stop": False}

    def emit(self, msg):
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        with self.lock:
            self.log.append(line)
            del self.log[:-400]
        print("[web]", msg)


def state_json(mgr, st):
    now = time.time()
    with mgr.lock:
        reg = dict(mgr.reg)
    nodes = []
    for nid, r in sorted(reg.items()):
        dt = now - r.get("last_seen", 0)
        nodes.append({
            "id": nid, "online": dt <= fed.HEARTBEAT_TIMEOUT,
            "ip": r.get("ip"), "mac": r.get("mac"), "n": r.get("n"),
            "heap": r.get("heap"), "rssi": r.get("rssi"),
            "round": r.get("last_round"), "mse": r.get("last_mse"),
            "fw": r.get("fw"), "lr": r.get("lr"), "beta": r.get("beta"),
            "epocas": r.get("epocas"), "mode": r.get("mode"), "seen": round(dt, 1),
        })
    with st.lock:
        train = dict(st.train); log = list(st.log[-250:])
        conv = list(st.conv); gossip = list(st.gossip)
    return {"ts": now, "nodes": nodes, "online": mgr.nodos_online(),
            "train": train, "log": log, "conv": conv, "gossip": gossip}


# ===================== Entrenamientos (en hilo) =====================
def _train_fedavg(mgr, st, body):
    import numpy as np, pandas as pd
    nodos = mgr.nodos_online()
    if not nodos:
        st.emit("FedAvg: no hay nodos online"); return
    N = int(body.get("N") or len(nodos))
    maxr = int(body.get("max_rondas") or fed.MAX_RONDAS)
    st.emit(f"FedAvg con {len(nodos)} nodos: {nodos}")
    mgr.enviar_modo("fedavg"); time.sleep(0.5)
    if not os.path.exists("prueba.csv"):
        fed.escribir_prueba(N)
    dfte = pd.read_csv("prueba.csv")
    Xte = dfte[[f"f{i}" for i in range(fed.N_PESOS - 1)]].values; yte = dfte["y"].values
    w_global = np.zeros(fed.N_PESOS)
    log = fed.abrir_csv(fed.LOG_CONV, "ronda,rmse_global,dw,n_nodos")
    with st.lock: st.conv = []
    rmse_prev = None
    for r in range(maxr):
        if st.train["stop"]: st.emit("FedAvg detenido"); break
        mgr.round_actual = r; mgr.round_updates = {}
        mgr.publicar_global(r, w_global)
        t0 = time.time()
        while len(mgr.round_updates) < len(nodos) and time.time() - t0 < fed.TIMEOUT_RONDA:
            if st.train["stop"]: break
            time.sleep(0.1)
        items = list(mgr.round_updates.values())
        if not items: st.emit(f"ronda {r}: sin respuestas"); continue
        total = sum(n for _, n in items)
        w_new = sum(n * w for w, n in items) / total
        dw = float(np.linalg.norm(w_new - w_global)); w_global = w_new
        rmse = float(np.sqrt(np.mean((Xte @ w_global[:-1] + w_global[-1] - yte) ** 2)))
        log.write(f"{r},{rmse:.5f},{dw:.6f},{len(items)}\n"); log.flush()
        with st.lock: st.conv.append({"ronda": r, "rmse": rmse, "dw": dw, "n": len(items)})
        st.emit(f"ronda {r:2d}  RMSE={rmse:.4f}  |dw|={dw:.4f}  ({len(items)}/{len(nodos)})")
        if rmse_prev is not None and dw < fed.EPS_CONVERGENCIA:
            st.emit("convergio"); break
        rmse_prev = rmse
    mgr.round_actual += 1; mgr.publicar_global(mgr.round_actual, w_global, stop=True)
    log.close()
    st.emit("FedAvg finalizado")


def _train_gossip(mgr, st, body):
    import numpy as np, pandas as pd
    nodos = mgr.nodos_online()
    if not nodos:
        st.emit("gossip: no hay nodos online"); return
    N = int(body.get("N") or len(nodos))
    dur = int(body.get("dur") or 60)
    tg = int(body.get("t_gossip") or 3000)
    if not os.path.exists("prueba.csv"):
        fed.escribir_prueba(N)
    dfte = pd.read_csv("prueba.csv")
    Xte = dfte[[f"f{i}" for i in range(fed.N_PESOS - 1)]].values; yte = dfte["y"].values
    with mgr.lock: mgr.gossip = {}
    mgr.enviar_modo("gossip", peers=nodos, t_gossip=tg, report=2000)
    cn = fed.abrir_csv("gossip_nodos.csv", "ts,t_rel,node,rmse_local,exch")
    cc = fed.abrir_csv("gossip_consenso.csv", "ts,t_rel,rmse_prom,dispersion,n_nodos")
    with st.lock: st.gossip = []
    st.emit(f"gossip activo {dur}s (t_gossip={tg}ms, {len(nodos)} nodos)")
    t0 = time.time()
    while time.time() - t0 < dur and not st.train["stop"]:
        time.sleep(2.0)
        trel = time.time() - t0
        with mgr.lock: snap = dict(mgr.gossip)
        if not snap: continue
        rmses, ws = [], []
        for nid, (w, mse, exch) in snap.items():
            rmse = float(np.sqrt(np.mean((Xte @ w[:-1] + w[-1] - yte) ** 2)))
            rmses.append(rmse); ws.append(w)
            cn.write(f"{fed.ahora_iso()},{trel:.1f},{nid},{rmse:.5f},{exch}\n")
        ws = np.array(ws); wmean = ws.mean(axis=0)
        disp = float(np.mean([np.linalg.norm(wi - wmean) for wi in ws]))
        rprom = float(np.mean(rmses))
        cc.write(f"{fed.ahora_iso()},{trel:.1f},{rprom:.5f},{disp:.5f},{len(snap)}\n")
        cn.flush(); cc.flush()
        with st.lock:
            st.gossip.append({"t": round(trel, 1), "rmse_prom": rprom, "disp": disp, "n": len(snap)})
        st.emit(f"t={trel:5.1f}s  RMSE_prom={rprom:.4f}  dispersion={disp:.4f}  ({len(snap)})")
    mgr.enviar_modo("idle"); cn.close(); cc.close()
    st.emit("gossip detenido")


# ===================== Provision / OTA (en hilo) =====================
def _run_pio(st, cmd, ok):
    st.emit("$ " + " ".join(cmd))
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in p.stdout:
            line = line.rstrip()
            if line: st.emit(line)
        p.wait()
        if p.returncode == 0:
            st.emit(ok); return True
        st.emit("fallo la grabacion"); return False
    except FileNotFoundError:
        st.emit("PlatformIO no encontrado: pip install platformio"); return False


def _provision(mgr, st, body):
    nid = int(body.get("node_id", 0)); N = int(body.get("N", 4))
    port = str(body.get("port", "") or "")
    header = os.path.join(fed.FIRMWARE_DIR, "include", "datos_nodo.h")
    n = fed.escribir_header(nid, N, header); fed.escribir_prueba(N)
    st.emit(f"generado datos_nodo.h nodo {nid} (n={n}) + prueba.csv")
    cmd = ["pio", "run", "-e", "esp32dev", "-t", "upload", "-d", fed.FIRMWARE_DIR]
    if port: cmd += ["--upload-port", port]
    _run_pio(st, cmd, f"nodo {nid} grabado por USB")


def _ota(mgr, st, body):
    online = mgr.nodos_online()
    if not online: st.emit("OTA: no hay nodos online"); return
    target = str(body.get("target", "-1"))
    N = int(body.get("N") or len(online))
    ids = online if target == "-1" else [int(target)]
    header = os.path.join(fed.FIRMWARE_DIR, "include", "datos_nodo.h")
    for nid in ids:
        ip = (mgr.reg.get(nid) or {}).get("ip")
        if not ip: st.emit(f"nodo {nid} sin IP"); continue
        st.emit(f"OTA nodo {nid} -> {ip}")
        fed.escribir_header(nid, N, header); fed.escribir_prueba(N)
        cmd = ["pio", "run", "-e", "esp32ota", "-t", "upload", "-d", fed.FIRMWARE_DIR,
               "--upload-port", ip]
        if not _run_pio(st, cmd, f"nodo {nid} actualizado por red"): break


# ===================== Lanzadores de trabajos =====================
def _start_job(st, fn, kind):
    with st.lock:
        if st.train["running"]:
            return {"ok": False, "error": "ocupado: ya hay un trabajo en curso"}
        st.train.update({"running": True, "stop": False, "kind": kind, "started": time.time()})

    def runner():
        try:
            fn()
        except Exception as e:
            st.emit(f"error: {e}")
        finally:
            with st.lock:
                st.train.update({"running": False, "stop": False})
    threading.Thread(target=runner, daemon=True).start()
    return {"ok": True, "kind": kind}


def _start_train(mgr, st, body):
    cfg = str(body.get("config", "A")).upper()
    if cfg == "A":
        return _start_job(st, lambda: _train_fedavg(mgr, st, body), "FedAvg")
    return _start_job(st, lambda: _train_gossip(mgr, st, body), "gossip")


# ===================== Router de POST =====================
def _handle_post(mgr, st, path, body):
    if path == "/api/discover":
        mgr.descubrir(); st.emit("discover enviado"); return {"ok": True}
    if path == "/api/config":
        mgr.enviar_config(_f(body.get("lr")), _f(body.get("beta")), _i(body.get("epocas")))
        st.emit("config enviada"); return {"ok": True}
    if path == "/api/mode":
        mode = body.get("mode", "idle")
        mgr.enviar_modo(mode, body.get("peers"),
                        body.get("t_gossip", 3000), body.get("report", 2000))
        st.emit(f"modo '{mode}' enviado"); return {"ok": True}
    if path == "/api/cmd":
        mgr.enviar_cmd(body.get("cmd", "reboot"), int(body.get("node", -1)))
        st.emit(f"cmd '{body.get('cmd')}' -> nodo {body.get('node')}"); return {"ok": True}
    if path == "/api/train":
        return _start_train(mgr, st, body)
    if path == "/api/train/stop":
        with st.lock: st.train["stop"] = True
        st.emit("solicitando detener..."); return {"ok": True}
    if path == "/api/provision":
        return _start_job(st, lambda: _provision(mgr, st, body), "provision")
    if path == "/api/ota":
        return _start_job(st, lambda: _ota(mgr, st, body), "ota")
    return None


# ===================== Servidor HTTP =====================
def _make_handler(mgr, st):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # silencio
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, (bytes, bytearray)) else str(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj), "application/json")

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/api/state":
                self._json(state_json(mgr, st)); return
            fname = "index.html" if path in ("/", "") else path.lstrip("/")
            fp = os.path.normpath(os.path.join(WEBDIR, fname))
            if not fp.startswith(WEBDIR) or not os.path.isfile(fp):
                self._send(404, "no encontrado", "text/plain"); return
            with open(fp, "rb") as f:
                self._send(200, f.read(), _ctype(fp))

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            ln = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(ln) if ln else b"{}"
            try:
                body = json.loads(raw or b"{}")
            except Exception:
                body = {}
            try:
                res = _handle_post(mgr, st, path, body)
            except Exception as e:
                self._json({"ok": False, "error": str(e)}, 400); return
            if res is None:
                self._json({"ok": False, "error": "ruta no encontrada"}, 404); return
            self._json(res)
    return H


def _make_server(mgr, st, port):
    return ThreadingHTTPServer(("0.0.0.0", port), _make_handler(mgr, st))


def serve_background(mgr, port=8770, open_browser=True):
    """Arranca el panel en un hilo (reutiliza el Manager de la CLI). Devuelve la URL."""
    if _server["httpd"] is not None:
        return _server["url"]
    st = WebState()
    httpd = _make_server(mgr, st, port)
    _server.update({"httpd": httpd, "state": st, "url": f"http://localhost:{port}"})
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    st.emit(f"panel web iniciado en {_server['url']}")
    if open_browser:
        try: webbrowser.open(_server["url"])
        except Exception: pass
    return _server["url"]


def serve(port=8770, open_browser=True):
    """Modo dedicado: crea su propio Manager, arranca MQTT y sirve el panel (bloqueante)."""
    mgr = fed.Manager()
    try:
        mgr.start()
    except Exception as e:
        sys.exit(f"No se pudo conectar al broker {fed.BROKER}:{fed.PUERTO} ({e})")
    st = WebState()
    httpd = _make_server(mgr, st, port)
    url = f"http://localhost:{port}"
    _server.update({"httpd": httpd, "state": st, "url": url})
    print(f"\n  Federer  -  panel web en  {url}\n  (Ctrl+C para salir)\n")
    if open_browser:
        try: webbrowser.open(url)
        except Exception: pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nhasta luego.")
    finally:
        httpd.shutdown()
        mgr.client.loop_stop()


if __name__ == "__main__":
    p = 8770
    if "--port" in sys.argv:
        p = int(sys.argv[sys.argv.index("--port") + 1])
    serve(port=p, open_browser="--no-browser" not in sys.argv)
