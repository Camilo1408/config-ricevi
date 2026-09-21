"""
base.py - El contrato que debe cumplir cualquier modelo de RiceVi.

POR QUE HAY UNA INTERFAZ Y NO UNA LLAMADA DIRECTA
-------------------------------------------------
Porque el sistema tiene que funcionar ANTES de que existan los modelos. La fase
de captura de dataset dura toda una campana y en ella no hay pesos que cargar;
la fase de inferencia llega despues. Con una interfaz, cambiar de una a otra es
una variable de entorno y no una rama del codigo.

LA REGLA QUE ESTA INTERFAZ HACE CUMPLIR
---------------------------------------
    `porcentaje` puede ser None, y None NO es cero.

Un modelo que no existe, que no pudo decodificar la imagen o cuyo ROI salio
vacio devuelve None con un `estado` que dice por que. El HMI muestra "sin
modelo" o "no evaluable", nunca "0 %". Es la diferencia entre un sistema que
calla cuando no sabe y uno que inventa un numero que acaba en la tesis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

# Estados posibles de un resultado. Si no esta aqui, no existe.
ESTADOS = (
    "valido",           # hay medida
    "sin_modelo",       # no hay pesos cargados: fase de dataset
    "roi_vacio",        # el ROI no contenia pixeles validos
    "no_evaluable",     # la escena no permite evaluar (tolva vacia, por ejemplo)
    "error_decodificar",
    "error_modelo",
    "vencido",          # el frame llego a la cola demasiado viejo
)


@dataclass
class Resultado:
    """Lo que devuelve cualquier modelo.

    `porcentaje` es la fraccion visual sobre el ROI, en tanto por ciento. Es
    NULO salvo que `estado == "valido"`.
    """

    estado: str = "sin_modelo"
    porcentaje: float | None = None

    # Clasificacion (PRE-CORTE). Nulos en tareas de segmentacion.
    clase: str | None = None
    confianza: float | None = None

    # Trazabilidad del calculo: sin el denominador, el porcentaje no se puede
    # auditar ni recalcular con otro ROI.
    pixeles_clase: int | None = None
    pixeles_roi: int | None = None

    # Ruta relativa de la mascara superpuesta, si se genero. Es un DERIVADO:
    # borrable y regenerable, y nunca sustituye al JPEG original.
    ruta_mascara: str | None = None

    ms_decodificar: float = 0.0
    ms_inferir: float = 0.0
    ms_postproceso: float = 0.0
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.estado not in ESTADOS:
            raise ValueError(f"estado '{self.estado}' no esta en {ESTADOS}")
        if self.estado != "valido" and self.porcentaje is not None:
            raise ValueError("un resultado no valido no puede llevar porcentaje")


class Modelo(Protocol):
    """Lo que la central espera de un motor de inferencia."""

    nombre: str
    version: str

    def cargar(self) -> None:
        """Carga los pesos y PRECALIENTA.

        El precalentamiento no es opcional: la primera inferencia de cualquier
        motor tarda varias veces mas que las siguientes, y sin el, el primer
        frame de cada jornada produce una medida de latencia que no representa
        nada y contamina los percentiles.
        """
        ...

    def tareas(self) -> tuple[str, ...]:
        """Que tareas sabe resolver: 'acame', 'post_corte', 'tolva'."""
        ...

    def inferir(self, octetos: bytes, tarea: str, roi: tuple[float, float, float, float],
                roi_version: str) -> Resultado:
        """Ejecuta sobre los octetos JPEG originales. No los modifica."""
        ...
