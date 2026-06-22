# Solución de problemas

## Federer no arranca

!!! failure "`No se pudo conectar al broker localhost:1883`"
    El broker MQTT no está corriendo o está en otra dirección.

    - Verifica Mosquitto: `systemctl status mosquitto` (Linux) o el servicio en Windows.
    - Prueba manualmente: `mosquitto_sub -h localhost -t test`.
    - Si está en otra máquina, ajusta `BROKER`/`PUERTO` en `federer.py`.

!!! failure "`Falta paho-mqtt` / `Falta rich`"
    Faltan dependencias de Python. Ejecuta `pip install -r requirements.txt`.

## Los nodos no aparecen

- Ejecuta `discover` para forzar un anuncio.
- Confirma que el ESP32 y el host están en la **misma red Wi-Fi**.
- Revisa que `BROKER_IP` en el firmware sea la IP real del host (no `localhost`).
- Abre el monitor serie (`pio device monitor`) para ver los logs de conexión del nodo.
- Si tu broker exige autenticación o no escucha en todas las interfaces, ajusta su
  configuración (`listener 1883 0.0.0.0`, `allow_anonymous true` en pruebas).

## Falla la grabación

!!! failure "`PlatformIO no encontrado`"
    Instala PlatformIO Core: `pip install platformio`. Comprueba con `pio --version`.

!!! failure "`fallo la grabacion` por USB"
    - Revisa el cable y el puerto (`provision` permite indicarlo a mano).
    - En Linux puede faltar permiso al puerto serie: añade tu usuario al grupo `dialout`.
    - Cierra cualquier monitor serie que tenga ocupado el puerto.

!!! failure "Falla la OTA"
    - El nodo debe estar **online** y tener IP (verifícalo con `nodes`).
    - La clave `--auth` del entorno `esp32ota` debe coincidir con `OTA_PASS` del firmware.
    - Algunos firewalls bloquean el puerto OTA (`3232`); permite el tráfico en la LAN.

## El entrenamiento no converge o da `NaN`

- Baja la tasa de aprendizaje con `config` (p. ej. `lr = 0.005`).
- Reduce `epocas` por ronda.
- Asegúrate de que `prueba.csv` y las particiones se generaron con el **mismo `N`**.
- Usa `reboot` con acción `reset` para poner los pesos a cero y reintentar.

## El gossip no converge (dispersión alta)

- Aumenta la **duración** del experimento: el consenso tarda más que unas pocas rondas FedAvg.
- Reduce `t_gossip` para que los nodos se contacten más a menudo.
- Verifica que todos los nodos recibieron `mode=gossip` (campo `mode = 2` en `describe`).
- Asegúrate de que hay **al menos 2 nodos** online; con uno solo no hay con quién fusionar.
- Si la `dispersion` no baja, baja la tasa de aprendizaje (`config`) para evitar que cada nodo
  se aleje demasiado entre fusiones.

## Métricas vacías

- Los CSV se crean al recibir el primer `update`/`announce`. Si están vacíos, aún no ha habido
  tráfico: corre `train` o espera un heartbeat.
- Recuerda que Federer **añade** filas; revisa que estés mirando el archivo del experimento
  actual.
