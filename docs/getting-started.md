# Instalación y setup

Esta guía te lleva de cero a un cluster entrenando con FedAvg.

## Requisitos previos

=== "Host (donde corre Federer)"

    - **Python 3.9+**
    - Un **broker MQTT** ([Mosquitto](https://mosquitto.org/) recomendado)
    - [**PlatformIO Core**](https://platformio.org/) (`pio`) para grabar el firmware
    - Una red Wi-Fi compartida con los nodos

=== "Nodos"

    - Placas **ESP32** (probado con `esp32dev`)
    - Cable **USB** para la primera grabación (luego todo es OTA)

## 1. Clonar el repositorio

```bash
git clone https://github.com/Vallit0/federer.git
cd federer
```

## 2. Instalar dependencias de Python

!!! tip "Usa un entorno virtual"
    Mantiene tus dependencias aisladas del sistema.

=== "Linux / macOS"

    ```bash
    python -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    ```

=== "Windows (PowerShell)"

    ```powershell
    python -m venv .venv
    .venv\Scripts\Activate.ps1
    pip install -r requirements.txt
    ```

Esto instala `paho-mqtt`, `rich`, `numpy`, `pandas`, `scikit-learn`, `platformio` y
`kagglehub`.

## 3. Levantar el broker MQTT

Federer se conecta por defecto a `localhost:1883`.

=== "Linux (Debian/Ubuntu)"

    ```bash
    sudo apt install mosquitto mosquitto-clients
    sudo systemctl enable --now mosquitto
    ```

=== "macOS (Homebrew)"

    ```bash
    brew install mosquitto
    brew services start mosquitto
    ```

=== "Windows"

    Descarga el instalador desde [mosquitto.org/download](https://mosquitto.org/download/)
    e inicia el servicio Mosquitto.

!!! note "¿Broker en otra máquina?"
    Edita `BROKER` y `PUERTO` al inicio de `federer.py`. Asegúrate también de que el
    `BROKER_IP` del firmware apunte a esa misma IP.

## 4. Preparar el dataset (opcional)

Por defecto Federer descarga *Crop Recommendation* desde Kaggle con `kagglehub`. Si prefieres
usar un CSV local, edita en `federer.py`:

```python
DATASET_CSV = "ruta/a/Crop_recommendation.csv"   # en lugar de None
```

## 5. Configurar el firmware

Edita las credenciales en `firmware_esp32/src/main.cpp`:

```cpp
const char* WIFI_SSID = "TU_RED_WIFI";
const char* WIFI_PASS = "TU_PASSWORD";
const char* BROKER_IP = "192.168.1.100";   // IP del host donde corre el broker
const char* OTA_PASS  = "federer";          // clave para grabar por red
```

## 6. Lanzar Federer

```bash
python federer.py
```

Verás la raqueta ASCII y el menú interactivo. Si no conecta, revisa que el broker esté
arriba (ver [Solución de problemas](troubleshooting.md)).

!!! tip "¿Prefieres una interfaz visual?"
    Lanza el [**panel web**](web-ui.md) con `python federer.py --web` (o la opción `web` del
    menú) y administra todo el cluster desde el navegador.

## Siguientes pasos

<div class="grid cards" markdown>

- :material-chip: **[Provisionar nodos](provisioning.md)** — graba tu primer ESP32.
- :material-sitemap: **[Arquitectura](architecture.md)** — cómo encajan las piezas.
- :material-swap-horizontal: **[Modos de entrenamiento](modos.md)** — FedAvg vs gossip.
- :material-school: **[FedAvg](fedavg.md)** y **[Gossip](gossip.md)** — los dos algoritmos.

</div>
