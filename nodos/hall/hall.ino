/*
 * hall.ino - Firmware de NH01 (molinete).
 *
 *   NH01 -> HALL01 -> pulsos_ventana (count) + reel_rpm (rpm)
 *
 * Hasta oct-2026 el mismo binario servia tambien a NH02, un Hall en la rueda
 * que estimaba la velocidad de avance. Ese nodo se retiro: el agua y el lodo de
 * la rueda no dejaban un montaje fiable, y la velocidad la mide ahora el GPS
 * USB de la central (central/app/gps.py), sin patinaje.
 *
 * POR QUE SE PUBLICAN DOS MAGNITUDES Y NO SOLO LA DERIVADA
 * --------------------------------------------------------
 * Porque si dentro de tres meses se corrige el numero de imanes del molinete,
 * con los pulsos guardados las rpm de toda la campana se recalculan. Sin ellos,
 * hay que repetir la campana. Los pulsos son el dato; las rpm son una
 * interpretacion del dato.
 *
 * POR QUE PCNT Y NO UNA INTERRUPCION
 * ----------------------------------
 * El contador de pulsos del ESP32-S3 cuenta por hardware y filtra glitches mas
 * cortos que un umbral. Con una interrupcion por flanco, el rebote de un Hall
 * mal acondicionado produce cuentas de mas, y a alta velocidad la CPU pasaria
 * mas tiempo atendiendo interrupciones que trabajando.
 */

#include <Arduino.h>
#include <driver/pulse_cnt.h>

#include <ricevi_nodo.h>   // nodos/comun instalada como libreria (ver nodos/README.md)

using ricevi::nodo;
using ricevi::Muestra;

// Señal del HW-477, despues del diodo 1N5819 y con pull-up de 10 k a 3,3 V.
// En la ESP32-C6 el GPIO4 es pin de arranque (MTMS): se usa GPIO10.
#if CONFIG_IDF_TARGET_ESP32C6
#define PIN_HALL 10
#else
#define PIN_HALL 4
#endif

static pcnt_unit_handle_t unidad_ = nullptr;
static pcnt_channel_handle_t canal_ = nullptr;

static uint32_t seqMuestra_ = 0;
static uint32_t seqLote_ = 0;
static int32_t acumulados_ = 0;
static uint64_t ultimoPulsoUs_ = 0;
static uint32_t periodoUltimoUs_ = 0;
static int32_t ultimaCuenta_ = 0;

// Ventana deslizante para la magnitud derivada. Con ventanas de 100 ms y 8
// pulsos/vuelta, un solo pulso ya son 75 rpm y dos son 150: la RPM saltaria
// entre 0, 75 y "fuera de rango" sin pasar nunca por los valores reales.
// Sumando las ultimas ventanas (1 s por defecto) la resolucion baja a 7,5 rpm.
// Los pulsos_ventana se siguen publicando por ventana: el dato crudo no cambia.
static const size_t MAX_DESLIZ = 50;
static int32_t deslizPulsos_[MAX_DESLIZ];
static uint32_t deslizUs_[MAX_DESLIZ];
static size_t deslizPos_ = 0;
static size_t deslizLlenas_ = 0;

static const size_t MAX_LOTE = 16;
static Muestra lote_[MAX_LOTE];
static size_t enLote_ = 0;

// Buffers para las cadenas que apuntan los Muestra: los punteros del struct
// tienen que seguir vivos hasta que se serialice el lote.
static char sensorId_[12] = "HALL01";
static char calibId_[32] = "";

/* ------------------------------------------------------------------ */

// Cada llamada del contador se comprueba: si la placa rechaza la configuracion,
// el nodo seguiria enviando "0 pulsos" para siempre y parecería un sensor sin
// iman. Asi queda escrito en el monitor serie y en un evento.
static bool pcntOk(esp_err_t e, const char* paso) {
  if (e == ESP_OK) return true;
  Serial.printf("[hall] ERROR contador de pulsos en %s: %s\n", paso, esp_err_to_name(e));
  nodo.enviarEvento("pcnt_error", String(paso) + ": " + esp_err_to_name(e));
  return false;
}

