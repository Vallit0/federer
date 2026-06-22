# Preguntas frecuentes

??? question "¿Por qué se llama Federer?"
    Es un juego de palabras: **Fed**erated Learning + Roger **Federer**. Y como un buen plano de
    control, "saca" comandos al cluster. 🎾

??? question "¿Realmente es aprendizaje federado?"
    Sí. Cada ESP32 entrena con **sus propios datos**, que nunca salen de la placa; solo se
    transmiten los **pesos** del modelo. En **Config A** un maestro los promedia con **FedAvg**;
    en **Config B** los nodos los fusionan entre sí con **gossip**. Es el mismo principio que
    usan los despliegues federados a gran escala, en miniatura.

??? question "¿Cuál es la diferencia entre FedAvg y gossip?"
    **FedAvg (Config A)** es centralizado: un maestro coordina rondas y promedia los pesos de
    todos. **Gossip (Config B)** es descentralizado: no hay maestro, cada nodo entrena de
    continuo y fusiona sus pesos con un vecino aleatorio hasta alcanzar el consenso. Comparativa
    completa en [Modos de entrenamiento](modos.md).

??? question "¿Tengo que regrabar el firmware para cambiar de modo?"
    No. El mismo firmware (`3.0-AB`) implementa ambos modos. Federer los conmuta en caliente
    publicando `cluster/mode` cuando eliges `A` o `B` en el comando `train`.

??? question "¿Cuántos nodos soporta?"
    No hay un límite duro: depende de tu broker MQTT y de la red. El reparto de datos
    (`np.array_split`) y la agregación escalan con `N`. Con decenas de ESP32 funciona sin
    problema; el cuello de botella suele ser el Wi-Fi.

??? question "¿Puedo usar otro dataset o modelo?"
    El ejemplo es una regresión lineal sobre *Crop Recommendation*. Para otro caso, ajusta
    `FEATURES`/`TARGET` y la generación de `datos_nodo.h` en `federer.py`, y la función de
    entrenamiento en el firmware. La estructura de FedAvg se mantiene.

??? question "¿Necesito una Raspberry Pi?"
    No. Federer corre en cualquier host con Python y un broker MQTT: una laptop, una Jetson o
    una Raspberry Pi. Solo debe compartir la red Wi-Fi con los nodos.

??? question "¿Tengo que volver a conectar el USB cada vez?"
    No. Solo la **primera** grabación es por USB (`provision`). A partir de ahí actualizas por
    red con `ota`.

??? question "¿Es seguro?"
    Es un proyecto educativo. El broker y la OTA usan configuraciones básicas (clave OTA
    compartida, MQTT sin TLS por defecto). Para producción conviene añadir TLS y autenticación
    en el broker.

??? question "¿Dónde quedan los resultados?"
    En tres CSV en el directorio de trabajo: `convergencia_fedavg.csv`, `metricas_fedavg.csv` y
    `telemetria_cluster.csv`. Ver [Métricas](metrics.md).

??? question "¿Puedo cambiar los hiperparámetros sin regrabar?"
    Sí. El comando `config` envía `lr`, `beta` y `epocas` por MQTT y los nodos los aplican al
    vuelo, sin regrabar el firmware.
