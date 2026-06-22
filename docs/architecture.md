# Arquitectura

Federer separa claramente el **plano de control** (administración del cluster) del
**plano de datos** (entrenamiento), ambos sobre MQTT. El plano de datos cambia según el
[modo de entrenamiento](modos.md) activo: **FedAvg** (con maestro) o **gossip** (peer-to-peer).

![Arquitectura de Federer](assets/architecture.png)

```mermaid
flowchart TB
    subgraph HOST["Host — Raspberry Pi / Jetson / laptop"]
        FED["federer.py<br/>(plano de control + FedAvg)"]
        BRK["Mosquitto<br/>broker MQTT :1883"]
        FED <-->|MQTT| BRK
    end

    BRK <-->|Wi-Fi| N0
    BRK <-->|Wi-Fi| N1
    BRK <-->|Wi-Fi| N2

    subgraph NODOS["Nodos ESP32"]
        N0["ESP32 #0<br/>datos_nodo.h #0"]
        N1["ESP32 #1<br/>datos_nodo.h #1"]
        N2["ESP32 #N<br/>datos_nodo.h #N"]
    end
```

## Componentes

| Componente | Rol |
|---|---|
| **`federer.py`** | CLI interactivo + cliente MQTT + orquestador FedAvg/gossip + generador de particiones. |
| **Broker MQTT** | Bus de mensajes entre el host y los nodos (Mosquitto). |
| **Firmware ESP32** | Agente de cluster + ArduinoOTA + entrenamiento local (FedAvg **y** gossip). |
| **`datos_nodo.h`** | Partición de datos embebida, única por nodo (la genera Federer). |
| **CSV de métricas** | Registro persistente de convergencia, métricas por nodo y telemetría. |

## Los dos planos

### Plano de control

Gestiona el ciclo de vida del cluster: descubrimiento, configuración y comandos.

| Tópico | Dirección | Propósito |
|---|---|---|
| `cluster/announce` | nodo → Federer | Heartbeat con identidad, telemetría y modo activo. |
| `cluster/discover` | Federer → nodos | Solicita que todos se anuncien. |
| `cluster/config` | Federer → nodos | Cambia `lr`, `beta`, `epocas`. |
| `cluster/cmd` | Federer → nodos | `reboot` / `reset`. |
| `cluster/mode` | Federer → nodos | Selecciona el modo: `fedavg` / `gossip` / `idle`. |

### Plano de datos

Cambia según el modo de entrenamiento.

| Tópico | Modo | Dirección | Propósito |
|---|---|---|---|
| `fedavg/global` | A | Federer → nodos | Difunde el modelo global de la ronda. |
| `fedavg/update` | A | nodo → Federer | Devuelve pesos locales + métricas. |
| `gossip/inbox/<id>` | B | nodo → nodo | Envía pesos a un vecino aleatorio. |
| `gossip/report` | B | nodo → Federer | Reporta estado (pesos, MSE, intercambios). |

Detalle completo de cargas útiles en [Protocolo MQTT](mqtt.md).

### Los dos modos

```mermaid
flowchart TB
    subgraph A["🟢 Config A — FedAvg (con maestro)"]
        M["Federer"] -->|fedavg/global| nA["nodos"]
        nA -->|fedavg/update| M
    end
    subgraph B["🔵 Config B — Gossip (sin maestro)"]
        b1["nodo"] <-->|gossip/inbox| b2["nodo"]
        b2 <-->|gossip/inbox| b3["nodo"]
        b1 & b2 & b3 -. gossip/report .-> F0["Federer (observa)"]
    end
```

Comparativa completa en [Modos de entrenamiento](modos.md).

## Flujo de datos del dataset

El host es el único que ve el dataset completo. Lo divide así:

```mermaid
flowchart LR
    DS["Crop_recommendation.csv"] --> SPLIT["train_test_split<br/>+ StandardScaler"]
    SPLIT -->|80% train| PART["np.array_split en N partes"]
    SPLIT -->|20% test| TEST["prueba.csv<br/>(evaluación global)"]
    PART -->|parte 0| H0["datos_nodo.h #0"]
    PART -->|parte 1| H1["datos_nodo.h #1"]
    PART -->|parte N| HN["datos_nodo.h #N"]
```

- Cada nodo recibe **solo su porción** ya normalizada y embebida en el firmware.
- El conjunto de prueba (`prueba.csv`) se queda en el host para medir el RMSE global por ronda.

## Tolerancia y heartbeats

- Cada nodo emite un `announce` cada **5 s**.
- Federer considera un nodo **online** si lo vio en los últimos **15 s** (`HEARTBEAT_TIMEOUT`).
- En `train`, cada ronda espera respuestas hasta `TIMEOUT_RONDA` (30 s) y agrega lo que llegó.
