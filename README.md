# config-ricevi-campo — el sistema que va montado en la cosechadora

Sistema de captura de dataset e inferencia in situ de RiceVi, para funcionamiento
real en campo con el hardware definitivo:

- **1 × Raspberry Pi 5 (8 GB)** como central: recibe, verifica, persiste, infiere y sirve el HMI.
- **4 × ESP32-S3-CAM** con OV3660 (`CAM01`–`CAM04`).
- **2 × ESP32-S3** con sensor Hall (`NH01` molinete, `NH02` rueda).
- **2 × ESP32-S3** con ultrasónico A02YYUW (`NU01` izquierdo, `NU02` derecho).
- **1 × punto de acceso Wi-Fi 2,4 GHz** dedicado.

> **Este proyecto es independiente de `prubea-conex/`.** Aquel es el banco de
> simulación, con hardware sustituto y sensores sintéticos, y se conserva aparte
> para ensayar cambios sin tocar el sistema de campo. Lo que se aprendió allí está
> incorporado aquí; lo que era un sustituto de banco, no.

## Las dos fases

El sistema tiene un único código y dos modos de operación:

| Fase | Qué hace | Cómo se activa |
|---|---|---|
| **1 · Dataset** | Captura, verifica y almacena. **No infiere.** | `RICEVI_MODELO=ninguno` (valor por defecto) |
| **2 · Inferencia** | Lo mismo, y además ejecuta los modelos y muestra diagnóstico | `RICEVI_MODELO=ncnn` con los pesos en `modelos/pesos/` |

**La fase 1 es la que se ejecuta primero y durante toda la campaña de captura.**
No hace falta tener modelos para salir a campo: hacen falta datos para poder
entrenarlos.

## La regla que no se negocia

> **Cuando no hay modelo, el sistema no muestra un número.** Muestra `sin modelo`.
> Nunca un porcentaje calculado con un sustituto.

Un modelo que no existe pero devuelve `12,86 %` es peor que no tener diagnóstico:
no falla, y el número acaba en la tesis. Por eso `modelos/sin_modelo.py` devuelve
`None` y el HMI lo distingue de un cero.

## Estructura

```
config-ricevi-campo/
├── config/          censo de nodos, calibración física y configuración de red
├── central/         el servidor que corre en la Raspberry Pi 5
├── modelos/         interfaz de modelo, el nulo y el de producción
├── nodos/           firmware de los ocho ESP32-S3
├── herramientas/    instalación, provisión, verificación, respaldo y exportación
└── docs/            el manual de campo
```

## Puesta en marcha, en orden

Cada paso deja verificado lo que el siguiente da por hecho. **No saltarse ninguno.**

**1 · Completar el censo con las MAC reales**

```bash
python config/censo.py
```

Tiene que terminar en `Censo completo y coherente.` Mientras avise de MAC que
faltan, no se puede configurar el punto de acceso.

**2 · Configurar el punto de acceso** siguiendo `config/red/router.md`.

**3 · Generar los tokens de los nodos**

```bash
python herramientas/generar_tokens.py
```

**4 · Instalar la central en la Pi**

```bash
./herramientas/copiar_a_pi.ps1
ssh ricevi-rasp@ricevi-rasp-01.local "~/config-ricevi-campo/herramientas/instalar_pi.sh"
```

**5 · Provisionar cada nodo** (identidad y token en NVS, uno por uno)

```bash
python herramientas/provisionar_nodo.py --node-id CAM01 --puerto COM7
```

**6 · Verificar el montaje completo antes de arrancar el motor**

```bash
python herramientas/verificar_campo.py
```

**7 · Al terminar la jornada, respaldar y verificar**

```bash
./herramientas/respaldo_jornada.sh /media/respaldo
```

## Lo que hay que medir con un metro antes de publicar nada

Cuatro constantes viven en `config/calibracion.json` con valor provisional. El
sistema funciona y **captura dataset válido** sin ellas, porque guarda siempre la
magnitud cruda. Pero hasta que estén medidas y anotadas, `reel_rpm`,
`wheel_speed`, `header_height` y `reel_index` **no se pueden publicar**:

| Constante | Qué es | Cómo se mide |
|---|---|---|
| `circunferencia_rueda_m` | Circunferencia efectiva de la rueda instrumentada | Marcar el neumático, avanzar diez vueltas **con carga**, medir y dividir |
| `radio_molinete_m` | Radio efectivo del molinete hasta la punta de la púa | Metro, con la máquina parada |
| `offset_b_mm` de `US01` | Distancia de la cara del sensor al plano de la cuchilla | Metro, con el cabezal en el suelo |
| `offset_b_mm` de `US02` | Ídem, lado derecho | Ídem |

`config/censo.py` y el acta de cada sesión avisan mientras sigan sin medir.

## Convenciones

1. **La captura tiene prioridad sobre el diagnóstico.** La central responde `201`
   cuando el archivo está en disco, sin esperar a la inferencia. Cuando algo se
   satura se pierde diagnóstico, **nunca dataset**.
2. **Los JPEG son los octetos recibidos, byte a byte.** Nunca se recomprimen.
   Cualquier versión anotada va a `datos/derivados/`.
3. **La identidad de un nodo es su `node_id`, no su IP.**
4. **Cuando no hay medida, el valor es nulo.** Nunca cero, nunca el último valor
   conocido.
5. **Si un campo no está en `contratos.py`, no existe.** Nada de diccionarios
   sueltos «por ahora».
6. **Nada se da por instalado hasta que un programa lo demuestra.**
