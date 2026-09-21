# Configuración del punto de acceso

La red que une los ocho nodos con la Raspberry Pi. **Es la parte del sistema que
más fallos tontos produce**, y casi todos se evitan con esta lista.

## El número que decide qué equipo sirve

| Elemento | Estaciones Wi-Fi |
|---|---|
| Cuatro cámaras | 4 |
| Cuatro nodos de sensor | 4 |
| `HMI01` | 1 |
| `RPI01`, si no va por cable | 1 |
| **Total** | **9 o 10** |

| Punto de acceso | Clientes que admite | ¿Sirve? |
|---|---|---|
| Router o AP dedicado | Decenas | **Sí, con holgura** |
| Hotspot de Android | Hasta unos 10, según fabricante | Justo, sin margen |
| Hotspot de iPhone | Unos 5, según modelo y operador | **No. No caben ocho nodos** |

**Para campo: router dedicado.** Es la única opción con margen y además deja
libre el Wi-Fi de la Pi.

## Ajustes obligatorios

| Parámetro | Valor | Por qué |
|---|---|---|
| SSID | `RiceVi-M01` | Uno por máquina, para no confundir dos montajes |
| Seguridad | WPA2-PSK | WPA3 puro puede no negociar con el ESP32 |
| **Banda** | **Solo 2,4 GHz** | El ESP32-S3 **no tiene radio de 5 GHz**. En "automático" el nodo puede no ver la red, y el síntoma es idéntico al de una placa averiada |
| **Canal** | **Fijo: 1, 6 u 11** | Un canal automático puede cambiar en marcha y desconectar a los ocho a la vez |
| Ancho de canal | 20 MHz | 40 MHz en 2,4 GHz añade interferencia sin beneficio para este tráfico |
| **Aislamiento de clientes** | **DESACTIVADO** | Si está activo, los nodos ven Internet pero **no ven a la Pi**. Es el fallo número uno y no da ningún mensaje de error |
| *Band steering* | Desactivado | No tiene sentido con una sola banda y confunde a clientes simples |
| 802.11k / v / r | Desactivado | Complejidad de itinerancia que un ESP32 no necesita |
| Portal cautivo | Ninguno | Un ESP32 no puede aceptar términos en una página web |
| Ahorro de energía del AP | Desactivado | Retrasa las tramas justo en el enlace que es el cuello de botella |
| DHCP | Activo, con reservas por MAC | Ver la tabla de abajo |

## Reservas DHCP

Las MAC salen de `config/censo.py`, y se anotan al provisionar cada placa con
`provisionar_nodo.py`.

| Equipo | IP | MAC |
|---|---|---|
| `AP01` | `192.168.40.1` | — |
| `RPI01` | `192.168.40.2` | *(anotar)* |
| `CAM01` | `192.168.40.11` | *(anotar)* |
| `CAM02` | `192.168.40.12` | *(anotar)* |
| `CAM03` | `192.168.40.13` | *(anotar)* |
| `CAM04` | `192.168.40.14` | *(anotar)* |
| `NH01` | `192.168.40.21` | *(anotar)* |
| `NH02` | `192.168.40.22` | *(anotar)* |
| `NU01` | `192.168.40.23` | *(anotar)* |
| `NU02` | `192.168.40.24` | *(anotar)* |
| Diagnóstico | `.40`–`.49` | rango DHCP libre |

**Reserva DHCP y no IP estática en cada equipo.** Con la IP grabada en el nodo,
llevar una placa al taller obliga a reconfigurarla. Con reserva, el nodo pide
dirección como cualquier cliente y en la red de campo siempre recibe la misma.

## Los cinco fallos, en el orden en que hay que descartarlos

**La primera comprobación que falla dice dónde está el problema.**

| # | Comprueba | Si falla |
|---|---|---|
| 1 | El nodo se asocia al SSID | Banda equivocada (¿el AP está en 5 GHz?), contraseña, o fuera de cobertura |
| 2 | El nodo recibe IP por DHCP | Servidor DHCP agotado, o reserva mal escrita |
| 3 | El nodo alcanza `192.168.40.2` | **Aislamiento de clientes activado**, o la Pi caída |
| 4 | El nodo recibe `200` de `/salud` | Cortafuegos en la Pi, o el servicio no arrancado |
| 5 | Sigue conectado **con la máquina en movimiento** | Cobertura. Es el que no se detecta en el taller |

El quinto merece atención aparte: un nodo montado en el extremo del cabezal, con
el chasis metálico entre su antena y la del AP, puede asociarse perfectamente
parado y perder el enlace cada vez que la máquina gira. La prueba es circular
con el sistema en marcha y mirar la tasa de reintentos por nodo, no la señal en
reposo.

## Dónde montar el punto de acceso

> **`RPI01` en cabina, `AP01` fuera y cerca de los nodos, unidos por Ethernet.**

Resuelve la tensión entre "la Pi quiere estar fresca" y "la antena quiere estar
cerca". El AP es pequeño, barato de reemplazar y tolera la intemperie mucho
mejor que una Pi con SSD. La Pi vive en el sitio benigno y el enlace entre
ambos es cable, no radio.

## Plan de contingencia: la Pi como punto de acceso

Si el router falla en campo:

```bash
sudo nmcli device wifi hotspot ifname wlan0 ssid RiceVi-M01 password "<la del censo>"
```

Los nodos la encontrarán por la vía 3 del descubrimiento (la puerta de enlace).
Coste: la Pi pierde su salida a Internet mientras hace de AP, porque solo tiene
un radio. Para capturar dataset eso no importa.
