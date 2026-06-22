# Panel web

Además de la CLI, Federer incluye un **panel web ligero** (estilo Docker Desktop / Apache
Airflow) que corre en el navegador para **ver y configurar todo visualmente**: estado de los
nodos en vivo, lanzar entrenamientos, cambiar hiperparámetros y modo, y grabar firmware.

!!! info "Ligero y sin dependencias extra"
    El backend usa **solo la librería estándar de Python** (`http.server`) y reutiliza el mismo
    `Manager` MQTT de la CLI. El frontend es **HTML/CSS/JS vanilla** servido desde `webui/`
    (sin build, sin CDN). Funciona offline en la red local.

## Lanzarlo

El panel **no arranca solo**: hay que pedirlo explícitamente.

=== "Modo dedicado (CLI)"

    ```bash
    python federer.py --web
    ```

    Opciones:

    | Flag | Efecto |
    |---|---|
    | `--port <N>` | Sirve en otro puerto (por defecto `8770`). |
    | `--no-browser` | No abre el navegador automáticamente. |

    Crea su propio `Manager`, conecta al broker y sirve el panel (bloqueante). Abre
    automáticamente `http://localhost:8770`.

=== "Desde el menú interactivo"

    ```text
    federer> web
    ```

    Levanta el panel **en segundo plano** reutilizando el `Manager` que ya está corriendo, y
    te devuelve al menú. Así puedes usar la CLI y el navegador a la vez.

## Secciones

<div class="grid cards" markdown>

- :material-server-network: **Cluster** — tarjetas de estado (nodos online, modo activo, trabajo
  en curso) y tabla de nodos en vivo, con botón de reinicio por nodo y *descubrir*.
- :material-brain: **Entrenar** — formularios para **FedAvg (A)** y **Gossip (B)**, botón de
  detener, gráficas de convergencia y consenso, y la salida del experimento en vivo.
- :material-cog: **Config** — envía hiperparámetros (`lr`, `beta`, `epocas`), conmuta el modo
  (`fedavg`/`gossip`/`idle`) y manda comandos (`reboot`/`reset`) a un nodo.
- :material-chip: **Firmware** — provisiona por USB y actualiza por OTA, con la salida de
  PlatformIO en directo.
- :material-console: **Consola** — registro completo de eventos del panel.

</div>

## API HTTP

El frontend habla con un API JSON mínimo (mismo origen). Útil si quieres automatizar:

| Método | Ruta | Cuerpo | Acción |
|---|---|---|---|
| `GET` | `/api/state` | — | Snapshot: nodos, trabajo, logs y series de gráficas. |
| `POST` | `/api/discover` | `{}` | Ping de descubrimiento. |
| `POST` | `/api/config` | `{lr, beta, epocas}` | Envía hiperparámetros. |
| `POST` | `/api/mode` | `{mode, t_gossip?, report?}` | Cambia el modo del cluster. |
| `POST` | `/api/cmd` | `{cmd, node}` | `reboot` / `reset` a un nodo (o `-1`). |
| `POST` | `/api/train` | `{config:"A"\|"B", ...}` | Lanza un experimento. |
| `POST` | `/api/train/stop` | `{}` | Solicita detener el experimento. |
| `POST` | `/api/provision` | `{node_id, N, port}` | Graba un ESP32 por USB. |
| `POST` | `/api/ota` | `{target, N}` | Actualiza por red. |

Ejemplo:

```bash
curl -X POST localhost:8770/api/train -H 'Content-Type: application/json' \
     -d '{"config":"B","dur":120,"t_gossip":2500}'
```

!!! warning "Un trabajo a la vez"
    El panel ejecuta un solo trabajo pesado a la vez (entrenamiento, provisión u OTA). Evita
    lanzar un `train` desde la CLI y otro desde el panel simultáneamente: ambos comparten el
    mismo `Manager` y se pisarían las rondas.

## Seguridad

El servidor escucha en `0.0.0.0` (accesible desde la LAN) y **no tiene autenticación**: está
pensado para una red local de laboratorio. No lo expongas directamente a Internet.
