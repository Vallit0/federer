# CLI de Federer

Al ejecutar `python federer.py` aparece un menú interactivo. Puedes elegir cada acción por su
**número** o por su **nombre**.

```text
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
```

## Comandos

### `nodes` (1)

Muestra una **tabla en vivo** (refrescada 2×/s) con todos los nodos: estado online/perdido, IP,
MAC, número de muestras, heap libre, RSSI, última ronda, último MSE y hace cuánto se vio.
`Ctrl+C` vuelve al menú.

### `discover` (2)

Publica un ping en `cluster/discover`; todos los nodos responden con un `announce` inmediato.
Útil para refrescar el registro sin esperar el siguiente heartbeat.

### `describe` (3)

Pide un `NODE_ID` y muestra el registro completo de ese nodo en formato JSON.

### `config` (4)

Envía hiperparámetros al cluster. Deja un campo vacío para no modificarlo.

```text
lr (enter=sin cambio): 0.02
beta: 0.95
epocas: 8
```

Se publican en `cluster/config` y cada nodo los aplica y reconfirma con un `announce`.

### `provision` (5)

Graba un **ESP32 nuevo por USB** (primera vez). Genera su `datos_nodo.h`, crea `prueba.csv` y
compila/sube con PlatformIO (`env:esp32dev`). Ver [Provisionar nodos](provisioning.md).

### `ota` (6)

Actualiza el firmware **por red** de uno o todos los nodos online, usando su IP y la clave
`OTA_PASS` (`env:esp32ota`). No requiere cable.

### `train` (7)

Lanza un experimento. Primero pregunta la **configuración**:

```text
Configuracion a correr [A/B] (A):
```

=== "A — FedAvg (rondas)"

    Ejecuta el experimento **FedAvg** ronda por ronda:

    - envía `mode=fedavg`, difunde el modelo global, espera los updates, agrega los pesos,
    - calcula el RMSE global contra `prueba.csv`,
    - registra cada ronda en `convergencia_fedavg.csv`,
    - se detiene al converger o al llegar a `MAX_RONDAS`.

    ```text
      ronda  0  RMSE_global=42.1031  |dw|=12.4410  (4/4)
      ronda  1  RMSE_global=31.7720  |dw|=6.9920   (4/4)
      ...
      convergio
    ```

=== "B — Gossip (por tiempo)"

    Ejecuta el experimento de **gossip learning** durante un tiempo dado:

    - pregunta la `duracion` (segundos) y el `t_gossip` (ms),
    - envía `mode=gossip` con la lista de `peers`,
    - cada ~2 s registra RMSE promedio y dispersión (consenso) en `gossip_consenso.csv`
      y el estado por nodo en `gossip_nodos.csv`,
    - al terminar envía `mode=idle`.

    ```text
    Configuracion a correr [A/B] (A): B
    duracion (segundos) (60): 120
    periodo de gossip por nodo (ms) (3000): 2500
      t=  2.0s  RMSE_prom=40.81  dispersion=7.32  (4 nodos)
      t=  4.0s  RMSE_prom=33.10  dispersion=4.05  (4 nodos)
      ...
    ```

Más detalle en [Modos de entrenamiento](modos.md), [FedAvg](fedavg.md) y [Gossip](gossip.md).

### `metrics` (8)

Lista los CSV generados e imprime las últimas filas de `metricas_fedavg.csv`. Ver
[Métricas](metrics.md).

### `reboot` (9)

Envía `reboot` (reinicio) o `reset` (pone los pesos a cero) a un `NODE_ID` o a todos (`-1`).

### `web` (10)

Abre el [panel web](web-ui.md) en el navegador, reutilizando el `Manager` actual, y vuelve al
menú. También puedes lanzarlo en modo dedicado con `python federer.py --web`.

### `quit` (0)

Cierra la conexión MQTT y sale.

## Configuración global

Las constantes al inicio de `federer.py` controlan el comportamiento:

```python
BROKER, PUERTO = "localhost", 1883      # broker MQTT
FIRMWARE_DIR = "./firmware_esp32"        # proyecto PlatformIO
DATASET_CSV  = None                      # CSV local, o None para Kaggle
FEATURES = ["N","P","temperature","humidity","ph","rainfall"]
TARGET, SEED, TEST_SIZE = "K", 42, 0.20
HEARTBEAT_TIMEOUT = 15
MAX_RONDAS, TIMEOUT_RONDA, EPS_CONVERGENCIA = 30, 30.0, 1e-3
```
