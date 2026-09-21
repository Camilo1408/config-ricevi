# Modelos

## Las dos fases

| Fase | `RICEVI_MODELO` | Qué ocurre |
|---|---|---|
| **Dataset** | `ninguno` *(por defecto)* | Se captura y no se infiere. El HMI muestra **«sin modelo»** |
| **Inferencia** | `ncnn` | Se ejecutan los modelos con los pesos de `pesos/` |

**La fase de dataset es la primera y dura toda la campaña de captura.** No hace
falta tener modelos para salir a campo: hacen falta datos para poder
entrenarlos.

## La regla que hace cumplir `base.py`

> `porcentaje` puede ser `None`, y **`None` no es cero**.

En el banco de pruebas había un sustituto que calculaba el «ratio de verde».
Como ejercicio de infraestructura fue útil. En campo es peligroso, y por una
razón concreta: **no falla**. Devuelve un número con la forma correcta, en el
rango correcto, que aparece junto a la etiqueta «material útil residual» y que
acaba en una tabla de la tesis. No se detecta mirando gráficas, porque se
comporta como un dato.

Por eso el motor por defecto es `sin_modelo.py`, y devuelve nulo.

## Qué pesos hacen falta

```
pesos/
  manifiesto.json
  acame.param       acame.bin         clasificación ordinal, 3 clases
  post_corte.param  post_corte.bin    segmentación semántica
  tolva.param       tolva.bin         segmentación semántica
```

**Sin `manifiesto.json` no se carga nada.** Un modelo sin versión no es
trazable, y un resultado que no se puede atribuir a una versión concreta no
sirve para comparar dos jornadas. El manifiesto también lleva el SHA-256 de cada
`.bin`: un archivo de pesos truncado por una copia interrumpida carga sin error
y produce basura.

## Por qué NCNN

Medido y publicado sobre Raspberry Pi 5, con YOLO11n a 640 × 640:

| Formato | Tiempo |
|---|---|
| **NCNN** | **93,9 ms** |
| ONNX | 181,8 ms |
| TensorFlow Lite | 324,2 ms |
| PyTorch | 524,8 ms |

Más de cinco veces entre ejecutar el mismo modelo en PyTorch y en NCNN. Es la
optimización más rentable de todo el sistema y no cuesta dinero.

## Segmentación semántica, no de instancias

Para obtener un **porcentaje de píxeles**, lo natural es segmentación
semántica. Un modelo de instancias tipo YOLO-seg produce objetos individuales
que luego habría que unir para no contar píxeles dos veces, y paga un coste de
cómputo por una información —cuántas panículas hay y dónde empieza cada una—
que el indicador no usa.

Si más adelante interesa contar panículas, entonces sí tendrá sentido el modelo
de instancias.

## El paso que no se puede saltar al desplegar

El modelo que se evalúa en el PC **no es** el que corre en la Pi: se ha
exportado a NCNN y posiblemente cuantizado a enteros.

| Paso | Qué puede salir mal |
|---|---|
| Exportar a NCNN | Una operación no soportada obliga a cambiar la arquitectura de la red |
| Cuantizar | La precisión puede caer de forma desigual: bien en promedio, mal en la clase minoritaria |
| Medir en la Pi | El modelo puede ser más lento de lo previsto y no caber en el presupuesto de CPU |

**Un candidato no se promueve por sus métricas en el PC de entrenamiento.** Se
promueve por sus métricas *después de exportar y cuantizar*, medidas sobre el
conjunto de prueba, y por su tiempo de inferencia medido en la Pi real. Las
métricas que van a la tesis tienen que ser las del modelo exportado, o declarar
ambas.

## Despliegue en sombra

Antes de promover un modelo, se ejecuta sobre los mismos frames que el vigente
sin mostrarse al operario, y se comparan las salidas durante al menos una
jornada. Es posible precisamente porque la inferencia es local.

Hay que contarlo en el presupuesto de CPU: durante la prueba en sombra el
consumo de inferencia se duplica, así que conviene hacerla con ritmos reducidos.

## Añadir un motor nuevo

Implementar el `Protocol` de `base.py` y registrarlo en `_crear_modelo()` de
`central/app/inferencia.py`. Tres métodos: `cargar()`, `tareas()`, `inferir()`.

Y precalentar en `cargar()`. **No es opcional**: la primera inferencia de
cualquier motor tarda varias veces más que las siguientes, y sin precalentar el
primer frame de cada jornada produce una medida de latencia que no representa
nada y contamina los percentiles p95 y p99.
