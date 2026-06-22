#!/usr/bin/env python3
"""
Federer  -  gestor del mini-cluster ESP32 (aprendizaje federado).
==================================================================
Como el tenista: "Fed"erated + Federer. Plano de control tipo kubectl
donde los "nodos" son ESP32 que entrenan con FedAvg. Soporta grabado por
red (OTA), nodos sueltos en Wi-Fi y registro ampliado de metricas.

Plano de control (MQTT):
  cluster/announce  nodo -> Federer   identidad + telemetria (heartbeat)
  cluster/discover  Federer -> nodos  ping de descubrimiento
  cluster/config    Federer -> nodos  {lr, beta, epocas}
  cluster/cmd       Federer -> nodos  {cmd:"reboot"|"reset", node:id|-1}
Plano de datos (FedAvg):
  fedavg/global / fedavg/update  (update trae metricas ampliadas)

Requisitos:
  pip install paho-mqtt rich numpy pandas scikit-learn platformio

Uso:
  python federer.py            menu interactivo (CLI)
  python federer.py --web      panel web en el navegador (UI visual)
                               opciones: --port <N>  --no-browser
  (tambien desde el menu: opcion 'web')
==================================================================
"""
import os, sys, json, time, threading, subprocess, datetime
import numpy as np
import pandas as pd

try:
    import paho.mqtt.client as mqtt
except ImportError:
    sys.exit("Falta paho-mqtt:  pip install paho-mqtt")
try:
    from rich.console import Console
    from rich.table import Table
    from rich.live import Live
    from rich.panel import Panel
    from rich.prompt import Prompt
except ImportError:
    sys.exit("Falta rich:  pip install rich")

# ----------------------- Configuracion -----------------------
BROKER, PUERTO = "localhost", 1883
T_ANNOUNCE, T_DISCOVER = "cluster/announce", "cluster/discover"
T_CONFIG, T_CMD = "cluster/config", "cluster/cmd"
T_GLOBAL, T_UPDATE = "fedavg/global", "fedavg/update"
T_MODE, T_GREPORT = "cluster/mode", "gossip/report"

FIRMWARE_DIR = "./firmware_esp32"   # proyecto PlatformIO (src/main.cpp)
DATASET_CSV  = None                 # ruta a Crop_recommendation.csv, o None (kagglehub)
N_PESOS = 7
FEATURES = ["N","P","temperature","humidity","ph","rainfall"]
TARGET, SEED, TEST_SIZE = "K", 42, 0.20

HEARTBEAT_TIMEOUT = 15
MAX_RONDAS, TIMEOUT_RONDA, EPS_CONVERGENCIA = 30, 30.0, 1e-3

LOG_CONV = "convergencia_fedavg.csv"
LOG_MET  = "metricas_fedavg.csv"
LOG_TEL  = "telemetria_cluster.csv"
# -------------------------------------------------------------

console = Console()
RAQUETA = r"""
        .-~~~~-.
       /  ::::  \      [bold yellow]FEDERER[/bold yellow]
      |  ::::::  |     gestor del mini-cluster ESP32
      |  ::::::  |     aprendizaje federado (FedAvg) + OTA
       \  ::::  /
        '-.  .-'
          |  |
          |  |
         /____\
"""

def ahora_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")

def abrir_csv(path, header):
    nuevo = (not os.path.exists(path)) or os.path.getsize(path) == 0
    f = open(path, "a")
    if nuevo:
        f.write(header + "\n"); f.flush()
    return f

# ============ dataset / particion (para provision/ota) ============
_cache = {}
def cargar_dataset():
    if "df" in _cache: return _cache["df"]
    if DATASET_CSV and os.path.exists(DATASET_CSV):
        df = pd.read_csv(DATASET_CSV)
    else:
        import kagglehub
        from kagglehub import KaggleDatasetAdapter
        df = kagglehub.load_dataset(KaggleDatasetAdapter.PANDAS,
            "atharvaingle/crop-recommendation-dataset", "Crop_recommendation.csv")
    if "label" in df.columns: df = df.drop(columns=["label"])
    _cache["df"] = df
    return df

