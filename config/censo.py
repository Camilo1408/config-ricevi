"""
censo.py - Quien es quien en la maquina. La unica fuente de verdad del montaje.

Define los ocho nodos, que sensor cuelga de cada uno, que magnitudes emite, que
plan recibe y en que ranura de reloj sincroniza. La central lo importa al
arrancar; ninguna de estas cifras vive dentro del firmware.

POR QUE ESTO NO ES UN .yaml NI UN .json
---------------------------------------
Porque un archivo de datos no puede comprobarse a si mismo. Aqui
`verificar()` detecta IP repetidas, nodos sin plan, sensores sin magnitudes y
calibraciones sin medir, y la central se niega a arrancar si algo critico falta.
Un YAML con una IP duplicada arranca igual y el fallo aparece en el arrozal.

    python config/censo.py     imprime el censo y avisa de lo que falta
"""

from __future__ import annotations

import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
RUTA_CALIBRACION = RAIZ / "config" / "calibracion.json"

# ---------------------------------------------------------------------------
# Versiones
# ---------------------------------------------------------------------------

# Sube CENSO_VERSION cada vez que cambies una posicion, una IP o una
# calibracion. Se escribe en el acta de cada sesion: sin el, dos jornadas con el
# mismo config_version pero distinto montaje pareceran comparables y no lo son.
CENSO_VERSION = "censo-1.0.0"

MACHINE_ID = "M01"

# ---------------------------------------------------------------------------
# Los ocho nodos
# ---------------------------------------------------------------------------
#
# `ip` es la RESERVA DHCP que hay que crear en el punto de acceso por MAC. No es
# una IP estatica grabada en el nodo: si lo fuera, llevar una placa al taller
# obligaria a reconfigurarla.
#
# `mac` se rellena al desembalar cada placa, leyendola por consola serie.

NODOS: list[dict] = [
    {"node_id": "CAM01", "tipo": "camara", "rol": "camara",
     "placa": "ESP32-S3-CAM", "vista": "frontal", "subsistema": "PRE-CORTE",
     "posicion": "Frente al cabezal, mirando el cultivo por entrar",
     "ip": "192.168.40.11", "mac": "44:BD:8D:7C:20:80", "etiqueta": "CAM01 / FRONTAL"},

    {"node_id": "CAM02", "tipo": "camara", "rol": "camara",
     "placa": "ESP32-S3-CAM", "vista": "posterior_izquierda", "subsistema": "POST-CORTE",
     "posicion": "Detras del cabezal, lado izquierdo, antes de las ruedas",
     "ip": "192.168.40.12", "mac": "44:BD:8D:7C:1D:24", "etiqueta": "CAM02 / POST IZQ"},

    {"node_id": "CAM03", "tipo": "camara", "rol": "camara",
     "placa": "ESP32-S3-CAM", "vista": "posterior_derecha", "subsistema": "POST-CORTE",
     "posicion": "Detras del cabezal, lado derecho, antes de las ruedas",
     "ip": "192.168.40.13", "mac": "B8:1F:3F:AB:12:0C", "etiqueta": "CAM03 / POST DER"},

    {"node_id": "CAM04", "tipo": "camara", "rol": "camara",
     "placa": "ESP32-S3-CAM", "vista": "tolva", "subsistema": "TOLVA",
     "posicion": "Interior de la tolva, vista fija de la superficie acumulada",
     "ip": "192.168.40.14", "mac": "44:BD:8D:7C:29:40", "etiqueta": "CAM04 / TOLVA"},

    {"node_id": "NH01", "tipo": "sensor", "rol": "hall",
     "placa": "ESP32-C6 DevKitC", "vista": None, "subsistema": "OPERACION",
     "posicion": "Junto al eje del molinete",
     "ip": "192.168.40.21", "mac": "98:A3:16:97:96:74", "etiqueta": "NH01 / MOLINETE"},

    {"node_id": "NH02", "tipo": "sensor", "rol": "hall",
     "placa": "ESP32-C6 DevKitC", "vista": None, "subsistema": "OPERACION",
     "posicion": "Junto a la rueda instrumentada",
     "ip": "192.168.40.22", "mac": "F0:F5:BD:0E:D7:30", "etiqueta": "NH02 / RUEDA"},

    {"node_id": "NU01", "tipo": "sensor", "rol": "ultrasonico",
     "placa": "ESP32-C6 DevKitC", "vista": None, "subsistema": "OPERACION",
     "posicion": "Extremo izquierdo del cabezal, mirando al suelo",
     "ip": "192.168.40.23", "mac": "", "etiqueta": "NU01 / ALTURA IZQ"},

    {"node_id": "NU02", "tipo": "sensor", "rol": "ultrasonico",
     "placa": "ESP32-C6 DevKitC", "vista": None, "subsistema": "OPERACION",
     "posicion": "Extremo derecho del cabezal, mirando al suelo",
     "ip": "192.168.40.24", "mac": "", "etiqueta": "NU02 / ALTURA DER"},
]