static void iniciarPcnt(int filtroNs) {
  pcnt_unit_config_t cfgU = {.low_limit = -1, .high_limit = 20000};
  if (!pcntOk(pcnt_new_unit(&cfgU, &unidad_), "new_unit")) return;

  pcnt_glitch_filter_config_t filtro = {.max_glitch_ns = (uint32_t)filtroNs};
  pcntOk(pcnt_unit_set_glitch_filter(unidad_, &filtro), "glitch_filter");

  pcnt_chan_config_t cfgC = {.edge_gpio_num = PIN_HALL, .level_gpio_num = -1};
  if (!pcntOk(pcnt_new_channel(unidad_, &cfgC, &canal_), "new_channel")) return;

  // SOLO flanco de subida. Contar los dos flancos y seguir usando una
  // calibracion de un solo flanco duplicaria el resultado, y el error seria
  // exactamente un factor dos: dificil de ver en una grafica.
  pcntOk(pcnt_channel_set_edge_action(canal_, PCNT_CHANNEL_EDGE_ACTION_INCREASE,
                                      PCNT_CHANNEL_EDGE_ACTION_HOLD), "edge_action");
  pcntOk(pcnt_channel_set_level_action(canal_, PCNT_CHANNEL_LEVEL_ACTION_KEEP,
                                       PCNT_CHANNEL_LEVEL_ACTION_KEEP), "level_action");
  pcntOk(pcnt_unit_enable(unidad_), "enable");
  pcntOk(pcnt_unit_clear_count(unidad_), "clear");
  pcntOk(pcnt_unit_start(unidad_), "start");
  Serial.printf("[hall] contador de pulsos listo en GPIO%d\n", PIN_HALL);
}

static void anadir(const char* magnitud, const char* unidad, bool tiene,
                   float valor, const char* codigo, uint64_t capturaUs,
                   uint32_t ventanaUs, int32_t pulsos, int32_t edadMs) {
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
  m.unidad = unidad;
  m.codigoCalidad = codigo;
  // La calidad se deriva del codigo, no se decide aparte: asi no pueden
  // contradecirse.
  m.calidad = (!strcmp(codigo, "ok")) ? "buena"
              : (!strcmp(codigo, "sin_pulsos")) ? "dudosa"
                                                : "invalida";
  m.calibrationId = calibId_[0] ? calibId_ : nullptr;
  m.pulsosVentana = pulsos;
  m.pulsosAcumulados = acumulados_;
  m.pulsosPorVuelta = nodo.plan()["pulsos_por_vuelta"] | 8;
  m.edadUltimoPulsoMs = edadMs;
  m.periodoUltimoUs = periodoUltimoUs_ > 0 ? (int32_t)periodoUltimoUs_ : -1;
}

/* ------------------------------------------------------------------ */

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n[hall] RiceVi Hall " RICEVI_FIRMWARE_VERSION);

  pinMode(PIN_HALL, INPUT_PULLUP);
  nodo.comenzar("sensor", "hall");

  // Que sensor cuelga de este nodo lo dice el plan, no el binario.
  const char* s = nodo.plan()["sensores"][0] | "HALL01";
  strncpy(sensorId_, s, sizeof(sensorId_) - 1);

  const char* cid = nodo.plan()["calibration_id"] | "";
  strncpy(calibId_, cid, sizeof(calibId_) - 1);

  iniciarPcnt(nodo.plan()["filtro_pcnt_ns"] | 1000);
  Serial.printf("[hall] %s, %s, %d pulsos/vuelta\n", nodo.nodeId().c_str(),
                sensorId_, (int)(nodo.plan()["pulsos_por_vuelta"] | 8));
}