def preparar_split(N):
    from sklearn.model_selection import train_test_split
    from sklearn.preprocessing import StandardScaler
    df = cargar_dataset()
    X = df[FEATURES].values.astype(np.float64); y = df[TARGET].values.astype(np.float64)
    Xtr,Xte,ytr,yte = train_test_split(X,y,test_size=TEST_SIZE,random_state=SEED)
    sc = StandardScaler().fit(Xtr)
    rng = np.random.default_rng(SEED); idx = rng.permutation(len(ytr))
    return {"partes":np.array_split(idx,N),"Xtr":sc.transform(Xtr),"ytr":ytr,
            "Xte":sc.transform(Xte),"yte":yte,"mean":sc.mean_,"std":sc.scale_}

def _fila(v): return "{" + ",".join(f"{x:.6f}f" for x in v) + "}"

def escribir_header(node_id, N, path):
    s = preparar_split(N); sel = s["partes"][node_id]
    X,y,mean,std = s["Xtr"][sel], s["ytr"][sel], s["mean"], s["std"]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path,"w") as f:
        f.write("#ifndef DATOS_NODO_H\n#define DATOS_NODO_H\n\n")
        f.write(f"#define NODE_ID {node_id}\n#define N_FEATURES {len(FEATURES)}\n")
        f.write(f"#define N_SAMPLES {len(y)}\n\n")
        f.write("const float FEAT_MEAN[N_FEATURES] = "+_fila(mean)+";\n")
        f.write("const float FEAT_STD[N_FEATURES]  = "+_fila(std)+";\n\n")
        f.write("const float X_LOCAL[N_SAMPLES][N_FEATURES] = {\n")
        for i in range(len(y)):
            f.write("  "+_fila(X[i])+("," if i<len(y)-1 else "")+"\n")
        f.write("};\nconst float Y_LOCAL[N_SAMPLES] = {\n  ")
        f.write(",".join(f"{v:.6f}f" for v in y)+"\n};\n\n#endif\n")
    return len(y)

def escribir_prueba(N, path="prueba.csv"):
    s = preparar_split(N)
    cols = [f"f{i}" for i in range(len(FEATURES))]
    d = pd.DataFrame(s["Xte"], columns=cols); d["y"] = s["yte"]
    d.to_csv(path, index=False)

