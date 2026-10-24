"""
prueba_humo.py - Arranca la central en memoria y recorre el camino completo.

QUE COMPRUEBA
-------------
Que el ciclo de arranque, el censo, la base, los turnos, la ingesta, el GPS, la
fusion y el HMI encajan entre si. No comprueba hardware ni red: para eso estan
verificar_campo.py y los nodos reales. El GPS se alimenta con tramas NMEA
escritas a mano, sin receptor.

Se ejecuta en el portatil, sin Pi y sin ESP32, antes de copiar nada:

    python herramientas/prueba_humo.py
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

# Entorno de prueba: datos en un temporal, sin tokens, sin modelo.
TMP = Path(tempfile.mkdtemp(prefix="ricevi-humo-"))
os.environ["RICEVI_DIR_DATOS"] = str(TMP)
os.environ["RICEVI_EXIGIR_TOKEN"] = "0"
os.environ["RICEVI_MODELO"] = "ninguno"
os.environ["RICEVI_VIGILAR_TEMP"] = "0"
# Sin receptor: el hilo no arranca y las tramas se inyectan a mano.
os.environ["RICEVI_GPS"] = "0"

sys.path.insert(0, str(RAIZ / "central"))
sys.path.insert(0, str(RAIZ))

from fastapi.testclient import TestClient  # noqa: E402

from app import fusion, gps  # noqa: E402
from app.main import app  # noqa: E402

OK, FALLO = 0, 0


def comprobar(nombre: str, condicion: bool, detalle: str = "") -> None:
    global OK, FALLO
    if condicion:
        OK += 1
        print(f"  OK    {nombre}")
    else:
        FALLO += 1
        print(f"  FALLO {nombre}  {detalle}")


def jpeg_falso(n: int = 1200) -> bytes:
    """Octetos con cabecera JPEG. No hace falta una imagen real: lo que se
    prueba es el transporte y la integridad, no la decodificacion."""
    cuerpo = bytes((i * 7 + 13) % 256 for i in range(n))
    return b"\xff\xd8\xff\xe0" + cuerpo + b"\xff\xd9"


def nmea(cuerpo: str) -> str:
    """Una trama NMEA con su suma de verificacion."""
    suma = 0
    for ch in cuerpo:
        suma ^= ord(ch)
    return f"${cuerpo}*{suma:02X}"


def main() -> int:
    print(f"Datos de prueba en {TMP}\n")
    with TestClient(app) as c:
        # --- arranque -------------------------------------------------------
        r = c.get("/salud")
        comprobar("/salud responde 200", r.status_code == 200, str(r.status_code))
        sid = r.json()["session_id"]
        comprobar("hay session_id", bool(sid), sid)
        comprobar("arranca en fase de dataset", r.json()["modelo"] == "ninguno")

        # --- registro -------------------------------------------------------
        reg = {"schema_version": "1.1", "machine_id": "M01", "node_id": "CAM02",
               "boot_id": "B03", "tipo": "camara", "rol": "camara",
               "firmware": "humo", "plataforma": "test", "motivo_reinicio": "POWERON"}
        r = c.post("/v1/nodes/register", json=reg)
        comprobar("registro de CAM02", r.status_code == 200, r.text[:160])
        plan = r.json()["plan"]
        comprobar("el plan trae su ranura", r.json()["ranura_indice"] == 1,
                  str(r.json().get("ranura_indice")))
        comprobar("el plan trae ROI de CAM02",
                  plan.get("roi_version") == "ROI-CAM02-01", str(plan.get("roi_version")))

        # Un nodo que no esta en el censo no entra.
        r = c.post("/v1/nodes/register", json={**reg, "node_id": "CAM99"})
        comprobar("un nodo fuera del censo es rechazado", r.status_code == 403,
                  str(r.status_code))

        # --- reloj ----------------------------------------------------------
        r = c.post("/v1/time/exchange", json={"node_id": "CAM02", "t1_us": 1000})
        comprobar("intercambio de tiempos", r.status_code == 200, r.text[:120])
        d = r.json()
        comprobar("t3 >= t2", d["t3_us"] >= d["t2_us"])

        # --- turno ----------------------------------------------------------
        r = c.post("/v1/upload-slots",
                   json={"node_id": "CAM02", "bytes_estimados": 1300})
        comprobar("turno concedido", r.json().get("concedido") is True, r.text[:120])
        turno = r.json()["turno_id"]

        r = c.post("/v1/upload-slots",
                   json={"node_id": "CAM03", "bytes_estimados": 1300})
        comprobar("el segundo turno se deniega (control de admision)",
                  r.json().get("concedido") is False, r.text[:120])

        r = c.post("/v1/upload-slots",
                   json={"node_id": "CAM02", "bytes_estimados": 99_000_000})
        comprobar("un tamano absurdo se rechaza con 413", r.status_code == 413,
                  str(r.status_code))

        # --- frame ----------------------------------------------------------
        octetos = jpeg_falso()
        fid = "M01-" + sid + "-CAM02-B03-000036"
        meta = {"schema_version": "1.1", "machine_id": "M01", "node_id": "CAM02",
                "boot_id": "B03", "seq": 36, "session_id": sid, "camera_id": "CAM02",
                "frame_id": fid, "capture_mono_us": 5_000_000,
                "capture_session_us": 5_000_000, "sync_uncertainty_ms": 3.2,
                "clock_epoch_id": "E-x", "capture_utc": None,
                "utc_quality": "desconocida", "bytes": len(octetos),
                "sha256": hashlib.sha256(octetos).hexdigest(),
                "ancho": 1280, "alto": 720, "jpeg_calidad": 85,
                "turno_id": turno, "pendientes_en_sd": 0}

        def enviar(m: dict, o: bytes):
            return c.post("/v1/frames",
                          data={"meta": json.dumps(m)},
                          files={"imagen": ("f.jpg", io.BytesIO(o), "image/jpeg")})

        r = enviar(meta, octetos)
        comprobar("frame persistido con 201", r.status_code == 201, r.text[:200])

        # Reenvio identico: idempotente, 200, sin duplicar.
        r = enviar(meta, octetos)
        comprobar("reenvio identico devuelve 200", r.status_code == 200,
                  str(r.status_code))

        # Mismo id, otro contenido: conflicto real.
        otros = jpeg_falso(1300)
        m2 = {**meta, "bytes": len(otros),
              "sha256": hashlib.sha256(otros).hexdigest()}
        r = enviar(m2, otros)
        comprobar("mismo frame_id con otro hash da 409", r.status_code == 409,
                  str(r.status_code))

        # Hash que no cuadra con los octetos.
        m3 = {**meta, "frame_id": "M01-" + sid + "-CAM02-B03-000037", "seq": 37,
              "sha256": "0" * 64}
        r = enviar(m3, octetos)
        comprobar("hash incorrecto da 422", r.status_code == 422, str(r.status_code))

        # frame_id que no corresponde al nodo.
        m4 = {**meta, "frame_id": "M01-" + sid + "-CAM03-B03-000038", "seq": 38}
        r = enviar(m4, octetos)
        comprobar("frame_id de otro nodo da 409", r.status_code == 409,
                  str(r.status_code))

        # Gramatica del frame_id.
        m5 = {**meta, "frame_id": "esto-no-vale", "seq": 39}
        r = enviar(m5, octetos)
        comprobar("frame_id mal formado da 422", r.status_code == 422,
                  str(r.status_code))

        # --- telemetria -------------------------------------------------------
        lote = {"schema_version": "1.1", "machine_id": "M01", "node_id": "NH01",
                "boot_id": "B07", "seq": 100, "session_id": sid,
                "sync_uncertainty_ms": 4.0, "clock_epoch_id": "E-x",
                "muestras": [
                    {"sensor_id": "HALL01", "magnitud": "pulsos_ventana", "seq": 100,
                     "capture_mono_us": 5_000_000, "capture_session_us": 5_000_000,
                     "ventana_us": 100_000, "valor": 4.0, "unidad": "count",
                     "calidad": "buena", "codigo_calidad": "ok",
                     "pulsos_ventana": 4, "pulsos_acumulados": 1400,
                     "pulsos_por_vuelta": 8, "edad_ultimo_pulso_ms": 22},
                    {"sensor_id": "HALL01", "magnitud": "reel_rpm", "seq": 100,
                     "capture_mono_us": 5_000_000, "capture_session_us": 5_000_000,
                     "ventana_us": 100_000, "valor": 30.0, "unidad": "rpm",
                     "calidad": "buena", "codigo_calidad": "ok",
                     "calibration_id": "CAL-000-PROVISIONAL"},
                ]}
        r = c.post("/v1/telemetry", json=lote)
        comprobar("lote de telemetria con 201", r.status_code == 201, r.text[:200])
        comprobar("dos magnitudes persistidas", r.json()["persistidas"] == 2,
                  r.text[:120])

        # Reenvio del mismo lote: no duplica.
        r = c.post("/v1/telemetry", json=lote)
        comprobar("reenvio del lote no duplica", r.json()["persistidas"] == 0,
                  r.text[:120])

        # La regla del nulo.
        malo = {**lote, "seq": 101, "muestras": [
            {"sensor_id": "HALL01", "magnitud": "reel_rpm", "seq": 101,
             "capture_mono_us": 1, "capture_session_us": 1, "ventana_us": 1,
             "valor": None, "unidad": "rpm", "calidad": "buena",
             "codigo_calidad": "sin_pulsos"}]}
        r = c.post("/v1/telemetry", json=malo)
        comprobar("valor nulo con calidad 'buena' se rechaza", r.status_code == 422,
                  str(r.status_code))

        nulo_ok = {**lote, "seq": 102, "muestras": [
            {"sensor_id": "HALL01", "magnitud": "reel_rpm", "seq": 102,
             "capture_mono_us": 1, "capture_session_us": 1, "ventana_us": 1,
             "valor": None, "unidad": "rpm", "calidad": "invalida",
             "codigo_calidad": "timeout"}]}
        r = c.post("/v1/telemetry", json=nulo_ok)
        comprobar("valor nulo con calidad 'invalida' se acepta",
                  r.status_code == 201, r.text[:160])

        # Un nodo no puede publicar por un sensor ajeno.
        ajeno = {**lote, "node_id": "NU01", "seq": 103, "muestras": [
            {"sensor_id": "HALL01", "magnitud": "reel_rpm", "seq": 103,
             "capture_mono_us": 1, "capture_session_us": 1, "ventana_us": 1,
             "valor": 1.0, "unidad": "rpm", "calidad": "buena",
             "codigo_calidad": "ok"}]}
        r = c.post("/v1/telemetry", json=ajeno)
        comprobar("un nodo no publica por un sensor ajeno", r.status_code == 409,
                  str(r.status_code))

        # El GPS va conectado a la central: ningun nodo puede publicar por el.
        por_gps = {**lote, "seq": 104, "muestras": [
            {"sensor_id": "GPS01", "magnitud": "ground_speed", "seq": 104,
             "capture_mono_us": 1, "capture_session_us": 1, "ventana_us": 1,
             "valor": 1.0, "unidad": "m/s", "calidad": "buena",
             "codigo_calidad": "ok"}]}
        r = c.post("/v1/telemetry", json=por_gps)
        comprobar("un nodo no publica por el GPS", r.status_code == 409,
                  str(r.status_code))

        # --- GPS --------------------------------------------------------------
        # Tramas como las del VK-162: GGA (satelites, HDOP) y RMC (velocidad).
        # 3,5 nudos = 1,80 m/s. La posicion es inventada y no se guarda.
        L = gps.lector
        gga = nmea("GPGGA,141500.00,0255.123,N,07517.456,W,1,09,0.9,450.0,M,8.0,M,,")
        rmc = nmea("GPRMC,141500.00,A,0255.123,N,07517.456,W,3.500,90.0,221026,,,A")
        L.procesar_linea(gga, ahora_us=6_000_000)
        n = L.procesar_linea(rmc, ahora_us=6_050_000)
        comprobar("una solucion del GPS guarda sus cuatro magnitudes", n == 4, str(n))
        comprobar("el GPS convierte nudos a m/s",
                  L.ultima and abs(L.ultima["ground_speed_mps"] - 1.8006) < 0.001,
                  str(L.ultima))

        malas = L.tramas_malas
        L.procesar_linea(rmc[:-2] + "00", ahora_us=6_100_000)
        comprobar("una trama con la suma mal se descarta y se cuenta",
                  L.tramas_malas == malas + 1, str(L.tramas_malas))

        sin_fix = nmea("GPRMC,141501.00,V,,,,,,,221026,,,N")
        L.procesar_linea(sin_fix, ahora_us=7_050_000)
        comprobar("sin solucion, la velocidad es NULA y no cero",
                  L.ultima["ground_speed_mps"] is None
                  and L.ultima["codigo"] == "sin_fix", str(L.ultima))

        quieto = nmea("GPRMC,141506.00,A,0255.123,N,07517.456,W,0.150,,221026,,,A")
        for k in range(4):
            L.procesar_linea(quieto, ahora_us=12_050_000 + k * 1_000_000)
        comprobar("parada: la filtrada vale 0 con codigo 'reposo'",
                  L.ultima["ground_speed_filtrada_mps"] == 0.0
                  and L.ultima["codigo"] == "reposo", str(L.ultima))

        L.procesar_linea(rmc, ahora_us=16_050_000)
        em = fusion.calcular_estado()
        comprobar("la fusion toma la velocidad del GPS",
                  em.get("ground_speed_mps") is not None
                  and em.get("ground_speed_edad_ms") is not None, str(em)[:200])
        comprobar("sin radio del molinete medido, el reel index es nulo",
                  em.get("reel_index") is None and em.get("ri_estado") == "sin_calibrar",
                  str(em.get("ri_estado")))

        s = c.get("/api/status").json()
        comprobar("el estado incluye el GPS",
                  "gps" in s and s["gps"]["soluciones"] >= 7, str(s.get("gps"))[:160])
        comprobar("el GPS no guarda la posicion",
                  "lat" not in json.dumps(s["gps"]), str(s["gps"])[:160])

        # --- eventos ----------------------------------------------------------
        r = c.post("/v1/events", json={"node_id": "CAM02", "tipo": "latido"})
        comprobar("latido aceptado", r.status_code == 201, str(r.status_code))

        # --- bateria ----------------------------------------------------------
        # Cada nodo lleva su propio juego de pilas: el estado viaja colgado del
        # latido, sin peticiones adicionales.
        r = c.post("/v1/events", json={"node_id": "CAM02", "tipo": "latido",
                                       "bateria_mv": 5200, "rssi_dbm": -58,
                                       "heap_libre": 210000, "pendientes_en_sd": 3})
        comprobar("latido con estado de batería", r.status_code == 201,
                  str(r.status_code))

        s = c.get("/api/status").json()
        cam2 = next((n for n in s["nodos"] if n["node_id"] == "CAM02"), None)
        comprobar("la batería llega al estado",
                  cam2 and cam2.get("bateria_mv") == 5200, str(cam2))
        comprobar("la batería se clasifica",
                  cam2 and cam2.get("bateria_estado") == "ok",
                  str(cam2.get("bateria_estado") if cam2 else None))
        comprobar("los pendientes en SD llegan",
                  cam2 and cam2.get("pendientes_sd") == 3, str(cam2))

        # Un paquete agotado tiene que verse como crítico, no como "va bien".
        c.post("/v1/events", json={"node_id": "NH01", "tipo": "latido",
                                   "bateria_mv": 4200})
        s = c.get("/api/status").json()
        nh1 = next((n for n in s["nodos"] if n["node_id"] == "NH01"), None)
        comprobar("un paquete bajo se marca crítico",
                  nh1 and nh1.get("bateria_estado") == "critico",
                  str(nh1.get("bateria_estado") if nh1 else None))

        # Una petición sin batería NO debe borrar la que ya se conocía.
        c.post("/v1/events", json={"node_id": "CAM02", "tipo": "latido"})
        s = c.get("/api/status").json()
        cam2 = next((n for n in s["nodos"] if n["node_id"] == "CAM02"), None)
        comprobar("un latido sin batería no borra la anterior",
                  cam2 and cam2.get("bateria_mv") == 5200, str(cam2))

        # --- HMI ---------------------------------------------------------------
        r = c.get("/api/status")
        comprobar("/api/status responde", r.status_code == 200, str(r.status_code))
        s = r.json()
        comprobar("el estado lista los siete nodos esperados",
                  len(s["nodos"]) + len(s["nodos_ausentes"]) == 7,
                  f"{len(s['nodos'])} vistos + {len(s['nodos_ausentes'])} ausentes")
        comprobar("el motor esta en modo 'sin-modelo'",
                  s["inferencia"]["modelo"] == "sin-modelo", str(s["inferencia"]))

        r = c.get("/api/results/latest")
        comprobar("/api/results/latest responde", r.status_code == 200)
        res = r.json()["resultados"]
        if res:
            comprobar("sin modelo, el porcentaje es NULO y no cero",
                      res[0]["porcentaje"] is None and res[0]["mostrar"] == "sin_modelo",
                      str(res[0]))
        else:
            comprobar("hay al menos un resultado registrado", False,
                      "la cola aun no habia procesado")

        r = c.get(f"/api/frame/{fid}/asociacion")
        comprobar("asociacion imagen-telemetria", r.status_code == 200, r.text[:160])

        r = c.get(f"/api/frame/{fid}/imagen")
        comprobar("el JPEG original se sirve tal cual",
                  r.status_code == 200 and r.content == octetos, str(r.status_code))

        r = c.get("/api/sensores/salud")
        comprobar("salud de sensores por codigo", r.status_code == 200)

        r = c.post("/api/exportar")
        comprobar("exportacion a CSV", r.status_code == 200, r.text[:160])

    # --- reinicios -------------------------------------------------------------
    # Cada arranque es una sesion nueva, tambien si la anterior no guardo ningun
    # frame. Sin camaras no se crea su carpeta y antes el id se repetia (R007).
    with TestClient(app) as c:
        sid2 = c.get("/salud").json()["session_id"]
    with TestClient(app) as c:
        sid3 = c.get("/salud").json()["session_id"]
    comprobar("un reinicio abre una sesion nueva", sid2 != sid, f"{sid} -> {sid2}")
    comprobar("un reinicio sin frames no repite la sesion",
              sid3 not in (sid, sid2), f"{sid2} -> {sid3}")

    print(f"\n{OK} correctas, {FALLO} fallidas")
    if FALLO == 0:
        print("La central de campo se sostiene.")
    return 1 if FALLO else 0


if __name__ == "__main__":
    raise SystemExit(main())