SENSORES_POR_NODO: dict[str, list[str]] = {
    "NH01": ["HALL01"], "NH02": ["HALL02"],
    "NU01": ["US01"],   "NU02": ["US02"],
}

# ---------------------------------------------------------------------------
# Que magnitud emite cada sensor
# ---------------------------------------------------------------------------
#
# Un Hall no emite "un numero": emite pulsos (lo que mide) y rpm (lo que
# deriva). Se publican como muestras SEPARADAS, cada una con su `magnitud`.
#
# POR QUE SE GUARDA TAMBIEN LA CRUDA: si dentro de tres meses se corrige la
# circunferencia de la rueda, con los pulsos guardados la velocidad de toda la
# campana se recalcula. Sin ellos, hay que repetir la campana.

MAGNITUDES: dict[str, list[dict]] = {
    "HALL01": [
        {"magnitud": "pulsos_ventana", "unidad": "count", "derivada": False,
         "rango": [0, 10000], "descripcion": "Pulsos contados en la ventana"},
        {"magnitud": "reel_rpm", "unidad": "rpm", "derivada": True,
         "rango": [0.0, 120.0], "requiere": ["pulsos_por_vuelta"],
         "descripcion": "Revoluciones por minuto del molinete"},
    ],
    "HALL02": [
        {"magnitud": "pulsos_ventana", "unidad": "count", "derivada": False,
         "rango": [0, 10000], "descripcion": "Pulsos contados en la ventana"},
        {"magnitud": "wheel_speed", "unidad": "m/s", "derivada": True,
         "rango": [0.0, 8.0], "requiere": ["circunferencia_rueda_m"],
         "descripcion": "Velocidad de avance estimada por rueda"},
    ],
    "US01": [
        {"magnitud": "distance", "unidad": "mm", "derivada": False,
         "rango": [30, 4500], "descripcion": "Distancia cruda del RCWL-1655 (Trig/Echo)"},
        {"magnitud": "header_height", "unidad": "mm", "derivada": True,
         "rango": [0, 2000], "requiere": ["offset_b_mm"],
         "descripcion": "Altura de cuchilla = distancia - offset_b"},
    ],
    "US02": [
        {"magnitud": "distance", "unidad": "mm", "derivada": False,
         "rango": [30, 4500], "descripcion": "Distancia cruda del RCWL-1655 (Trig/Echo)"},
        {"magnitud": "header_height", "unidad": "mm", "derivada": True,
         "rango": [0, 2000], "requiere": ["offset_b_mm"],
         "descripcion": "Altura de cuchilla = distancia - offset_b"},
    ],
}

# ---------------------------------------------------------------------------
# Codigos de calidad
# ---------------------------------------------------------------------------
#
# `calidad` decide si el dato se usa. `codigo_calidad` dice POR QUE, y es lo que
# permite diagnosticar: una tasa de invalidas del 20 % no se puede arreglar sin
# saber si es `checksum` (cableado, ruido) o `fuera_rango` (geometria, terreno).

CODIGOS_CALIDAD: dict[str, tuple[str, str]] = {
    "ok":           ("buena",    "Lectura normal dentro de rango"),
    "fuera_rango":  ("invalida", "El valor cae fuera del rango fisico declarado"),
    "checksum":     ("invalida", "La trama UART no supero la suma de verificacion"),
    "timeout":      ("invalida", "No llego trama dentro del plazo"),
    "sin_pulsos":   ("dudosa",   "Ventana sin pulsos: parada real o sensor caido"),
    "eco_dudoso":   ("dudosa",   "Distancia plausible pero inestable entre lecturas"),
    "sin_calibrar": ("invalida", "Falta la constante para derivar la magnitud"),
    "saturado":     ("dudosa",   "Valor en el limite superior del rango"),
}