# ===================== Manager (MQTT) =========================
class Manager:
    def __init__(self):
        self.reg = {}; self.lock = threading.Lock()
        self.round_actual = -1; self.round_updates = {}; self.gossip = {}
        self.f_met = None; self.f_tel = None
        self.client = mqtt.Client(client_id="federer", protocol=mqtt.MQTTv311)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    def start(self):
        self.f_met = abrir_csv(LOG_MET, "ts,ronda,node,n,mse,rmse,train_ms,heap,min_heap,rssi")
        self.f_tel = abrir_csv(LOG_TEL, "ts,node,ip,mac,heap,rssi,fw,lr,beta,epocas")
        self.client.connect(BROKER, PUERTO, keepalive=60)
        self.client.loop_start(); time.sleep(0.6); self.descubrir()

    def _on_connect(self, c,u,flags,rc,properties=None):
        c.subscribe(T_ANNOUNCE,1); c.subscribe(T_UPDATE,1); c.subscribe(T_GREPORT,1)

    def _on_message(self, c,u,msg):
        try: d = json.loads(msg.payload.decode())
        except Exception: return
        if msg.topic == T_ANNOUNCE:
            with self.lock:
                nid = d["node"]; r = self.reg.get(nid, {})
                r.update({k:d.get(k) for k in ("mac","ip","n","heap","rssi","fw","lr","beta","epocas")})
                r["last_seen"] = time.time(); self.reg[nid] = r
                self.f_tel.write(f'{ahora_iso()},{nid},{d.get("ip","")},{d.get("mac","")},'
                                 f'{d.get("heap","")},{d.get("rssi","")},{d.get("fw","")},'
                                 f'{d.get("lr","")},{d.get("beta","")},{d.get("epocas","")}\n')
                self.f_tel.flush()
        elif msg.topic == T_UPDATE:
            with self.lock:
                nid = d["node"]
                if nid in self.reg:
                    self.reg[nid]["last_round"] = d.get("round")
                    self.reg[nid]["last_mse"]   = d.get("mse")
                self.f_met.write(f'{ahora_iso()},{d.get("round")},{nid},{d.get("n")},'
                                 f'{d.get("mse")},{d.get("rmse","")},{d.get("train_ms","")},'
                                 f'{d.get("heap","")},{d.get("min_heap","")},{d.get("rssi","")}\n')
                self.f_met.flush()
                if d.get("round") == self.round_actual:
                    self.round_updates[nid] = (np.array(d["w"], float), float(d["n"]))
        elif msg.topic == T_GREPORT:
            with self.lock:
                self.gossip[d["node"]] = (np.array(d["w"], float),
                                          float(d.get("mse", float("nan"))),
                                          int(d.get("exch", 0)))

    def descubrir(self): self.client.publish(T_DISCOVER, "{}", qos=1)
    def enviar_config(self, lr=None,beta=None,epocas=None):
        m = {k:v for k,v in (("lr",lr),("beta",beta),("epocas",epocas)) if v is not None}
        self.client.publish(T_CONFIG, json.dumps(m), qos=1)
    def enviar_cmd(self, cmd, node=-1):
        self.client.publish(T_CMD, json.dumps({"cmd":cmd,"node":node}), qos=1)
    def publicar_global(self, ronda, w, stop=False):
        self.client.publish(T_GLOBAL, json.dumps(
            {"round":int(ronda),"w":list(map(float,w)),"stop":stop}), qos=1)
    def enviar_modo(self, mode, peers=None, t_gossip=3000, report=2000):
        m = {"mode": mode, "t_gossip": int(t_gossip), "report": int(report)}
        if peers is not None: m["peers"] = list(peers)
        self.client.publish(T_MODE, json.dumps(m), qos=1)
    def nodos_online(self):
        t = time.time()
        with self.lock:
            return sorted(n for n,r in self.reg.items()
                          if t - r.get("last_seen",0) <= HEARTBEAT_TIMEOUT)

# ===================== Vistas / comandos ======================
def tabla_nodos(mgr):
    t = Table(title="nodos del cluster", expand=True)
    for c in ("ID","Estado","IP","MAC","Muestras","Heap","RSSI","Ronda","MSE","Visto"):
        t.add_column(c)
    now = time.time()
    with mgr.lock: items = sorted(mgr.reg.items())
    if not items: t.add_row("-","[dim]sin nodos[/dim]","","","","","","","","")
    for nid,r in items:
        dt = now - r.get("last_seen",0); on = dt <= HEARTBEAT_TIMEOUT
        t.add_row(str(nid), "[green]online[/green]" if on else "[red]perdido[/red]",
                  str(r.get("ip","")), str(r.get("mac","")), str(r.get("n","")),
                  str(r.get("heap","")), str(r.get("rssi","")), str(r.get("last_round","-")),
                  (f'{r["last_mse"]:.3f}' if r.get("last_mse") is not None else "-"), f"{dt:.0f}s")
    return t

def cmd_watch(mgr):
    console.print("[dim](Ctrl+C para volver al menu)[/dim]"); mgr.descubrir()
    try:
        with Live(tabla_nodos(mgr), refresh_per_second=2, console=console) as live:
            while True: time.sleep(0.5); live.update(tabla_nodos(mgr))
    except KeyboardInterrupt: pass

