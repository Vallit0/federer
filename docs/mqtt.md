# Protocolo MQTT

Toda la comunicación entre Federer y los nodos viaja por MQTT (QoS 1). Hay dos planos:
**control** y **datos**.

## Resumen de tópicos

| Tópico | Dirección | Carga útil |
|---|---|---|
| `cluster/announce` | nodo → Federer | identidad + telemetría + `mode` |
| `cluster/discover` | Federer → nodos | ping (vacío `{}`) |
| `cluster/config` | Federer → nodos | `{lr, beta, epocas}` |
| `cluster/cmd` | Federer → nodos | `{cmd, node}` |
| `cluster/mode` | Federer → nodos | `{mode, peers[], t_gossip, report}` |
| `fedavg/global` | Federer → nodos | `{round, w[], stop}` (Config A) |
| `fedavg/update` | nodo → Federer | pesos + métricas (Config A) |
| `gossip/inbox/<id>` | nodo → nodo | `{from, w[]}` (Config B) |
| `gossip/report` | nodo → Federer | pesos + métricas de gossip (Config B) |

## Plano de control

### `cluster/announce` (heartbeat)

Cada nodo lo emite al conectarse, al reconfigurarse y cada 5 s.

```json
{
  "node": 0,
  "mac": "AA:BB:CC:DD:EE:FF",
  "ip": "192.168.1.42",
  "n": 110,
  "heap": 210480,
  "rssi": -58,
  "fw": "3.0-AB",
  "lr": 0.01,
  "beta": 0.9,
  "epocas": 5,
  "mode": 1
}
```

!!! note "Campo `mode`"
    `0` = idle, `1` = fedavg, `2` = gossip. Refleja el modo de entrenamiento activo en el nodo.

### `cluster/discover`

Carga útil vacía (`{}`). Provoca un `announce` inmediato de todos los nodos.

### `cluster/config`

Solo incluye los campos que cambian:

```json
{ "lr": 0.02, "beta": 0.95, "epocas": 8 }
```

### `cluster/cmd`

```json
{ "cmd": "reboot", "node": 1 }
```

- `cmd`: `"reboot"` (reinicia) o `"reset"` (pesos a cero).
- `node`: `NODE_ID` destino, o `-1` para todos.

### `cluster/mode`

Selecciona el [modo de entrenamiento](modos.md) de todos los nodos:

```json
{ "mode": "gossip", "peers": [0, 1, 2, 3], "t_gossip": 3000, "report": 2000 }
```

| Campo | Significado |
|---|---|
| `mode` | `"fedavg"`, `"gossip"` o `"idle"`. |
| `peers` | (gossip) lista de vecinos candidatos para el intercambio. |
| `t_gossip` | (gossip) periodo en ms con que cada nodo contacta a un vecino. |
| `report` | (gossip) periodo en ms con que cada nodo reporta su estado. |

## Plano de datos A (FedAvg)

### `fedavg/global`

El servidor difunde el modelo de la ronda:

```json
{ "round": 3, "w": [0.12, -0.04, 0.88, 0.21, -0.33, 0.05, 1.74], "stop": false }
```

Cuando el entrenamiento termina, se publica con `"stop": true`.

### `fedavg/update`

Cada nodo responde con sus pesos locales y **métricas ampliadas**:

```json
{
  "node": 0,
  "round": 3,
  "n": 110,
  "w": [0.13, -0.03, 0.90, 0.20, -0.31, 0.06, 1.71],
  "mse": 18.42,
  "rmse": 4.29,
  "train_ms": 37,
  "heap": 209120,
  "min_heap": 198440,
  "rssi": -59
}
```

| Campo | Significado |
|---|---|
| `node` | ID del nodo. |
| `round` | Ronda a la que corresponde el update. |
| `n` | Muestras locales (peso en la agregación). |
| `w` | Pesos del modelo tras entrenar. |
| `mse` / `rmse` | Error sobre los datos locales. |
| `train_ms` | Tiempo de entrenamiento en milisegundos. |
| `heap` / `min_heap` | Memoria libre actual / mínima histórica. |
| `rssi` | Intensidad de la señal Wi-Fi (dBm). |

## Plano de datos B (Gossip)

### `gossip/inbox/<id>`

Cada nodo se suscribe a su propio buzón `gossip/inbox/<NODE_ID>`. Un vecino le envía sus pesos:

```json
{ "from": 2, "w": [0.13, -0.03, 0.90, 0.20, -0.31, 0.06, 1.71] }
```

Al recibirlo, el nodo fusiona `w_local = (w_local + w_recibido) / 2` e incrementa su contador de
intercambios `exch`.

### `gossip/report`

Cada nodo reporta su estado a Federer (por defecto cada 2 s):

```json
{
  "node": 0,
  "w": [0.13, -0.03, 0.90, 0.20, -0.31, 0.06, 1.71],
  "mse": 16.04,
  "exch": 37,
  "heap": 208992,
  "rssi": -60
}
```

| Campo | Significado |
|---|---|
| `node` | ID del nodo. |
| `w` | Pesos actuales del modelo local. |
| `mse` | Error sobre los datos locales. |
| `exch` | Nº de fusiones (gossip) realizadas desde que empezó el modo. |
| `heap` / `rssi` | Memoria libre y señal Wi-Fi. |

## Inspeccionar el tráfico

Con las herramientas de Mosquitto puedes espiar todo el bus:

```bash
mosquitto_sub -h localhost -t 'cluster/#' -t 'fedavg/#' -t 'gossip/#' -v
```
