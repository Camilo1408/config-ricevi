/*
 * hall.ino - Firmware de NH01 (molinete) y NH02 (rueda).
 *
 * EL MISMO BINARIO PARA LOS DOS. Que magnitud derivada publica cada uno lo
 * decide el plan que manda la central, no el codigo:
 *
 *   NH01 -> HALL01 -> pulsos_ventana (count) + reel_rpm (rpm)
 *   NH02 -> HALL02 -> pulsos_ventana (count) + wheel_speed (m/s)
 *
 * POR QUE SE PUBLICAN DOS MAGNITUDES Y NO SOLO LA DERIVADA
 * --------------------------------------------------------
 * Porque si dentro de tres meses se corrige la circunferencia de la rueda, con
 * los pulsos guardados la velocidad de toda la campana se recalcula. Sin ellos,
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

#include "../comun/ricevi_nodo.h"

using ricevi::nodo;
using ricevi::Muestra;

#define PIN_HALL 4              // VERIFICAR con el acondicionamiento real

static pcnt_unit_handle_t unidad_ = nullptr;
static pcnt_channel_handle_t canal_ = nullptr;

static uint32_t seqMuestra_ = 0;
static uint32_t seqLote_ = 0;
static int32_t acumulados_ = 0;
static uint64_t ultimoPulsoUs_ = 0;
static uint32_t periodoUltimoUs_ = 0;
static int32_t ultimaCuenta_ = 0;

static const size_t MAX_LOTE = 16;
static Muestra lote_[MAX_LOTE];
static size_t enLote_ = 0;

// Buffers para las cadenas que apuntan los Muestra: los punteros del struct
// tienen que seguir vivos hasta que se serialice el lote.
static char sensorId_[12] = "HALL01";
static char calibId_[32] = "";
static bool esRueda_ = false;

/* ------------------------------------------------------------------ */

static void iniciarPcnt(int filtroNs) {
  pcnt_unit_config_t cfgU = {.low_limit = -1, .high_limit = 20000};
  pcnt_new_unit(&cfgU, &unidad_);

  pcnt_glitch_filter_config_t filtro = {.max_glitch_ns = (uint32_t)filtroNs};
  pcnt_unit_set_glitch_filter(unidad_, &filtro);

  pcnt_chan_config_t cfgC = {.edge_gpio_num = PIN_HALL, .level_gpio_num = -1};
  pcnt_new_channel(unidad_, &cfgC, &canal_);

  // SOLO flanco de subida. Contar los dos flancos y seguir usando una
  // calibracion de un solo flanco duplicaria el resultado, y el error seria
  // exactamente un factor dos: dificil de ver en una grafica.
  pcnt_channel_set_edge_action(canal_, PCNT_CHANNEL_EDGE_ACTION_INCREASE,
                               PCNT_CHANNEL_EDGE_ACTION_HOLD);
  pcnt_channel_set_level_action(canal_, PCNT_CHANNEL_LEVEL_ACTION_KEEP,
                                PCNT_CHANNEL_LEVEL_ACTION_KEEP);
  pcnt_unit_enable(unidad_);
  pcnt_unit_clear_count(unidad_);
  pcnt_unit_start(unidad_);
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
  esRueda_ = (strcmp(sensorId_, "HALL02") == 0);

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
  const float dt = ventanaUs / 1e6f;
  JsonVariantConst cal = nodo.plan()["calibracion"][sensorId_];

  if (pulsos == 0) {
    // Ventana sin pulsos: puede ser una parada real o el sensor caido. El nodo
    // no puede distinguirlo, asi que NO inventa un cero: lo marca como dudoso
    // con valor nulo y que lo decida el analisis.
    anadir(esRueda_ ? "wheel_speed" : "reel_rpm", esRueda_ ? "m/s" : "rpm",
           false, 0.0f, "sin_pulsos", capturaUs, ventanaUs, pulsos, edadMs);
  } else if (esRueda_) {
    const float circ = cal["circunferencia_rueda_m"] | 0.0f;
    if (circ <= 0.0f) {
      // Sin la constante no hay magnitud derivada. Publicar una velocidad
      // calculada con una circunferencia inventada seria dar por medido algo
      // que no lo esta.
      anadir("wheel_speed", "m/s", false, 0.0f, "sin_calibrar",
             capturaUs, ventanaUs, pulsos, edadMs);
    } else {
      const float v = (pulsos * circ) / (ppv * dt);      // v = N*C / (P*dt)
      anadir("wheel_speed", "m/s", v <= 8.0f, v,
             v <= 8.0f ? "ok" : "fuera_rango", capturaUs, ventanaUs, pulsos, edadMs);
    }
  } else {
    const float rpm = (60.0f * pulsos) / (ppv * dt);     // RPM = 60N / (P*dt)
    anadir("reel_rpm", "rpm", rpm <= 120.0f, rpm,
           rpm <= 120.0f ? "ok" : "fuera_rango", capturaUs, ventanaUs, pulsos, edadMs);
  }

  // --- enviar el lote -----------------------------------------------------
  // Por lotes y no una a una: a 10 Hz seria una peticion cada 100 ms por nodo,
  // cuarenta por segundo entre los cuatro, sobre el mismo radio que las camaras
  // necesitan. Cada muestra lleva su propio capture_session_us, asi que el
  // agrupamiento retrasa la ENTREGA, no degrada la MEDIDA.
  if (enLote_ >= porLote) {
    seqLote_++;
    int c = nodo.enviarLote(lote_, enLote_, seqLote_);
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