void loop() {
  nodo.atender();

  const uint32_t ventanaMs = nodo.plan()["ventana_ms"] | 100;
  const size_t porLote = min<size_t>(nodo.plan()["muestras_por_lote"] | 10, MAX_LOTE);
  const uint32_t t0 = millis();

  delay(ventanaMs);

  // --- cerrar la ventana ------------------------------------------------
  int cuenta = 0;
  pcnt_unit_get_count(unidad_, &cuenta);
  pcnt_unit_clear_count(unidad_);

  const uint64_t capturaUs = ricevi::monoUs();
  const uint32_t ventanaUs = (millis() - t0) * 1000;
  const int32_t pulsos = cuenta;
  acumulados_ += pulsos;
  seqMuestra_++;

  if (pulsos > 0) {
    if (ultimoPulsoUs_ > 0)
      periodoUltimoUs_ = (uint32_t)((capturaUs - ultimoPulsoUs_) / pulsos);
    ultimoPulsoUs_ = capturaUs;
  }
  const int32_t edadMs =
      ultimoPulsoUs_ ? (int32_t)((capturaUs - ultimoPulsoUs_) / 1000) : -1;

  // --- magnitud cruda ----------------------------------------------------
  anadir("pulsos_ventana", "count", true, (float)pulsos, "ok",
         capturaUs, ventanaUs, pulsos, edadMs);

  // --- magnitud derivada -------------------------------------------------
  const int ppv = nodo.plan()["pulsos_por_vuelta"] | 8;

  const uint32_t derivadaMs = nodo.plan()["ventana_derivada_ms"] | 1000;
  const size_t nDesliz = constrain(derivadaMs / max<uint32_t>(ventanaMs, 1), 1u, MAX_DESLIZ);
  deslizPulsos_[deslizPos_] = pulsos;
  deslizUs_[deslizPos_] = ventanaUs;
  deslizPos_ = (deslizPos_ + 1) % MAX_DESLIZ;
  if (deslizLlenas_ < MAX_DESLIZ) deslizLlenas_++;
  int32_t sumPulsos = 0;
  uint64_t sumUs = 0;
  for (size_t k = 0; k < min(nDesliz, deslizLlenas_); k++) {
    const size_t i = (deslizPos_ + MAX_DESLIZ - 1 - k) % MAX_DESLIZ;
    sumPulsos += deslizPulsos_[i];
    sumUs += deslizUs_[i];
  }
  const float dt = sumUs / 1e6f;

  // Vueltas por segundo. Con pulsos en la ventana deslizante, su media; pero
  // nunca mas que 1/(P*t), siendo t el tiempo desde el ultimo pulso: si el
  // siguiente pulso no ha llegado, la maquina no puede ir mas rapido que eso.
  // Asi, al frenar, el valor baja de forma continua en vez de quedarse en la
  // ultima media, y pasado `parada_ms` sin pulsos se publica un 0.
  // El 0 es una parada medida (velocidad por debajo de 1 pulso cada
  // parada_ms), no un hueco: el equipo quiere ver la maquina detenerse. Un
  // sensor desconectado tambien daria 0; eso se vigila con el nivel del pin y
  // los eventos, no ocultando la medida.
  const uint32_t paradaMs = nodo.plan()["parada_ms"] | 3000;
  float vps = 0.0f;
  if (ultimoPulsoUs_ > 0 && edadMs >= 0 && (uint32_t)edadMs <= paradaMs) {
    const float cota = edadMs > 0 ? 1000.0f / (ppv * (float)edadMs) : INFINITY;
    const float media = sumPulsos > 0 ? sumPulsos / (ppv * dt) : 0.0f;
    vps = sumPulsos > 0 ? min(media, cota) : cota;
  }

  const float rpm = 60.0f * vps;                         // RPM = 60N / (P*dt)
  anadir("reel_rpm", "rpm", rpm <= 120.0f, rpm,
         rpm <= 120.0f ? "ok" : "fuera_rango", capturaUs, ventanaUs, pulsos, edadMs);

  // --- enviar el lote -----------------------------------------------------
  // Por lotes y no una a una: a 10 Hz seria una peticion cada 100 ms por nodo,
  // unas veintiseis por segundo entre los tres sensores, sobre el radio que las
  // camaras necesitan. Cada muestra lleva su propio capture_session_us, asi que el
  // agrupamiento retrasa la ENTREGA, no degrada la MEDIDA.
  if (enLote_ >= porLote) {
    seqLote_++;
    int c = nodo.enviarLote(lote_, enLote_, seqLote_);
    // Diagnostico en el monitor serie: pulsos contados desde el arranque y
    // respuesta de la central a este lote. Si al pasar el iman "pulsos" no
    // sube, el problema esta en el cableado o el sensor, no en la red.
    Serial.printf("[hall] lote %u: pulsos acumulados=%ld, nivel=%d, http=%d\n",
                  (unsigned)seqLote_, (long)acumulados_, digitalRead(PIN_HALL), c);
    if (c != 201) {
      // El lote fallido se DESCARTA, no se acumula. Acumular haria crecer la
      // memoria sin limite durante un corte largo, y la telemetria vieja no
      // sirve para diagnosticar: lo que importa es lo que pasa ahora.
      Serial.printf("[hall] lote rechazado (%d), se descarta\n", c);
    }
    enLote_ = 0;
    nodo.led(0, 24, 0);
  }
}