# ---------------------------------------------------------------------------
# Planes por nodo
# ---------------------------------------------------------------------------
#
# Lo que la central responde en GET /v1/nodes/{id}/plan. El nodo NO lleva estos
# numeros compilados: los recibe. Cambiar el ritmo de una camara debe ser editar
# este archivo y reiniciar la central, no desmontar una caja del cabezal.
#
# `uno_de_cada_n_infiere` reparte el presupuesto de CPU: POST-CORTE es el
# indicador principal y va a 1 Hz; PRE-CORTE a 0,5 Hz; TOLVA muy por debajo
# porque la superficie acumulada cambia en minutos, no en segundos.
# LA CAPTURA NO SE TOCA: el dataset se queda con todas las imagenes.

PLANES: dict[str, dict] = {
    "CAM01": {
        "captura_fps": 1.0, "ancho": 1280, "alto": 720, "jpeg_calidad": 85,
        "uno_de_cada_n_infiere": 2,
        "tarea": "acame", "roi_version": "ROI-CAM01-01",
        "roi": [0.05, 0.30, 0.95, 1.00],
        "pedir_turno": True, "guardar_en_sd_local": False,
        # Orientacion del sensor. Con la GOOUUU sobre la mesa la OV3660 sale
        # girada 180 grados: las dos a True la enderezan. Ajustar por camara
        # segun como quede montada; cambia con reiniciar la central y el nodo.
        "voltear_v": True, "espejo_h": True,
        "exposicion_manual": False,
    },
    "CAM02": {
        "captura_fps": 1.0, "ancho": 1280, "alto": 720, "jpeg_calidad": 85,
        "uno_de_cada_n_infiere": 1,
        "tarea": "post_corte", "roi_version": "ROI-CAM02-01",
        "roi": [0.10, 0.35, 0.90, 1.00],
        "pedir_turno": True, "guardar_en_sd_local": False,
        # Orientacion del sensor. Con la GOOUUU sobre la mesa la OV3660 sale
        # girada 180 grados: las dos a True la enderezan. Ajustar por camara
        # segun como quede montada; cambia con reiniciar la central y el nodo.
        "voltear_v": True, "espejo_h": True,
        "exposicion_manual": False,
    },
    "CAM03": {
        "captura_fps": 1.0, "ancho": 1280, "alto": 720, "jpeg_calidad": 85,
        "uno_de_cada_n_infiere": 1,
        "tarea": "post_corte", "roi_version": "ROI-CAM03-01",
        "roi": [0.10, 0.35, 0.90, 1.00],
        "pedir_turno": True, "guardar_en_sd_local": False,
        # Orientacion del sensor. Con la GOOUUU sobre la mesa la OV3660 sale
        # girada 180 grados: las dos a True la enderezan. Ajustar por camara
        # segun como quede montada; cambia con reiniciar la central y el nodo.
        "voltear_v": True, "espejo_h": True,
        "exposicion_manual": False,
    },
    "CAM04": {
        "captura_fps": 0.5, "ancho": 1280, "alto": 720, "jpeg_calidad": 90,
        "uno_de_cada_n_infiere": 3,
        "tarea": "tolva", "roi_version": "ROI-CAM04-mid",
        "roi": [0.20, 0.20, 0.80, 0.85],
        "pedir_turno": True, "guardar_en_sd_local": False,
        # Orientacion del sensor. Con la GOOUUU sobre la mesa la OV3660 sale
        # girada 180 grados: las dos a True la enderezan. Ajustar por camara
        # segun como quede montada; cambia con reiniciar la central y el nodo.
        "voltear_v": True, "espejo_h": True,
        # La tolva es el unico sitio donde la exposicion NO puede ser
        # automatica. Si varia entre frames, el porcentaje segmentado cambia por
        # razones que no tienen que ver con el material.
        "exposicion_manual": True,
        "ganancia_manual": True,
        "balance_blancos_manual": True,
    },
    "NH01": {
        "muestreo_hz": 10.0, "muestras_por_lote": 10, "ventana_ms": 100,
        "pulsos_por_vuelta": 8, "flanco": "subida", "filtro_pcnt_ns": 1000,
        "pedir_turno": False,
    },
    "NH02": {
        "muestreo_hz": 10.0, "muestras_por_lote": 10, "ventana_ms": 100,
        "pulsos_por_vuelta": 8, "flanco": "subida", "filtro_pcnt_ns": 1000,
        "pedir_turno": False,
    },
    "NU01": {
        "muestreo_hz": 8.0, "muestras_por_lote": 8,
        # RCWL-1655 en modo GPIO: tiempo maximo de espera del eco (~5 m) y
        # velocidad del sonido usada para pasar de us a mm (346 m/s ~ 25 C).
        "timeout_eco_us": 30000, "velocidad_sonido_mps": 346.0,
        "pedir_turno": False,
    },
    "NU02": {
        "muestreo_hz": 8.0, "muestras_por_lote": 8,
        # RCWL-1655 en modo GPIO: tiempo maximo de espera del eco (~5 m) y
        # velocidad del sonido usada para pasar de us a mm (346 m/s ~ 25 C).
        "timeout_eco_us": 30000, "velocidad_sonido_mps": 346.0,
        "pedir_turno": False,
    },
}

