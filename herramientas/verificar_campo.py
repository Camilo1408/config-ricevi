"""
verificar_campo.py - La comprobacion que se hace ANTES de arrancar el motor.

    python herramientas/verificar_campo.py
    python herramientas/verificar_campo.py --central 192.168.40.2

QUE COMPRUEBA, Y EN ESE ORDEN A PROPOSITO
-----------------------------------------
Cada comprobacion da por hecho lo que confirmo la anterior, de modo que
**la primera que falla dice donde esta el problema**:

  1. El censo es coherente
  2. Hay tokens para los ocho nodos
  3. La central responde
  4. La central no tiene avisos bloqueantes
  5. Los ocho nodos estan en linea
  6. Cada nodo tiene reloj sincronizado
  7. Las camaras estan produciendo frames
  8. Los sensores estan produciendo muestras validas
  9. Queda disco para la jornada
 10. La temperatura esta en rango
 11. Las calibraciones estan medidas

Las diez primeras son BLOQUEANTES: si alguna falla, no se sale a campo. La
ultima es un aviso: se puede capturar dataset con calibraciones provisionales,
pero las magnitudes derivadas no se podran publicar.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from config import censo  # noqa: E402

try:
    import httpx
except ImportError:
    print("Falta httpx.  pip install httpx")
    raise SystemExit(1)

OK = FALLO = AVISO = 0


def bien(t: str, d: str = "") -> None:
    global OK
    OK += 1
    print(f"  OK     {t}" + (f"   {d}" if d else ""))


def mal(t: str, d: str = "") -> None:
    global FALLO
    FALLO += 1
    print(f"  FALLO  {t}" + (f"   {d}" if d else ""))


def aviso(t: str, d: str = "") -> None:
    global AVISO
    AVISO += 1
    print(f"  aviso  {t}" + (f"   {d}" if d else ""))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--central", default=os.getenv("RICEVI_CENTRAL", "192.168.40.2"))
    ap.add_argument("--puerto", type=int, default=8000)
    ap.add_argument("--horas", type=float, default=8.0,
                    help="duracion prevista de la jornada")
    a = ap.parse_args()
    base = f"http://{a.central}:{a.puerto}"

    print(f"Verificando el montaje contra {base}\n")

    # --- 1. censo -----------------------------------------------------------
    v = censo.verificar()
    if v["bloqueantes"]:
        for b in v["bloqueantes"]:
            mal("censo", b)
    else:
        bien("el censo es coherente", f"{len(censo.NODOS)} nodos")

    sin_mac = [n["node_id"] for n in censo.NODOS if not n["mac"]]
    if sin_mac:
        mal("faltan MAC en el censo", ", ".join(sin_mac))
    else:
        bien("las ocho MAC estan anotadas")

    # --- 2. tokens ----------------------------------------------------------
    rt = Path(os.getenv("RICEVI_TOKENS",
                        os.getenv("RICEVI_DIR_DATOS", "/datos/ricevi"))) / "tokens.json"
    if rt.is_file() or (rt := Path(str(rt))).exists():
        t = json.loads(rt.read_text(encoding="utf-8"))["tokens"]
        faltan = [n["node_id"] for n in censo.NODOS if n["node_id"] not in t]
        if faltan:
            mal("faltan tokens", ", ".join(faltan))
        else:
            bien("hay token para los ocho nodos")
    else:
        mal("no hay archivo de tokens", str(rt))

    # --- 3. central ---------------------------------------------------------
    try:
        r = httpx.get(base + "/salud", timeout=5)
        if r.status_code == 200:
            s = r.json()
            bien("la central responde",
                 f"sesion {s['session_id']}, modelo '{s['modelo']}'")
        else:
            mal("la central responde mal", f"HTTP {r.status_code}")
            return resumen()
    except Exception as e:
        mal("no se llega a la central", str(e)[:120])
        print("\n  Comprueba, en este orden: el AP encendido, la Pi encendida, "
              "el aislamiento de clientes DESACTIVADO en el router, y el "
              "servicio ricevi-central arrancado.")
        return resumen()

    try:
        est = httpx.get(base + "/api/status", timeout=10).json()
    except Exception as e:
        mal("no se puede leer el estado", str(e)[:120])
        return resumen()

    # --- 4. nodos en linea ---------------------------------------------------
    ausentes = est.get("nodos_ausentes", [])
    caidos = [n["node_id"] for n in est["nodos"] if not n.get("en_linea")]
    if ausentes:
        mal("nodos que nunca se registraron", ", ".join(ausentes))
    if caidos:
        mal("nodos sin senales recientes", ", ".join(caidos))
    if not ausentes and not caidos:
        bien("los ocho nodos estan en linea")

    # --- 4b. baterias ---------------------------------------------------------
    # Con ocho paquetes 18650 independientes, salir con uno a media carga es
    # perder esa vista a mitad de jornada. Se comprueba ANTES de arrancar.
    b = censo.BATERIA
    sin_dato, bajos, criticos = [], [], []
    for n in est["nodos"]:
        mv = n.get("bateria_mv")
        if mv is None:
            sin_dato.append(n["node_id"])
        elif mv < b["critico_mv"]:
            criticos.append(f"{n['node_id']} {mv/1000:.2f} V")
        elif mv < b["aviso_mv"]:
            bajos.append(f"{n['node_id']} {mv/1000:.2f} V")

    if criticos:
        mal("paquetes de batería agotados", ", ".join(criticos))
    if bajos:
        mal("paquetes por debajo del umbral de aviso", ", ".join(bajos))
    if sin_dato:
        aviso("nodos que no reportan batería", ", ".join(sin_dato))
    if not criticos and not bajos and not sin_dato:
        pk = [f"{n['node_id']} {n['bateria_mv']/1000:.2f} V" for n in est["nodos"]]
        bien("los ocho paquetes con carga suficiente", " · ".join(pk[:3]) + " …")

    # Autonomía estimada del rol más exigente frente a la jornada declarada.
    peor_rol = min(censo.CONSUMO,
                   key=lambda r: censo.autonomia_estimada(r)["horas_estimadas"])
    peor_h = censo.autonomia_estimada(peor_rol)["horas_estimadas"]
    if peor_h < a.horas:
        mal(f"la autonomía estimada no cubre {a.horas:.0f} h",
            f"'{peor_rol}' dura ~{peor_h:.0f} h")
    else:
        bien("autonomía estimada suficiente",
             f"'{peor_rol}' ~{peor_h:.0f} h para una jornada de {a.horas:.0f} h")

    # --- 5. reloj -------------------------------------------------------------
    sin_reloj = [n["node_id"] for n in est["nodos"] if n.get("rtt_us") is None]
    if sin_reloj:
        mal("nodos sin reloj sincronizado", ", ".join(sin_reloj))
    else:
        peor = max((n["rtt_us"] for n in est["nodos"] if n.get("rtt_us")), default=0)
        bien("los ocho tienen reloj", f"peor RTT {peor/1000:.1f} ms")

    # --- 6. produccion --------------------------------------------------------
    camaras = [n for n in est["nodos"] if n["tipo"] == "camara"]
    sin_frames = [n["node_id"] for n in camaras if not n.get("frames")]
    if sin_frames:
        mal("camaras que no han enviado ningun frame", ", ".join(sin_frames))
    else:
        bien("las cuatro camaras estan produciendo",
             f"{est['contadores']['frames']} frames")

    sensores = [n for n in est["nodos"] if n["tipo"] == "sensor"]
    sin_muestras = [n["node_id"] for n in sensores if not n.get("muestras")]
    if sin_muestras:
        mal("nodos de sensor sin muestras", ", ".join(sin_muestras))
    else:
        bien("los cuatro sensores estan produciendo",
             f"{est['contadores']['muestras']} muestras")

    # --- 7. calidad de los sensores -------------------------------------------
    try:
        sal = httpx.get(base + "/api/sensores/salud", timeout=10).json()
        for clave, d in sal.items():
            malas = sum(v for k, v in d["codigos"].items() if k != "ok")
            pct = 100.0 * malas / d["total"] if d["total"] else 0
            peor = max((k for k in d["codigos"] if k != "ok"),
                       key=lambda k: d["codigos"][k], default="")
            if pct > 20:
                mal(f"{clave}: {pct:.0f}% de lecturas malas", f"sobre todo '{peor}'")
            elif pct > 5:
                aviso(f"{clave}: {pct:.0f}% de lecturas malas", f"sobre todo '{peor}'")
            else:
                bien(f"{clave}: {100-pct:.0f}% de lecturas buenas")
    except Exception as e:
        aviso("no se pudo leer la salud de sensores", str(e)[:80])

    # --- 8. disco --------------------------------------------------------------
    salud = est["salud"]
    libre = salud["libre_mb"]
    # A 1 img/s por camara y 150 kB por imagen: ~2,1 GB por hora.
    necesario = int(a.horas * 2100)
    if not salud["aceptando_frames"]:
        mal("la central NO acepta frames", salud.get("motivo_rechazo", ""))
    elif libre < necesario:
        mal(f"disco insuficiente para {a.horas:.0f} h",
            f"{libre} MB libres, hacen falta ~{necesario} MB")
    else:
        bien("hay disco para la jornada",
             f"{libre} MB libres, ~{necesario} MB necesarios")

    # --- 9. temperatura ---------------------------------------------------------
    t = salud.get("temp_c")
    if t is None:
        aviso("no se puede leer la temperatura", "¿no es una Raspberry Pi?")
    elif salud["estado_termico"] != "nominal":
        mal(f"la central ya esta en estado '{salud['estado_termico']}'", f"{t:.1f} C")
    elif t > 60:
        aviso("temperatura alta en reposo", f"{t:.1f} C; bajo carga subira")
    else:
        bien("temperatura en rango", f"{t:.1f} C")

    if salud.get("throttled") not in (None, "0x0"):
        aviso("el PMIC reporta estrangulamiento o bajo voltaje",
              str(salud.get("throttled")))

    # --- 10. calibraciones -------------------------------------------------------
    if v["avisos"]:
        for x in v["avisos"]:
            if "PROVISIONAL" in x or "falta" in x:
                aviso("calibracion", x)
    else:
        bien("todas las calibraciones estan medidas")

    return resumen()


def resumen() -> int:
    print(f"\n{OK} correctas, {AVISO} avisos, {FALLO} fallos")
    if FALLO:
        print("NO SALIR A CAMPO hasta resolver los fallos.")
        return 1
    if AVISO:
        print("Apto para capturar dataset. Revisa los avisos: probablemente haya\n"
              "magnitudes derivadas que todavia no se podran publicar.")
        return 0
    print("Todo en orden.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
