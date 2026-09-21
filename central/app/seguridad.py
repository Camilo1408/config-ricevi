"""
seguridad.py - Un token por nodo. Lo minimo que hace falta y nada mas.

QUE PROTEGE Y QUE NO
--------------------
Protege UNA cosa: que un equipo cualquiera de la red pueda enviar datos
haciendose pasar por un nodo. Sin eso, basta con asociarse al Wi-Fi para
inyectar frames con `node_id` ajeno, y el dataset queda contaminado sin forma
de detectarlo al analizarlo.

NO protege la confidencialidad: el tráfico va en claro dentro de la LAN. Esa es
una decision consciente y esta argumentada en el capitulo 5 de la guia. La red
no sale a Internet, no hay datos personales, y el SHA-256 por frame ya cubre la
integridad de los octetos. Activar TLS cuesta CPU, y la CPU es el recurso
escaso de esta Pi. Si al medir resulta barato, se activa.

POR QUE TOKEN Y NO mTLS
-----------------------
mTLS obligaria a cada ESP32 a guardar y presentar un certificado, con el coste
de memoria y de handshake que eso implica en un microcontrolador. Un token
portador sobre una red cerrada da la garantia que hace falta -- saber quien
habla -- a coste practicamente nulo.
"""

from __future__ import annotations

import hmac
import json
import logging
import secrets
from pathlib import Path

from fastapi import Header, HTTPException

from . import config

log = logging.getLogger("ricevi.seguridad")

_TOKENS: dict[str, str] = {}
_CARGADO = False


def generar_token() -> str:
    """32 octetos de aleatoriedad criptografica en hexadecimal."""
    return secrets.token_hex(32)


def cargar(ruta: Path | None = None) -> int:
    """Lee el archivo de tokens. Devuelve cuantos cargo.

    El archivo lo produce herramientas/generar_tokens.py y vive FUERA del
    repositorio, en el directorio de datos. Si estuviera versionado, el primer
    `git push` publicaria las credenciales de los ocho nodos.
    """
    global _CARGADO
    ruta = ruta or config.RUTA_TOKENS
    _TOKENS.clear()
    if ruta.exists():
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        _TOKENS.update(datos.get("tokens", {}))
    _CARGADO = True
    return len(_TOKENS)


def estado() -> dict:
    return {"exigir_token": config.EXIGIR_TOKEN,
            "tokens_cargados": len(_TOKENS),
            "ruta": str(config.RUTA_TOKENS),
            "archivo_presente": config.RUTA_TOKENS.exists()}


def verificar(node_id: str, cabecera: str | None) -> None:
    """Comprueba que quien dice ser `node_id` presenta el token de `node_id`.

    Lanza 401 si falta y 403 si no coincide. La distincion importa al depurar
    en campo: 401 es "el firmware no manda la cabecera", 403 es "la manda mal".
    """
    if not config.EXIGIR_TOKEN:
        return
    if not _CARGADO:
        cargar()

    esperado = _TOKENS.get(node_id)
    if esperado is None:
        # Un node_id que no esta en el archivo de tokens no esta en el censo, o
        # el archivo esta incompleto. En los dos casos hay que verlo, no
        # dejarlo pasar.
        raise HTTPException(status_code=403,
                            detail=f"nodo '{node_id}' sin token registrado")

    if not cabecera:
        raise HTTPException(status_code=401, detail="falta la cabecera X-Ricevi-Token")

    # compare_digest y no ==: la comparacion normal termina en cuanto encuentra
    # una diferencia, y ese tiempo filtra informacion sobre el token. Aqui es
    # casi irrelevante, pero cuesta lo mismo hacerlo bien.
    if not hmac.compare_digest(cabecera, esperado):
        log.warning("Token incorrecto para %s", node_id)
        raise HTTPException(status_code=403, detail="token incorrecto")


async def dependencia_token(
    x_ricevi_node: str = Header(default=""),
    x_ricevi_token: str = Header(default=""),
) -> str:
    """Dependencia de FastAPI para los endpoints que no llevan node_id en el cuerpo.

    Devuelve el node_id ya verificado.
    """
    if not config.EXIGIR_TOKEN:
        return x_ricevi_node
    if not x_ricevi_node:
        raise HTTPException(status_code=401, detail="falta la cabecera X-Ricevi-Node")
    verificar(x_ricevi_node, x_ricevi_token)
    return x_ricevi_node