def cmd_describe(mgr):
    try: nid = int(Prompt.ask("ID del nodo"))
    except ValueError: return
    with mgr.lock: r = mgr.reg.get(nid)
    if not r: console.print("[red]nodo no encontrado[/red]"); return
    console.print(Panel.fit(json.dumps(r, indent=2, default=str), title=f"nodo {nid}"))

def cmd_config(mgr):
    lr = Prompt.ask("lr (enter=sin cambio)", default="")
    beta = Prompt.ask("beta", default=""); ep = Prompt.ask("epocas", default="")
    mgr.enviar_config(float(lr) if lr else None, float(beta) if beta else None,
                      int(ep) if ep else None)
    console.print("[green]config enviada[/green]")

def cmd_provision(mgr):
    console.print("[bold]Provisionar nuevo ESP32 (USB, primera vez)[/bold]")
    online = mgr.nodos_online(); sug = (max(online)+1) if online else 0
    nid = int(Prompt.ask("NODE_ID a asignar", default=str(sug)))
    N = int(Prompt.ask("tamano del cluster (N)", default="4"))
    puerto = Prompt.ask("puerto USB (enter=auto)", default="")
    header = os.path.join(FIRMWARE_DIR,"include","datos_nodo.h")
    n = escribir_header(nid,N,header); escribir_prueba(N)
    console.print(f"  {header} (n={n}) + prueba.csv")
    cmd = ["pio","run","-e","esp32dev","-t","upload","-d",FIRMWARE_DIR]
    if puerto: cmd += ["--upload-port", puerto]
    _correr(cmd, f"nodo {nid} grabado por USB")

def cmd_ota(mgr):
    console.print("[bold]Actualizar firmware por red (OTA)[/bold]")
    online = mgr.nodos_online()
    if not online: console.print("[red]no hay nodos online[/red]"); return
    obj = Prompt.ask("nodo a actualizar (-1 = todos los online)", default="-1")
    N = int(Prompt.ask("tamano del cluster (N) para regenerar particion", default=str(len(online))))
    ids = online if obj == "-1" else [int(obj)]
    header = os.path.join(FIRMWARE_DIR,"include","datos_nodo.h")
    for nid in ids:
        ip = (mgr.reg.get(nid) or {}).get("ip")
        if not ip: console.print(f"[red]nodo {nid} sin IP[/red]"); continue
        console.print(f"[bold]OTA nodo {nid} -> {ip}[/bold]")
        escribir_header(nid,N,header); escribir_prueba(N)
        cmd = ["pio","run","-e","esp32ota","-t","upload","-d",FIRMWARE_DIR,"--upload-port",ip]
        if not _correr(cmd, f"nodo {nid} actualizado por red"): break

def _correr(cmd, ok):
    console.print(f"[dim]$ {' '.join(cmd)}[/dim]")
    try:
        subprocess.run(cmd, check=True); console.print(f"[green]{ok}[/green]"); return True
    except FileNotFoundError:
        console.print("[red]PlatformIO no encontrado:  pip install platformio[/red]"); return False
    except subprocess.CalledProcessError:
        console.print("[red]fallo la grabacion[/red]"); return False

def cmd_reboot(mgr):
    nid = Prompt.ask("ID a reiniciar (-1 = todos)", default="-1")
    accion = Prompt.ask("accion", choices=["reboot","reset"], default="reboot")
    mgr.enviar_cmd(accion, node=int(nid)); console.print(f"[green]'{accion}' enviado[/green]")

def cmd_metrics(mgr):
    console.print("[bold]Archivos de metricas (revisables con pandas/Excel):[/bold]")
    for f in (LOG_MET, LOG_CONV, LOG_TEL):
        ok = os.path.exists(f) and os.path.getsize(f) > 0
        console.print(f"  {f}  {'[green]ok[/green]' if ok else '[dim]aun vacio[/dim]'}")
    if os.path.exists(LOG_MET) and os.path.getsize(LOG_MET) > 0:
        df = pd.read_csv(LOG_MET)
        console.print(f"\nmetricas por nodo/ronda  ({len(df)} registros, ultimas 8):")
        t = Table(expand=True)
        for c in df.columns: t.add_column(c)
        for _, row in df.tail(8).iterrows():
            t.add_row(*[str(row[c]) for c in df.columns])
        console.print(t)

