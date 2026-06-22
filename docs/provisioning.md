# Provisionar nodos

Cada ESP32 necesita su **propia partición de datos** y el firmware del nodo. Federer
automatiza ambos pasos.

## Primera grabación (por USB)

1. Conecta un ESP32 al host por **USB**.
2. En el menú de Federer escribe `provision` (opción `5`).
3. Responde a las preguntas:

    | Pregunta | Significado |
    |---|---|
    | `NODE_ID a asignar` | Identificador único del nodo (`0, 1, 2, …`). |
    | `tamano del cluster (N)` | Número total de nodos entre los que se reparten los datos. |
    | `puerto USB` | Puerto serie; deja vacío para autodetección. |

4. Federer:
    - Genera `firmware_esp32/include/datos_nodo.h` con la **partición de datos** de ese nodo.
    - Crea `prueba.csv` (conjunto de prueba global reservado en el host).
    - Compila y graba el firmware con PlatformIO (`env:esp32dev`).

!!! info "¿Qué hay dentro de `datos_nodo.h`?"
    El `NODE_ID`, el número de muestras, las medias/desviaciones para normalizar y los
    arreglos `X_LOCAL` / `Y_LOCAL` con la porción de datos que entrena ese nodo.

Repite el proceso para cada placa, incrementando el `NODE_ID`.

## Verificar que el nodo está en línea

Tras grabar, el ESP32 se conecta al Wi-Fi y empieza a emitir *heartbeats*. Comprueba con:

```text
federer> nodes
```

Deberías ver el nodo en estado **online** con su IP, MAC, número de muestras, heap y RSSI.

## Actualizaciones posteriores (por red, OTA)

Una vez que un nodo está en línea, ya no necesitas el cable:

1. Escribe `ota` (opción `6`).
2. Elige el nodo a actualizar (`-1` = todos los online).
3. Indica el tamaño del cluster `N` para regenerar la partición.

Federer reescribe `datos_nodo.h` para cada nodo y graba por red usando su **IP** y la clave
`OTA_PASS` (`env:esp32ota`).

!!! warning "La clave OTA debe coincidir"
    El flag `--auth` del entorno `esp32ota` en `platformio.ini` debe ser igual al `OTA_PASS`
    del firmware. Por defecto ambos son `federer`.

## Reiniciar o resetear un nodo

```text
federer> reboot
```

- `reboot` — reinicia el ESP32.
- `reset` — pone a cero los pesos del modelo sin reiniciar.

Puedes dirigirlo a un `NODE_ID` concreto o a `-1` para todos.
