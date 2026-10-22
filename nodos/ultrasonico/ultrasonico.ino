/*
 * ultrasonico.ino - Firmware de NU01 (izquierdo) y NU02 (derecho).
 *
 * EL MISMO BINARIO PARA LOS DOS. El sensor que le toca y su offset llegan en
 * el plan:
 *
 *   NU01 -> US01 -> distance (mm) + header_height (mm)
 *   NU02 -> US02 -> distance (mm) + header_height (mm)
 *
 * EL SENSOR: RCWL-1655 EN MODO GPIO (TRIG / ECHO)
 * -----------------------------------------------
 * Sustituye al A02YYUW del diseno v1.1. El RCWL-1655 elige su interfaz con la
 * resistencia R7 (sin R7 = GPIO, como un HC-SR04) y viene asi de fabrica. Cada
 * medida es:
 *
 *   1. pulso de 20 us en TRIG
 *   2. el sensor emite y pone ECHO en alto mientras espera el rebote
 *   3. distancia = duracion_del_alto * velocidad_del_sonido / 2
 *
 * La velocidad del sonido viene en el plan (velocidad_sonido_mps) y viaja con
 * cada muestra a traves del calibration_id: si la temperatura real del campo
 * difiere, la distancia se puede recalcular despues.
 *
 * Alimentado a 3,3 V, ECHO sale a 3,3 V y entra directo al GPIO.
 *
 * LA REGLA QUE GOBIERNA ESTE ARCHIVO
 * ----------------------------------
 * Cuando no hay eco valido, el valor es NULO. Nunca cero. Un cero entra en el
 * dataset como una altura de cuchilla de cero milimetros, indistinguible de una
 * medida real, y al entrenar el modelo aprende de el.
 */

#include <Arduino.h>

#include <ricevi_nodo.h>   // nodos/comun instalada como libreria (ver nodos/README.md)

using ricevi::nodo;
using ricevi::Muestra;

// ESP32-C6 DevKitC (nodos de sensor): GPIO11 y GPIO10 son libres y no son pines
// de arranque. En la S3 se conservan los del diseno original.
#if CONFIG_IDF_TARGET_ESP32C6
#define PIN_TRIG 11
#define PIN_ECHO 10
#else
#define PIN_TRIG 17
#define PIN_ECHO 18
#endif

static uint32_t seqMuestra_ = 0;
static uint32_t seqLote_ = 0;
static int32_t sinEco_ = 0;          // medidas seguidas sin eco

static const size_t MAX_LOTE = 16;
static Muestra lote_[MAX_LOTE];
static size_t enLote_ = 0;

static char sensorId_[8] = "US01";
static char calibId_[32] = "";
static int offsetBMm_ = -1;
static int zonaCiegaMm_ = 30;
static int rangoMaxMm_ = 4500;
static float vSonido_ = 343.0f;      // m/s; el plan lo sobrescribe
static uint32_t timeoutUs_ = 30000;  // ~5 m ida y vuelta

// Para detectar un eco inestable hace falta recordar la lectura anterior.
static int ultimaMm_ = -1;

/* ------------------------------------------------------------------ */

/* Dispara una medida. Devuelve la distancia en mm, o -1 si no hubo eco dentro
 * del plazo. `capturaUs` es el instante en que el sonido toco el objeto: el
 * disparo mas la mitad del vuelo. */
static int medir(uint64_t& capturaUs) {
  digitalWrite(PIN_TRIG, LOW);
  delayMicroseconds(4);
  digitalWrite(PIN_TRIG, HIGH);
  delayMicroseconds(20);
  digitalWrite(PIN_TRIG, LOW);
  const uint64_t disparoUs = ricevi::monoUs();

  const unsigned long alto = pulseIn(PIN_ECHO, HIGH, timeoutUs_);
  if (alto == 0) {
    capturaUs = disparoUs;
    return -1;
  }
  capturaUs = disparoUs + alto / 2;
  // mm = us * (m/s) / 1000 / 2
  return (int)(alto * vSonido_ / 2000.0f + 0.5f);
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
}

/* ------------------------------------------------------------------ */

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n[us] RiceVi ultrasonico " RICEVI_FIRMWARE_VERSION);

  pinMode(PIN_TRIG, OUTPUT);
  digitalWrite(PIN_TRIG, LOW);
  pinMode(PIN_ECHO, INPUT);

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
  vSonido_ = nodo.plan()["velocidad_sonido_mps"] | 343.0f;
  timeoutUs_ = nodo.plan()["timeout_eco_us"] | 30000;

  Serial.printf("[us] %s, %s, offset_b=%d mm, rango %d-%d mm, v=%.0f m/s\n",
                nodo.nodeId().c_str(), sensorId_, offsetBMm_,
                zonaCiegaMm_, rangoMaxMm_, vSonido_);
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

  uint64_t capturaUs = 0;
  const int mm = medir(capturaUs);
  const uint32_t ventanaUs = (millis() - t0) * 1000;
  seqMuestra_++;

  // --- magnitud cruda -----------------------------------------------------
  const char* codigo;
  bool valida = false;

  if (mm < 0) {
    codigo = "timeout";
    sinEco_++;
  } else if (mm < zonaCiegaMm_ || mm > rangoMaxMm_) {
    codigo = "fuera_rango";
    sinEco_ = 0;
  } else if (ultimaMm_ >= 0 && abs(mm - ultimaMm_) > 500) {
    // Salto de mas de medio metro entre lecturas consecutivas a 8 Hz. Es
    // fisicamente posible sobre terreno irregular, pero tambien es la firma de
    // un eco que rebota en vegetacion en vez de en el suelo. Se acepta el
    // valor y se marca DUDOSO: que lo decida el analisis, no el firmware.
    codigo = "eco_dudoso";
    valida = true;
    sinEco_ = 0;
  } else {
    codigo = "ok";
    valida = true;
    sinEco_ = 0;
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

    // Muchas medidas seguidas sin eco son un problema fisico: sonda
    // desconectada, cable de TRIG/ECHO suelto o nada al alcance. Merece un
    // evento propio, porque la telemetria sola no distingue "sensor roto" de
    // "no hay suelo debajo".
    if (sinEco_ == 50)
      nodo.enviarEvento("sin_eco", String(sensorId_) + ": 50 medidas seguidas sin eco");
  }

  // El RCWL-1655 necesita unos 60 ms entre disparos para que el eco anterior se
  // extinga; a 8 Hz hay 125 ms.
  const uint32_t gastado = millis() - t0;
  if (periodoMs > gastado) delay(periodoMs - gastado);
}
