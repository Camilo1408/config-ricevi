# RiceVi en NEIVA FEST · Reto Innova 2026

Resumen de la postulación del **22 de octubre de 2026** a la Convocatoria Pública
No. 001 de 2026 *NEIVA FEST Reto Innova*, de la Fundación Es Entre Todos (Neiva,
Huila). Recoge lo que se presentó, con qué cifras y con qué fuentes, para que el
proyecto y lo prometido en el concurso no se separen.

> **Lo que no está aquí, a propósito.** Los anexos firmados y el pitch llevan
> números de cédula, teléfonos y firmas. Este repositorio es público, así que
> esos archivos se quedan fuera: viven en la carpeta local
> `Modalidad de Grado/Concurso/Diligenciados/`.

| Campo | Valor |
|---|---|
| Iniciativa | **RiceVi: diagnóstico con visión artificial del corte de la cosecha mecanizada de arroz** |
| Ámbito | Económico (agroindustria arrocera, con impacto social en la zona rural) |
| Representante | Ferley Medina Rojas, profesor de Ingeniería de Software de la Universidad Surcolombiana y asesor del proyecto de grado |
| Desarrolladores | Cesar Camilo Hoyos Diaz y Alvaro Julian Delgado Mena, estudiantes de noveno semestre de la USCO |
| Documentos entregados | Anexo 2 (documento técnico, 11 páginas), anexo 3 (autoría y propiedad intelectual), anexo 4 (datos e IA responsable), anexo 5 (integridad) y pitch de 10 diapositivas |

## La propuesta en pocas líneas

RiceVi es un sistema de monitoreo de cosecha que le muestra al operario, mientras
cosecha, cuánto grano está dejando en el campo. Sirve para cualquier grano que se
coseche con cabezal, molinete y tolva; el primer diseño es para el arroz. Cuatro
cámaras y tres sensores observan el cultivo antes del corte, el suelo después del
cabezal y la tolva, y un GPS mide la velocidad de avance. Tres modelos de visión
analizan las imágenes a bordo, en una Raspberry Pi 5 y sin Internet. El operario
ve, ajusta y comprueba; el sistema no toca los controles.

## Las cifras y de dónde salen

| Dato | Valor | Fuente |
|---|---|---|
| Pérdida promedio al cosechar arroz con cosechadora en Colombia | **7,17 %**: 1,44 cabezal · 1,56 trilla · 4,12 separación y limpieza (39 observaciones, Ambalema) | [1] |
| Pérdida total razonable con buen operario y máquina ajustada | 1,25–2,2 % | [2] |
| Huila 2025 | 30.620 ha, 236.475 t de paddy verde, **7,40 t/ha** (mayor rendimiento del país) | [3] |
| Huila, primer semestre de 2026 | 114.473 t, 7,32 t/ha | [4] |
| Precio del paddy verde, junio de 2026 | $1,34 millones por tonelada (junio de 2025: $1,43 M) | [6] |
| Velocidad de avance y pérdida | Relación lineal; la menor velocidad observada, 3,87 km/h, dio 0,67 % de pérdida | [7] |

El DANE publica por departamento, no por municipio. La seccional de Fedearroz en
Neiva atiende además Aipe, Alpujarra, Baraya, Íquira, Palermo, Tello, Villavieja y
Yaguará [5].

**Escenarios sobre la pérdida del cabezal** (cálculo propio con [1], [3], [4] y [6]).
RiceVi actúa directamente sobre el cabezal; el efecto indirecto sobre trilla y
limpieza se describe y se medirá, pero **no se suma**.

| Escala | Pérdida actual del cabezal, 1,44 % (techo recuperable) | Reducirla a la mitad, −0,72 puntos |
|---|---|---|
| Una hectárea | ≈ 107 kg · ≈ $142.800 | ≈ 53 kg · ≈ $71.400 |
| Lote de 10 ha | ≈ 1,07 t · ≈ $1,4 M | ≈ 530 kg · ≈ $714.000 |
| Huila, primer semestre de 2026 | ≈ 1.650 t · ≈ $2.200 M | ≈ 820 t · ≈ $1.100 M |
| Huila, año 2025 | ≈ 3.400 t · ≈ $4.560 M | ≈ 1.700 t · ≈ $2.280 M |

Con la mitad recuperada la pérdida total bajaría de 7,17 % a 6,45 %, y a 5,73 % en
el techo. El hardware cuesta del orden de **US$ 1.000–1.100 por cosechadora**
(≈ $4–4,5 M) y no tiene costos recurrentes: se paga en ≈ 56 ha cosechadas en el
escenario de la mitad, o ≈ 28 ha en el techo.

