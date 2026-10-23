# config-ricevi-campo — el sistema que va montado en la cosechadora

Sistema de captura de dataset e inferencia in situ de RiceVi, para funcionamiento
real en campo con el hardware definitivo:

- **1 × Raspberry Pi 5 (8 GB)** como central: recibe, verifica, persiste, infiere y sirve el HMI.
- **4 × GOOUUU ESP32-S3-CAM** (N16R8) con OV3660 (`CAM01`–`CAM04`); `CAM04` con LED de tolva pulsado.
- **1 × ESP32-C6 DevKitC** con sensor Hall HW-477 (`NH01`, molinete).
- **2 × ESP32-C6 DevKitC** con ultrasónico RCWL-1655 en modo Trig/Echo (`NU01` izquierdo, `NU02` derecho).
- **1 × receptor GPS USB VK-162** (u-blox 7) conectado a la Pi, con la antena en el
  techo de la cabina (`GPS01`): mide la velocidad de avance. La posición no se guarda.
- **1 × router Tenda N301** (2,4 GHz) como punto de acceso dedicado.

Siete ESP32 en total. Hasta octubre de 2026 había un octavo, `NH02`, con un Hall
en la rueda; se retiró porque el agua y el lodo no dejaban montarlo y porque la
rueda patina. El GPS mide la velocidad sobre el suelo sin ese error.

Cada nodo lleva 4 pilas AA Ni-MH y no lleva microSD: las imágenes van directo
al SSD de la Pi. La central y el router se alimentan de una batería LiFePO4 de
12 V. Nada se conecta a la cosechadora. Detalle en
`docs/01-arquitectura-hardware.md` (versión 1.3).

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
├── nodos/           firmware de los siete ESP32 (S3 en cámaras, C6 en sensores)
├── herramientas/    instalación, provisión, verificación, respaldo y exportación
└── docs/            estado del proyecto, diseño, configuración, manual y concurso
```

| Documento | Qué es |
|---|---|
| `docs/00_ESTADO_ACTUAL_PROYECTO.md` | **Fuente de verdad**: decisiones cerradas, pendientes y próximos pasos |
| `docs/01-arquitectura-hardware.md` | Diseño: hardware, alimentación, red, datos y procesamiento |
| `docs/02-configuracion-sistema.md` | Dónde vive cada ajuste y qué pasa si se cambia |
| `docs/03-manual-de-campo.md` | Lo que se hace, en orden, en una jornada |
| `docs/concurso/` | Postulación a NEIVA FEST Reto Innova 2026: resumen, cifras y fuentes |

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

**4 · Conectar el GPS a un USB de la Pi e instalar la central**

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
`header_height` y `reel_index` **no se pueden publicar**. La velocidad del GPS no
necesita constantes; se valida con un tramo medido (manual de campo, §7.2):

| Constante | Qué es | Cómo se mide |
|---|---|---|
| `pulsos_por_vuelta` de `HALL01` | Imanes en el eje del molinete | Contarlos y comprobar con una vuelta a mano |
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
