/*
 * ultrasonico.ino - Firmware de NU01 (izquierdo) y NU02 (derecho).
 *
 * EL MISMO BINARIO PARA LOS DOS. El sensor que le toca y su offset llegan en
 * el plan:
 *
 *   NU01 -> US01 -> distance (mm) + header_height (mm)
 *   NU02 -> US02 -> distance (mm) + header_height (mm)
 *
 * EL A02YYUW NO ES UN HC-SR04
 * ---------------------------
 * No tiene TRIG/ECHO: entrega tramas por UART a 9600 bps, por su cuenta, sin
 * que nadie se las pida. Su pin RX selecciona el modo de salida y NO es una
 * entrada de disparo. Intentar "dispararlo" es un error frecuente que produce
 * un sensor que parece averiado.
 *
 * La trama son cuatro octetos:
 *
 *     0xFF   ALTO   BAJO   SUMA
 *
 *     distancia_mm = ALTO * 256 + BAJO
 *     SUMA         = (0xFF + ALTO + BAJO) & 0xFF
 *
 * LA REGLA QUE GOBIERNA ESTE ARCHIVO
 * ----------------------------------
 * Cuando no hay eco valido, el valor es NULO. Nunca cero. Un cero entra en el
 * dataset como una altura de cuchilla de cero milimetros, indistinguible de una
 * medida real, y al entrenar el modelo aprende de el.
 */

#include <Arduino.h>

#include "../comun/ricevi_nodo.h"

using ricevi::nodo;
using ricevi::Muestra;

#define PIN_RX 18          // TX del sensor -> RX del ESP32. VERIFICAR
#define PIN_TX 17          // no se usa para disparar; ver nota de arriba
#define UART_SENSOR Serial1

static uint32_t seqMuestra_ = 0;
static uint32_t seqLote_ = 0;
static int32_t descartadas_ = 0;

static const size_t MAX_LOTE = 16;
static Muestra lote_[MAX_LOTE];
static size_t enLote_ = 0;

static char sensorId_[8] = "US01";
static char calibId_[32] = "";
static int offsetBMm_ = -1;
static int zonaCiegaMm_ = 30;
static int rangoMaxMm_ = 4500;

// Para detectar un eco inestable hace falta recordar la lectura anterior.
static int ultimaMm_ = -1;

/* ------------------------------------------------------------------ */

/* Lee una trama completa y validada. Devuelve la distancia en mm, o:
 *    -1 timeout      no llego nada en el plazo
 *    -2 checksum     llego algo y no cuadra (ruido, cableado, conector) */
static int leerTrama(uint32_t plazoMs) {
  const uint32_t limite = millis() + plazoMs;
  while (millis() < limite) {
    if (UART_SENSOR.available() < 4) { delay(1); continue; }
    if (UART_SENSOR.peek() != 0xFF) { UART_SENSOR.read(); continue; }

    uint8_t b[4];
    UART_SENSOR.readBytes(b, 4);
    const uint8_t suma = (uint8_t)(b[0] + b[1] + b[2]);
    if (suma != b[3]) {
      descartadas_++;
      return -2;
    }
    return (int)b[1] * 256 + (int)b[2];
  }
  return -1;
}

static void anadir(const char* magnitud, bool tiene, float valor,
                   const char* codigo, uint64_t capturaUs, uint32_t ventanaUs,
                   int crudaMm) {
  if (enLote_ >= MAX_LOTE) return;
  Muestra& m = lote_[enLote_++];
  m.sensorId = sensorId_;
  m.magnitud = magnitud;
  m.seq = seqMuestra_;
  m.captureMonoUs = capturaUs;
  m.captureSessionUs = nodo.aSesion(capturaUs);
  m.ventanaUs = ventanaUs;
  m.tieneValor = tiene;
  m.valor = valor;
  m.unidad = "mm";
  m.codigoCalidad = codigo;
  m.calidad = (!strcmp(codigo, "ok"))          ? "buena"
              : (!strcmp(codigo, "eco_dudoso") ||
                 !strcmp(codigo, "saturado"))  ? "dudosa"
                                               : "invalida";
  m.calibrationId = calibId_[0] ? calibId_ : nullptr;
  m.distanciaCrudaMm = crudaMm;
  m.offsetBMm = offsetBMm_;
  m.tramasDescartadas = descartadas_;
}