# ---------------------------------------------------------------------------
# Ranuras de sincronia
# ---------------------------------------------------------------------------
#
# Ocho nodos, ocho ranuras de 3,75 s dentro del ciclo de 30 s.
#
# Las camaras van primero porque su `capture_session_us` es lo que se asocia con
# la telemetria: conviene que su offset sea el mas fresco cuando empieza la
# rafaga de imagenes.
#
# La ranura es FIJA por nodo y no por orden de llegada: si se asignara por orden
# de registro, un nodo que se reinicia en campo caeria en la ranura de otro y
# los dos sincronizarian a la vez, produciendo la rafaga que el escalonado
# quiere evitar.

ORDEN_RANURAS = ["CAM01", "CAM02", "CAM03", "CAM04", "NH01", "NH02", "NU01", "NU02"]
CICLO_SYNC_S = 30.0
RANURA_S = CICLO_SYNC_S / len(ORDEN_RANURAS)

# ---------------------------------------------------------------------------
# Alimentacion: 4 pilas AA Ni-MH en serie por nodo
# ---------------------------------------------------------------------------
#
# Decision del equipo (oct-2026), sustituye a las 18650 del diseno v1.1: cada
# nodo lleva un portapilas de 4 AA Ni-MH en serie (4,8 V nominales) que entra
# DIRECTO al pin 5V de la placa, sin elevador. El regulador de la placa baja a
# 3,3 V. La tension se mide en G1 con un divisor 150 k / 100 k (factor 2,5).
#
# divisor_montado: mientras el nodo funcione en la mesa por USB, sin el divisor
# soldado, G1 queda al aire y lee cualquier cosa. Con False el nodo no mide la
# bateria (dato nulo, nunca un numero inventado) y nunca se cree agotado. Pasar
# a True cuando las placas perforadas lleven el divisor.
#
# UMBRALES: la tension se mide en el propio nodo y viaja en el latido.
BATERIA = {
    "quimica": "Ni-MH AA",
    "configuracion": "4S",
    "celdas_por_nodo": 4,
    # La caja dice 3600 mAh; un AA Ni-MH real no pasa de ~2800. Se usa 2600
    # hasta medir un juego con descarga completa.
    "capacidad_celda_mah": 2600,
    "capacidad_paquete_mah": 2600,
    "tension_nominal_v": 4.8,
    "tension_plena_v": 5.6,
    # Descarga completa de 4 celdas (1,0 V/celda). Por debajo, el regulador de
    # la placa ya no sostiene 3,3 V con el Wi-Fi transmitiendo.
    "tension_corte_v": 4.0,
    # Umbrales que SI vigila el firmware, para avisar antes de que corte.
    "aviso_mv": 4500,      # LED de aviso y evento
    "critico_mv": 4350,    # el nodo avisa y deja de capturar ordenadamente
    "divisor": "150 k arriba / 100 k abajo (factor 2,5)",
    "divisor_factor": 2.5,
    "divisor_montado": False,
    "adc_pin_sugerido": 1,
    # SIN CARGA EN LA MAQUINA. Las pilas se cambian y se cargan fuera.
    "carga_en_maquina": False,
    "juegos_de_paquetes": 2,   # uno en la maquina, otro cargando
}