def train_fedavg(mgr):
    nodos = mgr.nodos_online()
    if not nodos: console.print("[red]no hay nodos online[/red]"); return
    console.print(f"[bold]Config A (FedAvg)[/bold] con {len(nodos)} nodos: {nodos}")
    mgr.enviar_modo("fedavg"); time.sleep(0.5)
    if not os.path.exists("prueba.csv"):
        N = int(Prompt.ask("falta prueba.csv; N del cluster", default=str(len(nodos))))
        escribir_prueba(N)
    dfte = pd.read_csv("prueba.csv")
    Xte = dfte[[f"f{i}" for i in range(N_PESOS-1)]].values; yte = dfte["y"].values
    w_global = np.zeros(N_PESOS)
    log = abrir_csv(LOG_CONV, "ronda,rmse_global,dw,n_nodos")
    rmse_prev = None
    for r in range(MAX_RONDAS):
        mgr.round_actual = r; mgr.round_updates = {}
        mgr.publicar_global(r, w_global)
        t0 = time.time()
        while len(mgr.round_updates) < len(nodos) and time.time()-t0 < TIMEOUT_RONDA:
            time.sleep(0.1)
        items = list(mgr.round_updates.values())
        if not items: console.print(f"[yellow]ronda {r}: sin respuestas[/yellow]"); continue
        total = sum(n for _,n in items)
        w_new = sum(n*w for w,n in items) / total
        dw = float(np.linalg.norm(w_new - w_global)); w_global = w_new
        rmse = float(np.sqrt(np.mean((Xte @ w_global[:-1] + w_global[-1] - yte)**2)))
        log.write(f"{r},{rmse:.5f},{dw:.6f},{len(items)}\n"); log.flush()
        console.print(f"  ronda {r:2d}  RMSE_global={rmse:.4f}  |dw|={dw:.4f}  ({len(items)}/{len(nodos)})")
        if rmse_prev is not None and dw < EPS_CONVERGENCIA:
            console.print("[green]convergio[/green]"); break
        rmse_prev = rmse
    mgr.round_actual += 1; mgr.publicar_global(mgr.round_actual, w_global, stop=True)
    log.close()
    console.print(f"[green]listo[/green] -> {LOG_CONV} y {LOG_MET}")

def train_gossip(mgr):
    nodos = mgr.nodos_online()
    if not nodos: console.print("[red]no hay nodos online[/red]"); return
    console.print(f"[bold]Config B (gossip)[/bold] con {len(nodos)} nodos: {nodos}")
    if not os.path.exists("prueba.csv"):
        N = int(Prompt.ask("falta prueba.csv; N del cluster", default=str(len(nodos))))
        escribir_prueba(N)
    dfte = pd.read_csv("prueba.csv")
    Xte = dfte[[f"f{i}" for i in range(N_PESOS-1)]].values; yte = dfte["y"].values
    dur = int(Prompt.ask("duracion (segundos)", default="60"))
    tg = int(Prompt.ask("periodo de gossip por nodo (ms)", default="3000"))

    with mgr.lock: mgr.gossip = {}
    mgr.enviar_modo("gossip", peers=nodos, t_gossip=tg, report=2000)
    cn = abrir_csv("gossip_nodos.csv", "ts,t_rel,node,rmse_local,exch")
    cc = abrir_csv("gossip_consenso.csv", "ts,t_rel,rmse_prom,dispersion,n_nodos")
    console.print(f"gossip activo {dur}s (Ctrl+C para cortar antes)...")
    t0 = time.time()
    try:
        while time.time() - t0 < dur:
            time.sleep(2.0)
            trel = time.time() - t0
            with mgr.lock: snap = dict(mgr.gossip)
            if not snap: continue
            rmses, ws = [], []
            for nid, (w, mse, exch) in snap.items():
                rmse = float(np.sqrt(np.mean((Xte @ w[:-1] + w[-1] - yte) ** 2)))
                rmses.append(rmse); ws.append(w)
                cn.write(f"{ahora_iso()},{trel:.1f},{nid},{rmse:.5f},{exch}\n")
            ws = np.array(ws); wmean = ws.mean(axis=0)
            disp = float(np.mean([np.linalg.norm(wi - wmean) for wi in ws]))
            rprom = float(np.mean(rmses))
            cc.write(f"{ahora_iso()},{trel:.1f},{rprom:.5f},{disp:.5f},{len(snap)}\n")
            cn.flush(); cc.flush()
            console.print(f"  t={trel:5.1f}s  RMSE_prom={rprom:.4f}  dispersion={disp:.4f}  ({len(snap)} nodos)")
    except KeyboardInterrupt:
        console.print("[yellow]cortado por el usuario[/yellow]")
    mgr.enviar_modo("idle")
    cn.close(); cc.close()
    console.print("[green]gossip detenido[/green] -> gossip_nodos.csv, gossip_consenso.csv")