/* ------------------------------------------------------------------ */

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n[us] RiceVi ultrasonico " RICEVI_FIRMWARE_VERSION);

  nodo.comenzar("sensor", "ultrasonico");

  const char* s = nodo.plan()["sensores"][0] | "US01";
  strncpy(sensorId_, s, sizeof(sensorId_) - 1);
  const char* cid = nodo.plan()["calibration_id"] | "";
  strncpy(calibId_, cid, sizeof(calibId_) - 1);

  JsonVariantConst cal = nodo.plan()["calibracion"][sensorId_];
  // -1 y no 0: "no hay offset" es distinto de "el offset es cero".
  offsetBMm_ = cal["offset_b_mm"] | -1;
  zonaCiegaMm_ = cal["zona_ciega_mm"] | 30;
  rangoMaxMm_ = cal["rango_max_mm"] | 4500;

  UART_SENSOR.begin(nodo.plan()["uart_baudios"] | 9600, SERIAL_8N1, PIN_RX, PIN_TX);
  Serial.printf("[us] %s, %s, offset_b=%d mm, rango %d-%d mm\n",
                nodo.nodeId().c_str(), sensorId_, offsetBMm_,
                zonaCiegaMm_, rangoMaxMm_);
  if (offsetBMm_ < 0)
    nodo.enviarEvento("sin_calibrar",
                      String(sensorId_) + " sin offset_b_mm: no habra altura");
}

void loop() {
  nodo.atender();

  const float hz = nodo.plan()["muestreo_hz"] | 8.0f;
  const uint32_t periodoMs = (uint32_t)(1000.0f / max(0.5f, hz));
  const size_t porLote = min<size_t>(nodo.plan()["muestras_por_lote"] | 8, MAX_LOTE);
  const uint32_t t0 = millis();

  const int mm = leerTrama(periodoMs);
  const uint64_t capturaUs = ricevi::monoUs();
  const uint32_t ventanaUs = (millis() - t0) * 1000;
  seqMuestra_++;

  // --- magnitud cruda -----------------------------------------------------
  const char* codigo;
  bool valida = false;

  if (mm == -1) {
    codigo = "timeout";
  } else if (mm == -2) {
    codigo = "checksum";
  } else if (mm < zonaCiegaMm_ || mm > rangoMaxMm_) {
    codigo = "fuera_rango";
  } else if (ultimaMm_ >= 0 && abs(mm - ultimaMm_) > 500) {
    // Salto de mas de medio metro entre lecturas consecutivas a 8 Hz. Es
    // fisicamente posible sobre terreno irregular, pero tambien es la firma de
    // un eco que rebota en vegetacion en vez de en el suelo. Se acepta el
    // valor y se marca DUDOSO: que lo decida el analisis, no el firmware.
    codigo = "eco_dudoso";
    valida = true;
  } else {
    codigo = "ok";
    valida = true;
  }

  anadir("distance", valida, (float)mm, codigo, capturaUs, ventanaUs,
         mm >= 0 ? mm : -1);
  if (mm >= 0) ultimaMm_ = mm;

  // --- magnitud derivada ---------------------------------------------------
  if (!valida) {
    // Sin distancia valida no hay altura. NULO, no cero.
    anadir("header_height", false, 0.0f, codigo, capturaUs, ventanaUs,
           mm >= 0 ? mm : -1);
  } else if (offsetBMm_ < 0) {
    // Sin el offset medido no se puede derivar la altura. Publicar
    // "distancia - 200" con un 200 inventado seria dar por medido el montaje.
    anadir("header_height", false, 0.0f, "sin_calibrar", capturaUs, ventanaUs, mm);
  } else {
    const float h = (float)(mm - offsetBMm_);
    // Una altura negativa significa que el eco vino de algo mas cerca que la
    // cuchilla: no es una altura, es otra cosa.
    anadir("header_height", h >= 0.0f, h,
           h >= 0.0f ? codigo : "fuera_rango", capturaUs, ventanaUs, mm);
  }

  // --- enviar el lote ------------------------------------------------------
  if (enLote_ >= porLote) {
    seqLote_++;
    int c = nodo.enviarLote(lote_, enLote_, seqLote_);
    if (c != 201)
      Serial.printf("[us] lote rechazado (%d), se descarta\n", c);
    enLote_ = 0;
    nodo.led(0, 24, 0);

    // Si la tasa de tramas invalidas se dispara, hay un problema fisico:
    // cableado, conector flojo o ruido electrico. Merece un evento propio,
    // porque la telemetria sola no distingue "sensor roto" de "eco malo".
    if (descartadas_ > 50) {
      nodo.enviarEvento("trama_invalida",
                        String(descartadas_) + " tramas con checksum malo");
      descartadas_ = 0;
    }
  }

  const uint32_t gastado = millis() - t0;
  if (periodoMs > gastado) delay(periodoMs - gastado);
}
