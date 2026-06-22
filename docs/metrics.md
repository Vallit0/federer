# Métricas

Federer registra cada experimento en archivos CSV en el directorio de trabajo, legibles con
`pandas` o Excel. El comando `metrics` (opción `8`) lista y previsualiza los de FedAvg.

| Archivo | Modo | Contenido |
|---|---|---|
| `convergencia_fedavg.csv` | A | Convergencia global por ronda. |
| `metricas_fedavg.csv` | A | Métricas por nodo y ronda. |
| `gossip_consenso.csv` | B | Consenso global del cluster en el tiempo. |
| `gossip_nodos.csv` | B | Estado por nodo durante el gossip. |
| `telemetria_cluster.csv` | A/B | Telemetría de cada `announce`. |

## Config A — FedAvg

### `convergencia_fedavg.csv`

Una fila por ronda de entrenamiento — ideal para graficar la curva de convergencia.

| Columna | Significado |
|---|---|
| `ronda` | Número de ronda. |
| `rmse_global` | RMSE del modelo global sobre `prueba.csv`. |
| `dw` | Norma del cambio de pesos `‖Δw‖` respecto a la ronda anterior. |
| `n_nodos` | Nodos que respondieron en esa ronda. |

### `metricas_fedavg.csv`

Una fila por **nodo y ronda** — para comparar el rendimiento entre placas.

| Columna | Significado |
|---|---|
| `ts` | Marca de tiempo ISO. |
| `ronda` | Ronda. |
| `node` | ID del nodo. |
| `n` | Muestras locales. |
| `mse` / `rmse` | Error local. |
| `train_ms` | Tiempo de entrenamiento (ms). |
| `heap` / `min_heap` | Memoria libre actual / mínima. |
| `rssi` | Señal Wi-Fi (dBm). |

## Config B — Gossip

### `gossip_consenso.csv`

Una fila cada ~2 s — mide el **consenso global** del cluster a lo largo del experimento.

| Columna | Significado |
|---|---|
| `ts` | Marca de tiempo ISO. |
| `t_rel` | Segundos desde el inicio del experimento. |
| `rmse_prom` | RMSE promedio de todos los nodos sobre `prueba.csv`. |
| `dispersion` | Distancia media de cada modelo al modelo promedio (→ 0 = consenso). |
| `n_nodos` | Nodos que reportaron en esa instantánea. |

### `gossip_nodos.csv`

Una fila por **nodo e instantánea** — estado individual durante el gossip.

| Columna | Significado |
|---|---|
| `ts` | Marca de tiempo ISO. |
| `t_rel` | Segundos desde el inicio. |
| `node` | ID del nodo. |
| `rmse_local` | RMSE de ese nodo sobre `prueba.csv`. |
| `exch` | Nº de fusiones (gossip) acumuladas por el nodo. |

## Común

### `telemetria_cluster.csv`

Una fila por cada `announce` recibido — historial de salud del cluster.

| Columna | Significado |
|---|---|
| `ts` | Marca de tiempo ISO. |
| `node` | ID del nodo. |
| `ip` / `mac` | Dirección de red. |
| `heap` / `rssi` | Memoria y señal. |
| `fw` | Versión de firmware. |
| `lr` / `beta` / `epocas` | Hiperparámetros activos en el nodo. |

## Graficar la convergencia

```python
import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv("convergencia_fedavg.csv")
df.plot(x="ronda", y="rmse_global", marker="o", title="Convergencia FedAvg")
plt.ylabel("RMSE global")
plt.tight_layout()
plt.savefig("convergencia.png", dpi=150)
```

## Comparar nodos

```python
import pandas as pd

m = pd.read_csv("metricas_fedavg.csv")
# RMSE medio y tiempo de entrenamiento por nodo
print(m.groupby("node")[["rmse", "train_ms"]].mean())
```

## Graficar el consenso (gossip)

```python
import pandas as pd
import matplotlib.pyplot as plt

c = pd.read_csv("gossip_consenso.csv")
ax = c.plot(x="t_rel", y="rmse_prom", marker="o", title="Consenso (gossip)")
c.plot(x="t_rel", y="dispersion", marker="s", ax=ax, secondary_y=True)
plt.tight_layout()
plt.savefig("consenso.png", dpi=150)
```

La `dispersion` debería tender a 0 a medida que los nodos alcanzan el consenso.

!!! tip "Los archivos se acumulan"
    Federer **añade** filas (modo `append`). Para empezar un experimento limpio, borra o
    renombra los CSV antes de entrenar.