# Consumo estimado por rol, en el riel de 3,3 V. SON ESTIMACIONES PARA
# DIMENSIONAR, no medidas: hay que confirmarlas con un multimetro en serie
# sobre un nodo real antes de dar por buena la autonomia.
#
# `ahorro_wifi` es la decision que mas afecta a la autonomia, y no es uniforme:
#
#   Camaras   -> NO. El enlace es el cuello de botella de la latencia y el
#                ahorro de energia anade decenas de milisegundos impredecibles
#                a cada peticion.
#   Sensores  -> SI. Su telemetria ya viaja por lotes de ~1 s, y cada muestra
#                lleva su propio instante de captura: el retraso de entrega no
#                degrada la medida. Sale casi gratis y casi duplica la autonomia.
CONSUMO = {
    "camara":      {"ma_33v": 200, "ahorro_wifi": False, "horas_estimadas": 17},
    "hall":        {"ma_33v": 140, "ahorro_wifi": True,  "horas_estimadas": 34},
    "ultrasonico": {"ma_33v": 145, "ahorro_wifi": True,  "horas_estimadas": 33},
}


def autonomia_estimada(rol: str) -> dict:
    """Horas de autonomia estimadas para un rol, con las cuentas a la vista.

    Se publica el desglose y no solo el resultado para que cualquiera pueda
    rehacer la cuenta con sus propias medidas en vez de creerse un numero.
    """
    c = CONSUMO[rol]
    ma = c["ma_33v"]
    if c["ahorro_wifi"]:
        # Con ahorro de energia el radio no esta en recepcion continua. La
        # reduccion depende del DTIM del punto de acceso; se usa un factor
        # conservador y HAY QUE MEDIRLO.
        ma = int(ma * 0.55)

    # Las pilas entran directo a la placa y su regulador lineal baja a 3,3 V: la
    # corriente que sale de las pilas es la misma del riel de 3,3 V, asi que la
    # autonomia es capacidad / corriente, sin rendimiento de convertidor.
    w_bateria = ma / 1000.0 * BATERIA["tension_nominal_v"]
    wh_utiles = (BATERIA["capacidad_paquete_mah"] / 1000.0
                 * BATERIA["tension_nominal_v"] * 0.85)   # 85 % aprovechable
    horas = wh_utiles / w_bateria
    return {
        "rol": rol,
        "ma_33v_efectivos": ma,
        "ahorro_wifi": c["ahorro_wifi"],
        "w_en_bateria": round(w_bateria, 2),
        "wh_utiles_paquete": round(wh_utiles, 1),
        "horas_estimadas": round(horas, 1),
    }


# ---------------------------------------------------------------------------
# Acceso
# ---------------------------------------------------------------------------

def calibracion() -> dict:
    """Lee config/calibracion.json. Es el archivo que se edita con un metro."""
    if not RUTA_CALIBRACION.exists():
        return {}
    return json.loads(RUTA_CALIBRACION.read_text(encoding="utf-8"))


def ficha(node_id: str) -> dict:
    for n in NODOS:
        if n["node_id"] == node_id:
            return n
    raise KeyError(f"nodo desconocido en el censo: {node_id}")


def ranura_de(node_id: str) -> int:
    return ORDEN_RANURAS.index(node_id)


def plan_de(node_id: str) -> dict:
    """Plan efectivo de un nodo: su plan, su ranura, sus sensores y su calibracion."""
    f = ficha(node_id)
    plan = dict(PLANES[node_id])
    cal = calibracion()

    plan["node_id"] = node_id
    plan["rol"] = f["rol"]
    plan["censo_version"] = CENSO_VERSION
    plan["ranura_indice"] = ranura_de(node_id)
    plan["ranura_offset_s"] = ranura_de(node_id) * RANURA_S
    plan["ciclo_sync_s"] = CICLO_SYNC_S

    # Alimentacion: el nodo necesita saber sus umbrales de bateria y si puede
    # dormir el radio. Ninguna de las dos cosas se compila en el firmware.
    rol = f["rol"]
    plan["ahorro_wifi"] = CONSUMO[rol]["ahorro_wifi"]
    plan["bateria"] = {
        "aviso_mv": BATERIA["aviso_mv"],
        "critico_mv": BATERIA["critico_mv"],
        "corte_v": BATERIA["tension_corte_v"],
        # Sin divisor montado, sin pin: el nodo publica la bateria como nula.
        "adc_pin": BATERIA["adc_pin_sugerido"] if BATERIA["divisor_montado"] else None,
        "divisor": BATERIA["divisor_factor"],
    }

    if node_id in SENSORES_POR_NODO:
        sensores = SENSORES_POR_NODO[node_id]
        plan["sensores"] = sensores
        plan["magnitudes"] = {s: [m["magnitud"] for m in MAGNITUDES[s]] for s in sensores}
        # Las constantes de derivacion viajan en el plan. El nodo las aplica y
        # ademas las devuelve en cada muestra, para que el dato sea auditable
        # sin tener que saber que configuracion habia ese dia.
        porsensor = cal.get("sensores", {})
        plan["calibracion"] = {s: porsensor.get(s, {}) for s in sensores}
        plan["calibration_id"] = cal.get("calibration_id", "SIN-CALIBRAR")

    return plan


