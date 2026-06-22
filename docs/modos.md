# Modos de entrenamiento

Federer corre el **mismo firmware** (`FW_VER = 3.0-AB`) en todos los nodos, pero con **dos modos
de aprendizaje** que se conmutan en caliente publicando `cluster/mode`:

| Modo | `mode` | Descripción |
|---|---|---|
| 🟢 **Config A** | `fedavg` | Aprendizaje federado coordinado por un maestro. |
| 🔵 **Config B** | `gossip` | Gossip learning descentralizado, sin maestro. |
| ⚪ Inactivo | `idle` | El nodo no entrena (estado de reposo). |

No hace falta regrabar para cambiar de modo: Federer lo decide al lanzar el experimento
(comando `train` → elige `A` o `B`).

## Comparativa

| | 🟢 **FedAvg (A)** | 🔵 **Gossip (B)** |
|---|---|---|
| **Topología** | Maestro ↔ nodos (estrella) | Nodos ↔ nodos (malla) |
| **Coordinación** | Federer dirige cada ronda | Autónoma, sin maestro |
| **Entrenamiento** | Reactivo: al recibir el modelo global | Continuo: una época cada ~150 ms |
| **Intercambio** | Nodo → maestro (`fedavg/update`) | Nodo → vecino aleatorio (`gossip/inbox/<id>`) |
| **Agregación** | $w = \dfrac{\sum_k n_k w_k}{\sum_k n_k}$ (en el host) | $w \leftarrow \dfrac{w_{local} + w_{vecino}}{2}$ (en cada nodo) |
| **Criterio de fin** | Converge por rondas (`‖Δw‖ < ε`) | Por tiempo; converge al consenso |
| **Punto único de fallo** | Sí (el maestro) | No |
| **Reproducibilidad** | Alta (rondas deterministas) | Menor (orden de mensajes aleatorio) |
| **Métricas** | `convergencia_fedavg.csv`, `metricas_fedavg.csv` | `gossip_consenso.csv`, `gossip_nodos.csv` |

## ¿Cuándo usar cada uno?

!!! tip "Usa **FedAvg (A)**"
    - Cuando quieres **experimentos reproducibles** y comparables ronda a ronda.
    - Cuando tienes un coordinador fiable (la Raspberry Pi / Jetson siempre disponible).
    - Para medir convergencia clásica de aprendizaje federado.

!!! tip "Usa **Gossip (B)**"
    - Cuando no quieres **punto único de fallo** ni un maestro central.
    - Para estudiar **consenso** y robustez en redes peer-to-peer.
    - Cuando los nodos entran y salen y prefieres un protocolo más tolerante.

## Cómo se selecciona

```text
federer> train
Configuracion a correr [A/B] (A): B
```

- **A** ejecuta `train_fedavg`: envía `mode=fedavg` y corre rondas (ver [FedAvg](fedavg.md)).
- **B** ejecuta `train_gossip`: envía `mode=gossip` con la lista de `peers`, deja correr el
  gossip durante el tiempo indicado y al final envía `mode=idle` (ver [Gossip](gossip.md)).

El modo activo de cada nodo aparece en su `announce` (campo `mode`) y, por tanto, en el detalle
del comando `describe`.