> **Ojo al citar.** Son escenarios calculados, no resultados medidos. Según ASABE
> [2], una pérdida de cabezal de ≈ 0,95–1,9 % ya es razonable, así que el 1,44 % de
> 1984 cae en ese rango; el gran exceso del estudio está en separación y limpieza.
> La tesis no afirma reducciones en kg/ha hasta medirlas (`00_ESTADO…` §1).

## Lo que se comprometió en público

| Compromiso | Dónde se cumple en el sistema |
|---|---|
| El GPS se usa solo para medir la velocidad; la ubicación de los lotes no se publica | La central descarta latitud y longitud (`central/app/gps.py`, decisión C35) |
| El sistema no se conecta a la máquina | Todo con batería propia (C26) |
| Sin modelo o sin medida no se muestra un número | «sin modelo» y regla del nulo (C16, C17) |
| El dataset se divide por jornada, nunca al azar | `grupo` = fecha de la jornada en `exportar_dataset.py` (C29) |
| La altura del cabezal se valida con cinta antes de publicarla | Manual de campo §7.1 (C28) |
| Ley 1581 de 2012: las cámaras apuntan al cultivo, al suelo y a la tolva | Imágenes con personas captadas por accidente se excluyen o anonimizan antes de etiquetar |
| Código abierto | Este repositorio |

## Cronograma comprometido

| Periodo | Hito |
|---|---|
| Hasta mediados de noviembre de 2026 | Montaje de los siete nodos y el GPS, con pruebas de banco |
| Mediados de noviembre a diciembre de 2026 | Captura del dataset en cosecha y validación de sensores en el lote |
| Noviembre de 2026 a enero de 2027 | Etiquetado y entrenamiento a medida que llegan los datos |
| Enero y febrero de 2027 | Primeras salidas con los modelos en la Raspberry Pi y medición de la pérdida en el lote |

## Uso orientador del incentivo

Primer puesto, $5.000.000: **40 %** hardware de campo (SSD, pilas, cajas IP65,
conectores, cámaras de reemplazo) · **25 %** salidas de campo y muestreo físico ·
**20 %** etiquetado del dataset · **15 %** cómputo (GPU en la nube y, si las
medidas lo justifican, un acelerador para la Pi). Con el segundo puesto ($3 M) se
priorizan hardware y salidas; con el tercero ($2 M), lo indispensable para
completar los siete nodos y la primera salida.

## Estado del prototipo declarado

Prototipo funcional en banco, fase 1 (dataset). La central corre en la Pi con su
batería de comprobaciones automáticas (el anexo dice 40; con el GPS hoy son 50),
el nodo Hall cuenta pulsos en protoboard, el firmware del ultrasónico ya es
Trig/Echo y el cableado pasa a placa perforada. Limitaciones declaradas: modelos
sin entrenar, autonomías y tiempos de inferencia estimados, **velocidad por GPS
por validar a baja velocidad**, tolva que solo ve la superficie, y el etiquetado
como mayor riesgo de calendario.

## Referencias

1. Chaparro, J. M., Devia, J. R. y Zea, J. A. (1984). Evaluación de pérdidas de grano en cosecha de arroz con combinada. *Ingeniería e Investigación*, (8), 14-24. Universidad Nacional de Colombia.
2. Paulsen, M. R., Kalita, P. K. y Rausch, K. D. (2015). Postharvest Losses due to Harvesting Operations in Developing Countries: A Review. ASABE Annual International Meeting. doi:10.13031/aim.20152176663.
3. DANE y Fedearroz-FNA (2026). Encuesta Nacional de Arroz Mecanizado (ENAM), segundo semestre y total anual 2025. Boletín técnico, 3 de febrero de 2026.
4. DANE y Fedearroz-FNA (2026). ENAM, primer semestre 2026. Boletín técnico, 11 de agosto de 2026.
5. Fedearroz. Seccional Neiva-Huila. fedearroz.com.co, consultado el 22 de octubre de 2026.
6. La República (21 de julio de 2026). Arroceros del Huila alertan sobre pérdidas por caída de precios y alza de fertilizantes. Con cifras de Fedearroz.
7. Mokhtor, S. A., El Pebrian, D. y Johari, N. A. A. (2020). Actual field speed of rice combine harvester and its influence on grain loss in Malaysian paddy field. *Journal of the Saudi Society of Agricultural Sciences*, 19(6), 422-425. doi:10.1016/j.jssas.2020.07.002.