# ---------------------------------------------------------------------------
# Verificacion
# ---------------------------------------------------------------------------

def verificar() -> dict:
    """Comprueba lo que un despiste rompe en campo.

    Separa lo BLOQUEANTE (impide arrancar: corrompe datos o identidad) de los
    AVISOS (el sistema funciona y captura dataset valido, pero hay magnitudes
    derivadas que no se pueden publicar).
    """
    bloqueantes: list[str] = []
    avisos: list[str] = []

    ids = [n["node_id"] for n in NODOS]
    ips = [n["ip"] for n in NODOS]

    if len(set(ids)) != len(ids):
        bloqueantes.append("hay node_id repetidos en el censo")
    if len(set(ips)) != len(ips):
        bloqueantes.append("hay IP repetidas en el censo")
    if set(ids) != set(ORDEN_RANURAS):
        bloqueantes.append("ORDEN_RANURAS no coincide con la lista de nodos")

    for n in NODOS:
        nid = n["node_id"]
        if nid not in PLANES:
            bloqueantes.append(f"{nid}: no tiene plan definido")
        if not n["mac"]:
            avisos.append(f"{nid}: falta la MAC, no se puede reservar DHCP")

    for nodo, sensores in SENSORES_POR_NODO.items():
        for s in sensores:
            if s not in MAGNITUDES:
                bloqueantes.append(f"{nodo}: el sensor {s} no tiene magnitudes declaradas")

    # Calibracion: lo que impide publicar una magnitud derivada.
    cal = calibracion()
    porsensor = cal.get("sensores", {})
    for sensor, mags in MAGNITUDES.items():
        for m in mags:
            for req in m.get("requiere", []):
                v = porsensor.get(sensor, {}).get(req)
                if v is None:
                    avisos.append(
                        f"{sensor}.{m['magnitud']}: falta '{req}' en calibracion.json")
                elif porsensor.get(sensor, {}).get(f"{req}__medido") is not True:
                    avisos.append(
                        f"{sensor}.{m['magnitud']}: '{req}' = {v} es PROVISIONAL, "
                        f"sin medir. La magnitud derivada no se puede publicar")

    return {"bloqueantes": bloqueantes, "avisos": avisos,
            "apto_para_arrancar": not bloqueantes}


def resumen() -> dict:
    """Instantanea del censo para el acta de sesion."""
    return {
        "censo_version": CENSO_VERSION,
        "machine_id": MACHINE_ID,
        "nodos": {n["node_id"]: {k: n[k] for k in
                                 ("tipo", "rol", "ip", "mac", "posicion", "etiqueta")}
                  for n in NODOS},
        "planes": PLANES,
        "sensores_por_nodo": SENSORES_POR_NODO,
        "magnitudes": MAGNITUDES,
        "orden_ranuras": ORDEN_RANURAS,
        "bateria": BATERIA,
        "consumo": CONSUMO,
        "autonomia": {r: autonomia_estimada(r) for r in CONSUMO},
        "calibracion": calibracion(),
        "verificacion": verificar(),
    }


if __name__ == "__main__":
    r = resumen()
    print(json.dumps(r, indent=2, ensure_ascii=False))
    v = r["verificacion"]
    print()
    for b in v["bloqueantes"]:
        print("  BLOQUEANTE: " + b)
    for a in v["avisos"]:
        print("  aviso: " + a)
    if not v["bloqueantes"] and not v["avisos"]:
        print("Censo completo y coherente.")
    elif not v["bloqueantes"]:
        print(f"\nApto para arrancar, con {len(v['avisos'])} aviso(s).")
    else:
        print(f"\nNO APTO: {len(v['bloqueantes'])} problema(s) bloqueante(s).")
        raise SystemExit(1)
