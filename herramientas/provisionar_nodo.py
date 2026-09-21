"""
provisionar_nodo.py - Graba la identidad de un nodo en su NVS, por consola serie.

    python herramientas/provisionar_nodo.py --node-id CAM01 --puerto COM7
    python herramientas/provisionar_nodo.py --node-id NU02 --puerto /dev/ttyACM0
    python herramientas/provisionar_nodo.py --leer-mac --puerto COM7

POR QUE UNA PROVISION Y NO UN BINARIO POR NODO
----------------------------------------------
Las cuatro camaras corren el MISMO binario. Si cada una tuviera el suyo, copiar
el equivocado convertiria a CAM03 en CAM02, y el sintoma seria un 409 en la
central que nadie sabria explicar -- o peor, imagenes atribuidas a la vista
equivocada si el conflicto no saltara.

Con la identidad en NVS, el binario es intercambiable y la placa es la que
lleva su nombre.

EL PASO QUE NO HAY QUE SALTARSE
-------------------------------
Al terminar, este script imprime la MAC. Hay que copiarla a `config/censo.py`:
sin ella no se puede crear la reserva DHCP, y sin reserva el nodo recibira una
IP distinta cada vez y los registros de red seran ilegibles.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from config import censo  # noqa: E402

try:
    import serial
except ImportError:
    print("Falta pyserial.  pip install pyserial")
    raise SystemExit(1)


def ruta_tokens() -> Path:
    t = os.getenv("RICEVI_TOKENS")
    if t:
        return Path(t)
    return Path(os.getenv("RICEVI_DIR_DATOS", "/datos/ricevi")) / "tokens.json"


def orden(s: serial.Serial, linea: str, espera: float = 0.6) -> str:
    """Envia una orden a la consola del nodo y devuelve lo que conteste."""
    s.reset_input_buffer()
    s.write((linea + "\n").encode())
    s.flush()
    time.sleep(espera)
    return s.read_all().decode(errors="replace")


def main() -> int:
    ap = argparse.ArgumentParser(description="Provision de un nodo RiceVi")
    ap.add_argument("--puerto", required=True, help="COM7, /dev/ttyACM0...")
    ap.add_argument("--node-id", help="CAM01..NU02")
    ap.add_argument("--baudios", type=int, default=115200)
    ap.add_argument("--leer-mac", action="store_true",
                    help="solo lee la MAC y sale")
    ap.add_argument("--ssid", help="sobrescribe el SSID del censo")
    ap.add_argument("--pass", dest="clave", help="contrasena del Wi-Fi")
    ap.add_argument("--central-ip", help="IP de la central")
    a = ap.parse_args()

    if not a.leer_mac and not a.node_id:
        print("Hace falta --node-id (o --leer-mac)")
        return 1

    if a.node_id:
        try:
            ficha = censo.ficha(a.node_id)
        except KeyError:
            print(f"'{a.node_id}' no esta en el censo. "
                  f"Anadelo a config/censo.py primero.")
            return 1

        rt = ruta_tokens()
        if not rt.exists():
            print(f"No hay tokens en {rt}. Ejecuta generar_tokens.py primero.")
            return 1
        tokens = json.loads(rt.read_text(encoding="utf-8"))["tokens"]
        if a.node_id not in tokens:
            print(f"No hay token para {a.node_id}. Ejecuta generar_tokens.py.")
            return 1
        token = tokens[a.node_id]

    print(f"Abriendo {a.puerto}...")
    with serial.Serial(a.puerto, a.baudios, timeout=1) as s:
        time.sleep(2.0)     # el ESP32 se reinicia al abrir el puerto
        s.read_all()

        salida = orden(s, "mac")
        m = re.search(r"([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})", salida)
        mac = m.group(1).upper() if m else ""
        if mac:
            print(f"MAC: {mac}")
        else:
            print("No se pudo leer la MAC. ¿La consola de provision esta activa?")
            print("Salida cruda:\n" + salida[:400])

        if a.leer_mac:
            return 0 if mac else 1

        ssid = a.ssid or os.getenv("RICEVI_SSID", "RiceVi-M01")
        clave = a.clave or os.getenv("RICEVI_WIFI_PASS", "")
        ip = a.central_ip or "192.168.40.2"

        if not clave:
            print("AVISO: sin --pass, el nodo conservara la contrasena que tenga.")

        pasos = [("node_id", a.node_id), ("token", token),
                 ("wifi_ssid", ssid), ("central_ip", ip)]
        if clave:
            pasos.insert(3, ("wifi_pass", clave))

        for clave_nvs, valor in pasos:
            r = orden(s, f"set {clave_nvs} {valor}")
            ok = "OK" in r.upper()
            mostrado = valor if clave_nvs not in ("token", "wifi_pass") else "********"
            print(f"  {'OK   ' if ok else 'FALLO'} {clave_nvs} = {mostrado}")
            if not ok:
                print("    respuesta: " + r.strip()[:200])
                return 1

        print(orden(s, "verificar", 1.0).strip())
        orden(s, "reiniciar", 0.2)

    print()
    print(f"{a.node_id} provisionado.")
    print(f"  Posicion : {ficha['posicion']}")
    print(f"  Etiqueta : {ficha['etiqueta']}   <- PEGALA EN LA CAJA AHORA")
    print(f"  IP        : {ficha['ip']}  (crea la reserva DHCP con la MAC)")
    if mac and not ficha["mac"]:
        print()
        print("  FALTA UN PASO: copia esta linea a config/censo.py")
        print(f'     "mac": "{mac}",   # en la ficha de {a.node_id}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
