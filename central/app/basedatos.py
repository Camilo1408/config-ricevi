"""
basedatos.py - Esquema SQLite y TODAS las escrituras del sistema.

POR QUE TODAS LAS ESCRITURAS VIVEN AQUI
---------------------------------------
Concentrarlas garantiza que el archivo JPEG en disco y su fila en la base van
juntos. Repartidas por el codigo, tarde o temprano aparece un frame sin fila --
o peor, una fila que apunta a un archivo que no existe. Es el tipo de
incoherencia que arruina un dataset y no se detecta hasta meses despues.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from . import config

# Una conexion por hilo. Un sqlite3.Connection no se comparte entre hilos sin
# cuidado, y aqui hay al menos cuatro: servidor, inferencia, fusion y salud.
_local = threading.local()


def conexion() -> sqlite3.Connection:
    con = getattr(_local, "con", None)
    if con is None:
        con = sqlite3.connect(config.RUTA_BD, timeout=15.0, isolation_level=None)
        # Las filas se leen por nombre (fila["frame_id"]) y no por posicion. Un
        # indice numerico se rompe en silencio al anadir una columna.
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")       # lectura y escritura en paralelo
        con.execute("PRAGMA synchronous=NORMAL")     # ver nota de apagado seguro
        con.execute("PRAGMA busy_timeout=15000")
        con.execute("PRAGMA foreign_keys=ON")
        _local.con = con
    return con


ESQUEMA = """
CREATE TABLE IF NOT EXISTS sesiones (
    session_id      TEXT PRIMARY KEY,
    machine_id      TEXT NOT NULL,
    inicio_utc      TEXT NOT NULL,
    fin_utc         TEXT,
    clock_epoch_id  TEXT NOT NULL,
    config_version  TEXT NOT NULL,
    censo_version   TEXT NOT NULL,
    modelo          TEXT NOT NULL,
    -- Instantanea completa de config.resumen() + censo.resumen(), avisos
    -- incluidos. Sin esto, dos jornadas con el mismo config_version pero
    -- distinto montaje pareceran comparables y no lo son.
    acta_json       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS nodos (
    node_id         TEXT PRIMARY KEY,
    tipo            TEXT NOT NULL,
    rol             TEXT NOT NULL DEFAULT '',
    boot_id         TEXT,
    ranura_indice   INTEGER,
    ip              TEXT,
    firmware        TEXT,
    motivo_reinicio TEXT NOT NULL DEFAULT '',
    ultimo_visto_us INTEGER,
    registros       INTEGER NOT NULL DEFAULT 0,
    -- Estado que llega colgado del latido. Con ocho paquetes 18650
    -- independientes, saber cual se esta agotando es lo que evita perder una
    -- vista a mitad de jornada sin aviso previo.
    bateria_mv      INTEGER,
    rssi_dbm        INTEGER,
    heap_libre      INTEGER,
    pendientes_sd   INTEGER
);

-- Se guardan TODOS los intercambios, no solo el ultimo: la deriva del reloj
-- solo se puede calcular con la serie historica, y la nube (RTT, offset) es
-- una figura directa para el documento de grado.
CREATE TABLE IF NOT EXISTS intercambios_tiempo (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id     TEXT NOT NULL,
    t1_us       INTEGER NOT NULL,
    t2_us       INTEGER NOT NULL,
    t3_us       INTEGER NOT NULL,
    t4_us       INTEGER,
    offset_us   INTEGER,
    rtt_us      INTEGER,
    session_us  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_tiempo_nodo ON intercambios_tiempo(node_id, id);

CREATE TABLE IF NOT EXISTS frames (
    -- frame_id es CLAVE PRIMARIA, no autoincremento: la idempotencia pasa a
    -- ser una propiedad de la base y no una comprobacion que se pueda olvidar.
    frame_id            TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL,
    node_id             TEXT NOT NULL,
    camera_id           TEXT NOT NULL,
    boot_id             TEXT NOT NULL,
    seq                 INTEGER NOT NULL,
    capture_mono_us     INTEGER NOT NULL,
    capture_session_us  INTEGER NOT NULL,
    sync_uncertainty_ms REAL NOT NULL,
    clock_epoch_id      TEXT NOT NULL,
    capture_utc         TEXT,
    utc_quality         TEXT NOT NULL,
    recibido_session_us INTEGER NOT NULL,
    bytes               INTEGER NOT NULL,
    sha256              TEXT NOT NULL,
    ruta                TEXT NOT NULL,
    ancho               INTEGER NOT NULL,
    alto                INTEGER NOT NULL,
    jpeg_calidad        INTEGER NOT NULL,
    pendientes_en_sd    INTEGER,
    ms_recepcion        REAL NOT NULL,
    ms_escritura        REAL NOT NULL,
    config_version      TEXT NOT NULL,
    censo_version       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_frames_tiempo ON frames(capture_session_us);
CREATE INDEX IF NOT EXISTS ix_frames_camara ON frames(camera_id, capture_session_us);
CREATE INDEX IF NOT EXISTS ix_frames_seq    ON frames(camera_id, boot_id, seq);

CREATE TABLE IF NOT EXISTS telemetria (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT NOT NULL,
    node_id             TEXT NOT NULL,
    sensor_id           TEXT NOT NULL,
    magnitud            TEXT NOT NULL DEFAULT '',
    boot_id             TEXT NOT NULL,
    seq                 INTEGER NOT NULL,
    capture_mono_us     INTEGER NOT NULL,
    capture_session_us  INTEGER NOT NULL,
    ventana_us          INTEGER NOT NULL,
    -- NULO cuando no hay medida. Nunca cero.
    valor               REAL,
    unidad              TEXT NOT NULL,
    calidad             TEXT NOT NULL,
    codigo_calidad      TEXT NOT NULL DEFAULT 'ok',
    calibration_id      TEXT,
    pulsos_ventana      INTEGER,
    pulsos_acumulados   INTEGER,
    pulsos_por_vuelta   INTEGER,
    edad_ultimo_pulso_ms INTEGER,
    periodo_ultimo_us   INTEGER,
    distancia_cruda_mm  INTEGER,
    offset_b_mm         INTEGER,
    tramas_descartadas  INTEGER,
    sync_uncertainty_ms REAL NOT NULL,
    recibido_session_us INTEGER NOT NULL,
    config_version      TEXT NOT NULL,
    censo_version       TEXT NOT NULL DEFAULT '',
    -- Evita duplicados si un nodo reenvia un lote tras un timeout dudoso.
    -- Incluye magnitud porque un sensor emite varias con el mismo seq.
    UNIQUE(node_id, boot_id, sensor_id, magnitud, seq)
);
CREATE INDEX IF NOT EXISTS ix_telem_busqueda
    ON telemetria(sensor_id, magnitud, capture_session_us);
CREATE INDEX IF NOT EXISTS ix_telem_calidad
    ON telemetria(sensor_id, codigo_calidad);

-- DERIVADA: se puede borrar y regenerar desde `telemetria` sin perder nada.
-- Por eso no lleva claves ajenas que compliquen el borrado.
CREATE TABLE IF NOT EXISTS estado_maquina (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id           TEXT NOT NULL,
    session_us           INTEGER NOT NULL,
    reel_rpm             REAL,
    reel_rpm_edad_ms     INTEGER,
    wheel_speed_mps      REAL,
    wheel_speed_edad_ms  INTEGER,
    altura_izq_mm        REAL,
    altura_izq_edad_ms   INTEGER,
    altura_der_mm        REAL,
    altura_der_edad_ms   INTEGER,
    altura_media_mm      REAL,
    altura_dif_mm        REAL,
    reel_index           REAL,
    ri_pairing_skew_ms   INTEGER,
    ri_estado            TEXT NOT NULL DEFAULT 'sin_datos',
    nodos_ausentes       TEXT NOT NULL DEFAULT '',
    calibration_id       TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS ix_estado_tiempo ON estado_maquina(session_us);

CREATE TABLE IF NOT EXISTS resultados (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    frame_id            TEXT NOT NULL REFERENCES frames(frame_id),
    tarea               TEXT NOT NULL,
    modelo              TEXT NOT NULL,
    modelo_version      TEXT NOT NULL,
    -- NULO cuando no hay modelo o la inferencia no es valida. El HMI distingue
    -- "sin modelo" de "0 %", y esa distincion es la que impide que un
    -- porcentaje inventado acabe en la tesis.
    porcentaje          REAL,
    estado              TEXT NOT NULL DEFAULT 'valido',
    clase               TEXT,
    confianza           REAL,
    pixeles_clase       INTEGER,
    pixeles_roi         INTEGER,
    roi_version         TEXT NOT NULL DEFAULT '',
    ruta_mascara        TEXT,
    encolado_session_us INTEGER NOT NULL,
    inicio_session_us   INTEGER NOT NULL,
    fin_session_us      INTEGER NOT NULL,
    ms_espera_cola      REAL NOT NULL,
    ms_decodificar      REAL NOT NULL,
    ms_inferir          REAL NOT NULL,
    ms_postproceso      REAL NOT NULL DEFAULT 0,
    temp_c              REAL,
    estado_termico      TEXT NOT NULL DEFAULT '',
    -- Un frame puede tener varias inferencias: la del modelo vigente y la de
    -- cualquier modelo posterior ejecutado en diferido. Actualizar un modelo
    -- no borra la prediccion anterior.
    UNIQUE(frame_id, modelo, modelo_version)
);
CREATE INDEX IF NOT EXISTS ix_resultados_fin ON resultados(fin_session_us);
CREATE INDEX IF NOT EXISTS ix_resultados_frame ON resultados(frame_id);

CREATE TABLE IF NOT EXISTS eventos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id     TEXT NOT NULL,
    tipo        TEXT NOT NULL,
    detalle     TEXT NOT NULL,
    session_us  INTEGER NOT NULL,
    utc         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_eventos_tipo ON eventos(tipo, id);
"""


def inicializar(session_id: str, clock_epoch_id: str, inicio_utc: str,
                censo_version: str, modelo: str, acta_json: str) -> None:
    con = conexion()
    con.executescript(ESQUEMA)
    con.execute(
        """INSERT OR REPLACE INTO sesiones
           (session_id, machine_id, inicio_utc, clock_epoch_id, config_version,
            censo_version, modelo, acta_json)
           VALUES (?,?,?,?,?,?,?,?)""",
        (session_id, config.MACHINE_ID, inicio_utc, clock_epoch_id,
         config.CONFIG_VERSION, censo_version, modelo, acta_json),
    )


def cerrar_sesion(session_id: str, fin_utc: str) -> None:
    conexion().execute("UPDATE sesiones SET fin_utc=? WHERE session_id=?",
                       (fin_utc, session_id))


# ---------------------------------------------------------------------------
# Escrituras
# ---------------------------------------------------------------------------


def registrar_nodo(node_id: str, tipo: str, rol: str, boot_id: str, ranura: int,
                   ip: str, firmware: str, motivo: str, session_us: int) -> None:
    conexion().execute(
        """INSERT INTO nodos (node_id, tipo, rol, boot_id, ranura_indice, ip,
                              firmware, motivo_reinicio, ultimo_visto_us, registros)
           VALUES (?,?,?,?,?,?,?,?,?,1)
           ON CONFLICT(node_id) DO UPDATE SET
               tipo=excluded.tipo, rol=excluded.rol, boot_id=excluded.boot_id,
               ranura_indice=excluded.ranura_indice, ip=excluded.ip,
               firmware=excluded.firmware, motivo_reinicio=excluded.motivo_reinicio,
               ultimo_visto_us=excluded.ultimo_visto_us,
               registros=nodos.registros+1""",
        (node_id, tipo, rol, boot_id, ranura, ip, firmware, motivo, session_us),
    )


def tocar_nodo(node_id: str, session_us: int, bateria_mv: int | None = None,
               rssi_dbm: int | None = None, heap_libre: int | None = None,
               pendientes_sd: int | None = None,
               tipo: str = "", rol: str = "") -> None:
    """Marca al nodo como visto y actualiza lo que haya reportado.

    ES UN UPSERT, NO UN UPDATE, y la diferencia importa: con un UPDATE simple,
    un nodo que envia datos sin haberse registrado -- porque la central se
    reinicio entre medias, por ejemplo -- guardaria sus muestras en la base y
    NO APARECERIA en la lista de nodos del HMI. Estaria trabajando y seria
    invisible. `tipo` y `rol` salen del censo, no del mensaje, asi que no se
    inventa nada.

    COALESCE y no asignacion directa: una peticion de telemetria no trae estado
    de bateria, y sin COALESCE lo borraria. Solo se sobrescribe lo que llega.
    """
    conexion().execute(
        """INSERT INTO nodos (node_id, tipo, rol, ultimo_visto_us, registros,
                              bateria_mv, rssi_dbm, heap_libre, pendientes_sd)
           VALUES (?,?,?,?,0,?,?,?,?)
           ON CONFLICT(node_id) DO UPDATE SET
               ultimo_visto_us = excluded.ultimo_visto_us,
               bateria_mv    = COALESCE(excluded.bateria_mv, nodos.bateria_mv),
               rssi_dbm      = COALESCE(excluded.rssi_dbm, nodos.rssi_dbm),
               heap_libre    = COALESCE(excluded.heap_libre, nodos.heap_libre),
               pendientes_sd = COALESCE(excluded.pendientes_sd, nodos.pendientes_sd)""",
        (node_id, tipo, rol, session_us, bateria_mv, rssi_dbm,
         heap_libre, pendientes_sd))


def guardar_intercambio(node_id: str, t1: int, t2: int, t3: int, session_us: int) -> None:
    conexion().execute(
        "INSERT INTO intercambios_tiempo (node_id, t1_us, t2_us, t3_us, session_us) "
        "VALUES (?,?,?,?,?)", (node_id, t1, t2, t3, session_us))


def completar_intercambio(node_id: str, t4: int, offset: int, rtt: int) -> None:
    """Rellena t4, offset y rtt del ultimo intercambio incompleto de este nodo.

    Llegan colgados de la SIGUIENTE peticion del nodo (piggyback). Se actualiza
    la fila mas reciente con t4 nulo: es la que corresponde, porque los
    intercambios de un nodo son estrictamente secuenciales.
    """
    conexion().execute(
        """UPDATE intercambios_tiempo SET t4_us=?, offset_us=?, rtt_us=?
            WHERE id = (SELECT id FROM intercambios_tiempo
                         WHERE node_id=? AND t4_us IS NULL
                      ORDER BY id DESC LIMIT 1)""",
        (t4, offset, rtt, node_id))


def existe_frame(frame_id: str) -> sqlite3.Row | None:
    return conexion().execute(
        "SELECT frame_id, sha256, ruta FROM frames WHERE frame_id=?",
        (frame_id,)).fetchone()


def guardar_frame(datos: dict) -> None:
    """Inserta la fila del frame.

    Se llama DESPUES de que el archivo este escrito y renombrado. El orden
    importa: una fila antes que el archivo dejaria, ante una caida, una fila
    apuntando a la nada -- el caso dificil de detectar. Al reves, un archivo
    huerfano se encuentra con un listado.
    """
    campos = ", ".join(datos)
    marcas = ", ".join("?" * len(datos))
    conexion().execute(f"INSERT INTO frames ({campos}) VALUES ({marcas})",
                       tuple(datos.values()))


COLUMNAS_TELEMETRIA = (
    "session_id", "node_id", "sensor_id", "magnitud", "boot_id", "seq",
    "capture_mono_us", "capture_session_us", "ventana_us", "valor", "unidad",
    "calidad", "codigo_calidad", "calibration_id", "pulsos_ventana",
    "pulsos_acumulados", "pulsos_por_vuelta", "edad_ultimo_pulso_ms",
    "periodo_ultimo_us", "distancia_cruda_mm", "offset_b_mm",
    "tramas_descartadas", "sync_uncertainty_ms", "recibido_session_us",
    "config_version", "censo_version",
)


def guardar_telemetria(filas: list[tuple]) -> list[int]:
    """Inserta un lote entero en UNA transaccion.

    Diez muestras en diez transacciones cuestan diez veces mas trabajo de disco
    que diez en una. Ademas el lote es atomico: o entran todas o ninguna, y el
    nodo nunca ve un exito parcial que no sabria como reintentar.
    """
    con = conexion()
    campos = ", ".join(COLUMNAS_TELEMETRIA)
    marcas = ", ".join("?" * len(COLUMNAS_TELEMETRIA))
    sql = f"INSERT OR IGNORE INTO telemetria ({campos}) VALUES ({marcas})"
    ids: list[int] = []
    con.execute("BEGIN")
    try:
        for f in filas:
            cur = con.execute(sql, f)
            # Se mira rowcount, NO lastrowid: con INSERT OR IGNORE, cuando la
            # fila se ignora por chocar contra el UNIQUE, lastrowid conserva el
            # valor del ultimo insert que si ocurrio. Usarlo haria que un lote
            # reenviado pareciera haberse insertado otra vez.
            if cur.rowcount > 0:
                ids.append(cur.lastrowid)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return ids


def guardar_resultado(datos: dict) -> None:
    campos = ", ".join(datos)
    marcas = ", ".join("?" * len(datos))
    conexion().execute(
        f"INSERT OR REPLACE INTO resultados ({campos}) VALUES ({marcas})",
        tuple(datos.values()))


def guardar_estado_maquina(datos: dict) -> None:
    campos = ", ".join(datos)
    marcas = ", ".join("?" * len(datos))
    conexion().execute(
        f"INSERT INTO estado_maquina ({campos}) VALUES ({marcas})",
        tuple(datos.values()))


def guardar_evento(node_id: str, tipo: str, detalle: str,
                   session_us: int, utc: str) -> None:
    conexion().execute(
        "INSERT INTO eventos (node_id, tipo, detalle, session_us, utc) "
        "VALUES (?,?,?,?,?)", (node_id, tipo, detalle, session_us, utc))


# ---------------------------------------------------------------------------
# Lecturas
# ---------------------------------------------------------------------------


def ultima_muestra(sensor_id: str, magnitud: str) -> sqlite3.Row | None:
    """La ultima muestra VALIDA de una magnitud. La usa la fusion."""
    return conexion().execute(
        """SELECT valor, capture_session_us, calibration_id, codigo_calidad
             FROM telemetria
            WHERE sensor_id=? AND magnitud=? AND valor IS NOT NULL
              AND calidad != 'invalida'
         ORDER BY capture_session_us DESC LIMIT 1""",
        (sensor_id, magnitud)).fetchone()


def estado_maquina_cercano(session_us: int, tolerancia_us: int) -> sqlite3.Row | None:
    return conexion().execute(
        """SELECT * FROM estado_maquina
            WHERE session_us BETWEEN ? AND ?
         ORDER BY ABS(session_us - ?) LIMIT 1""",
        (session_us - tolerancia_us, session_us + tolerancia_us, session_us)).fetchone()


def ultimo_estado_maquina() -> sqlite3.Row | None:
    return conexion().execute(
        "SELECT * FROM estado_maquina ORDER BY session_us DESC LIMIT 1").fetchone()


def frame(frame_id: str) -> sqlite3.Row | None:
    return conexion().execute("SELECT * FROM frames WHERE frame_id=?",
                              (frame_id,)).fetchone()


def estado_nodos() -> list[dict]:
    filas = conexion().execute(
        """SELECT n.node_id, n.tipo, n.rol, n.boot_id, n.ranura_indice, n.ip,
                  n.ultimo_visto_us, n.registros, n.motivo_reinicio,
                  n.bateria_mv, n.rssi_dbm, n.heap_libre, n.pendientes_sd,
                  (SELECT COUNT(*) FROM frames f WHERE f.node_id=n.node_id) AS frames,
                  (SELECT COUNT(*) FROM telemetria t WHERE t.node_id=n.node_id) AS muestras,
                  -- Se pide la ultima fila YA COMPLETADA: la mas reciente suele
                  -- estar esperando su t4, que llega por piggyback.
                  (SELECT rtt_us FROM intercambios_tiempo i
                    WHERE i.node_id=n.node_id AND i.rtt_us IS NOT NULL
                 ORDER BY i.id DESC LIMIT 1) AS rtt_us,
                  (SELECT offset_us FROM intercambios_tiempo i
                    WHERE i.node_id=n.node_id AND i.offset_us IS NOT NULL
                 ORDER BY i.id DESC LIMIT 1) AS offset_us
             FROM nodos n ORDER BY n.node_id""").fetchall()
    return [dict(f) for f in filas]


def resultado_por_camara() -> list[dict]:
    """El ultimo resultado de cada camara. Es lo que ve el operario."""
    filas = conexion().execute(
        """SELECT f.camera_id, r.tarea, r.porcentaje, r.estado, r.clase, r.confianza,
                  r.modelo, r.modelo_version, r.fin_session_us, r.ms_inferir,
                  r.ms_espera_cola, r.frame_id, f.capture_session_us
             FROM resultados r JOIN frames f USING (frame_id)
             JOIN (SELECT f2.camera_id AS cam, MAX(r2.fin_session_us) AS ult
                     FROM resultados r2 JOIN frames f2 USING (frame_id)
                    GROUP BY f2.camera_id) u
               ON u.cam=f.camera_id AND u.ult=r.fin_session_us
            ORDER BY f.camera_id""").fetchall()
    return [dict(f) for f in filas]


def salud_sensores() -> list[dict]:
    """Tasa de cada codigo de calidad por sensor. Dice a que nodo hay que ir."""
    filas = conexion().execute(
        """SELECT sensor_id, magnitud, codigo_calidad, COUNT(*) AS n
             FROM telemetria
         GROUP BY sensor_id, magnitud, codigo_calidad
         ORDER BY sensor_id, magnitud, n DESC""").fetchall()
    return [dict(f) for f in filas]


def huecos_secuencia(camera_id: str) -> list[dict]:
    """Saltos en la secuencia de una camara: asi se detecta una perdida."""
    filas = conexion().execute(
        """SELECT boot_id, seq,
                  seq - LAG(seq) OVER (PARTITION BY boot_id ORDER BY seq) AS salto
             FROM frames WHERE camera_id=? ORDER BY boot_id, seq""",
        (camera_id,)).fetchall()
    return [dict(f) for f in filas if f["salto"] is not None and f["salto"] > 1]


def contadores() -> dict:
    con = conexion()

    def uno(sql: str) -> int:
        r = con.execute(sql).fetchone()
        return int(r[0]) if r and r[0] is not None else 0

    return {
        "frames": uno("SELECT COUNT(*) FROM frames"),
        "muestras": uno("SELECT COUNT(*) FROM telemetria"),
        "muestras_nulas": uno("SELECT COUNT(*) FROM telemetria WHERE valor IS NULL"),
        "resultados": uno("SELECT COUNT(*) FROM resultados"),
        "bytes_frames": uno("SELECT SUM(bytes) FROM frames"),
        "eventos": uno("SELECT COUNT(*) FROM eventos"),
        "estados_maquina": uno("SELECT COUNT(*) FROM estado_maquina"),
    }


def asociar(frame_id: str, tolerancia_ms: float) -> dict:
    """Asociacion imagen <-> telemetria.

    Para cada magnitud busca la muestra VALIDA mas cercana dentro de la
    tolerancia. Devuelve tambien las ausentes: si falta un sensor, la imagen se
    conserva con asociacion incompleta, no se descarta.
    """
    con = conexion()
    f = con.execute("SELECT capture_session_us FROM frames WHERE frame_id=?",
                    (frame_id,)).fetchone()
    if f is None:
        return {"frame_id": frame_id, "encontrado": False}

    t = f["capture_session_us"]
    tol = int(tolerancia_ms * 1000)
    pares = con.execute(
        "SELECT DISTINCT sensor_id, magnitud FROM telemetria").fetchall()

    asociadas, ausentes = [], []
    for p in pares:
        m = con.execute(
            """SELECT sensor_id, magnitud, valor, unidad, capture_session_us,
                      ventana_us, calidad, codigo_calidad
                 FROM telemetria
                WHERE sensor_id=? AND magnitud=? AND valor IS NOT NULL
                  AND calidad != 'invalida'
                  AND capture_session_us BETWEEN ? AND ?
             ORDER BY ABS(capture_session_us - ?) LIMIT 1""",
            (p["sensor_id"], p["magnitud"], t - tol, t + tol, t)).fetchone()
        if m is None:
            ausentes.append(f"{p['sensor_id']}.{p['magnitud']}")
        else:
            d = dict(m)
            d["distancia_ms"] = (m["capture_session_us"] - t) / 1000.0
            asociadas.append(d)

    if not pares:
        calidad = "sin_contexto"
    elif not ausentes:
        calidad = "completa"
    elif asociadas:
        calidad = "parcial"
    else:
        calidad = "sin_contexto"

    return {"frame_id": frame_id, "encontrado": True, "capture_session_us": t,
            "tolerancia_ms": tolerancia_ms, "calidad_asociacion": calidad,
            "asociadas": asociadas, "ausentes": ausentes}


def exportar_csv(destino: Path) -> dict[str, int]:
    import csv

    destino.mkdir(parents=True, exist_ok=True)
    con = conexion()
    tablas = ["frames", "telemetria", "estado_maquina", "resultados",
              "intercambios_tiempo", "nodos", "eventos", "sesiones"]
    conteo: dict[str, int] = {}
    for t in tablas:
        filas = con.execute(f"SELECT * FROM {t}").fetchall()
        conteo[t] = len(filas)
        with open(destino / f"{t}.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            if filas:
                w.writerow(filas[0].keys())
                w.writerows([tuple(r) for r in filas])
    return conteo