def cmd_train(mgr):
    cfg = Prompt.ask("Configuracion a correr", choices=["A","B"], default="A")
    if cfg == "A": train_fedavg(mgr)
    else:          train_gossip(mgr)

def cmd_web(mgr):
    import federer_web
    url = federer_web.serve_background(mgr)
    console.print(f"[green]panel web activo en[/green] {url}  "
                  f"[dim](se abre en el navegador; sigue usando el menu si quieres)[/dim]")

# ========================== Menu =============================
MENU = """[bold]comandos[/bold]
 1) nodes      ver nodos del cluster (en vivo)
 2) discover   descubrir nodos ahora
 3) describe   detalle de un nodo
 4) config     enviar hiperparametros (lr/beta/epocas)
 5) provision  grabar un ESP32 nuevo (USB, primera vez)
 6) ota        actualizar firmware por red (sin cable)
 7) train      correr experimento (A=FedAvg / B=gossip)
 8) metrics    revisar metricas guardadas
 9) reboot     reiniciar / resetear un nodo
10) web        abrir panel web (navegador)
 0) quit       salir
"""

def main():
    console.print(RAQUETA)
    mgr = Manager()
    try: mgr.start()
    except Exception as e: sys.exit(f"No se pudo conectar al broker {BROKER}:{PUERTO} ({e})")
    acc = {
        "1":cmd_watch,"nodes":cmd_watch,
        "2":lambda m:(m.descubrir(),console.print("[green]discover enviado[/green]")),
        "discover":lambda m:(m.descubrir(),console.print("[green]discover enviado[/green]")),
        "3":cmd_describe,"describe":cmd_describe,
        "4":cmd_config,"config":cmd_config,
        "5":cmd_provision,"provision":cmd_provision,
        "6":cmd_ota,"ota":cmd_ota,
        "7":cmd_train,"train":cmd_train,
        "8":cmd_metrics,"metrics":cmd_metrics,
        "9":cmd_reboot,"reboot":cmd_reboot,
        "10":cmd_web,"web":cmd_web,
    }
    while True:
        console.print(Panel(MENU, title="[yellow]Federer[/yellow]", expand=False))
        op = Prompt.ask("federer>").strip().lower()
        if op in ("0","quit","q","exit"): break
        fn = acc.get(op)
        if fn:
            try: fn(mgr)
            except Exception as e: console.print(f"[red]error: {e}[/red]")
        else: console.print("[dim]opcion no valida[/dim]")
    mgr.client.loop_stop(); console.print("hasta luego.")

if __name__ == "__main__":
    if "--web" in sys.argv:
        import federer_web
        port = 8770
        if "--port" in sys.argv:
            port = int(sys.argv[sys.argv.index("--port") + 1])
        federer_web.serve(port=port, open_browser="--no-browser" not in sys.argv)
    else:
        main()
