/*
 * ricevi_nodo.h - El firmware compartido por los ocho nodos.
 *
 * Es la traduccion a C++ de lo que en el banco de pruebas era `comun.py`: la
 * misma logica de registro, cuatro tiempos, turno y reintento, contra los
 * mismos endpoints y el mismo contrato.
 *
 * LO QUE CADA ROL APORTA POR SU CUENTA
 * ------------------------------------
 *   camara.ino        capturar un JPEG y llamar a subirFrame()
 *   hall.ino          contar pulsos y llamar a enviarLote()
 *   ultrasonico.ino   leer la UART y llamar a enviarLote()
 *
 * Todo lo demas -- red, identidad, reloj, turnos, reintentos, LED -- vive aqui
 * y no se duplica en ningun sitio.
 */

#pragma once

#include <Arduino.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <WiFi.h>

#include "ricevi_config.h"

namespace ricevi {

/* ------------------------------------------------------------------ */
/* Estado del nodo                                                     */
/* ------------------------------------------------------------------ */

enum class Estado : uint8_t {
  SinIdentidad,   // falta node_id o token en NVS
  SinRed,         // no asociado al AP
  SinCentral,     // asociado, pero la central no responde
  Registrando,
  Sincronizando,
  Operando,
  Reenviando      // vaciando pendientes de la SD
};

/* Una muestra de sensor, con los campos del contrato 1.1.
 *
 * `valor` va acompanado de `tieneValor`: en C++ no hay un `None` natural, y la
 * regla del proyecto es que cuando no hay medida el valor es NULO, nunca cero.
 * Confundirlos meteria en el dataset una altura de cuchilla de cero milimetros
 * indistinguible de una medida real. */
struct Muestra {
  const char* sensorId = "";
  const char* magnitud = "";
  uint32_t    seq = 0;
  uint64_t    captureMonoUs = 0;
  uint64_t    captureSessionUs = 0;
  uint32_t    ventanaUs = 0;
  bool        tieneValor = false;
  float       valor = 0.0f;
  const char* unidad = "";
  const char* calidad = "buena";        // buena | dudosa | invalida
  const char* codigoCalidad = "ok";
  const char* calibrationId = nullptr;

  // Crudos del Hall. -1 = no aplica.
  int32_t pulsosVentana = -1;
  int32_t pulsosAcumulados = -1;
  int32_t pulsosPorVuelta = -1;
  int32_t edadUltimoPulsoMs = -1;
  int32_t periodoUltimoUs = -1;

  // Crudos del ultrasonico. -1 = no aplica.
  int32_t distanciaCrudaMm = -1;
  int32_t offsetBMm = -1;
  int32_t tramasDescartadas = -1;
};

/* ------------------------------------------------------------------ */
/* El nodo                                                             */
/* ------------------------------------------------------------------ */

class Nodo {
 public:
  /* Lee la identidad de NVS, conecta, descubre la central y se registra.
   * Bloquea hasta conseguirlo: en campo, un nodo que se rinde es un nodo que
   * hay que ir a reiniciar subido a una cosechadora. */
  bool comenzar(const char* tipo, const char* rol);

  /* Llamar en cada vuelta de loop(). Mantiene el reloj, el latido y la
   * reconexion. No bloquea mas de unos milisegundos en el caso normal. */
  void atender();

  /* Consola de provision por el puerto serie (115200). La usa
   * herramientas/provisionar_nodo.py. Ordenes, una por linea:
   *   mac                    -> "MAC xx:xx:xx:xx:xx:xx" (la de la estacion Wi-Fi)
   *   set <clave> <valor>    -> "OK <clave>"; claves: node_id, token,
   *                             wifi_ssid, wifi_pass, central_ip
   *   verificar              -> lo grabado (token y clave enmascarados)
   *   borrar                 -> borra la identidad de la NVS
   *   reiniciar              -> "OK" y reinicia
   * No bloquea: lee lo que haya y procesa las lineas completas. */
  void atenderConsola();

  /* --- envio ------------------------------------------------------- */

  /* Pide turno. Devuelve true y rellena turnoId si se concedio.
   * Si devuelve false, `esperarMs` dice cuanto conviene esperar (con jitter
   * ya aplicado). */
  bool pedirTurno(size_t bytesEstimados, String& turnoId, uint32_t& esperarMs);

  /* Sube un frame por multipart. Devuelve el codigo HTTP.
   *   201 persistido
   *   200 reenvio idempotente, ya estaba
   *   409 conflicto de identidad -- NO reintentar, es un fallo de firmware
   *   422 hash o contrato mal -- NO reintentar
   *   507 la central no acepta frames (sin disco) -- conservar en SD
   *   <0  error de red -- conservar y reintentar */
  int subirFrame(const uint8_t* jpeg, size_t largo, uint32_t seq,
                 uint16_t ancho, uint16_t alto, uint8_t calidadJpeg,
                 uint64_t captureMonoUs, const String& turnoId,
                 int pendientesEnSd);

  /* Envia un lote de muestras. Devuelve el codigo HTTP. */
  int enviarLote(const Muestra* muestras, size_t n, uint32_t seqLote);

  /* Registra un evento. `latido` es el caso frecuente y lo hace atender().
   * El estado del nodo -- bateria, RSSI, heap, pendientes -- viaja colgado del
   * evento: cuesta unos octetos y cero peticiones adicionales. */
  int enviarEvento(const char* tipo, const String& detalle);

  /* --- bateria ------------------------------------------------------ */

  /* Tension del paquete 18650 en milivoltios, o -1 si no se puede medir.
   * Promedia varias lecturas: el ADC del ESP32-S3 es ruidoso, y una sola
   * lectura durante un pico de transmision da un valor artificialmente bajo. */
  int bateriaMv();

  /* true cuando el paquete esta por debajo del umbral critico del plan. El
   * nodo deja de capturar ordenadamente en vez de morirse a mitad de una
   * subida y dejar un archivo a medias. */
  bool bateriaCritica();

  /* Cuantos frames esperan en la microSD. Lo publica el nodo de camara; en los
   * demas vale -1. Es la senal temprana de que el enlace no da abasto. */
  void fijarPendientes(int n) { pendientesSd_ = n; }

  /* --- consulta ---------------------------------------------------- */

  Estado estado() const { return estado_; }
  const String& nodeId() const { return nodeId_; }
  const String& sessionId() const { return sessionId_; }
  const String& bootId() const { return bootId_; }
  const JsonDocument& plan() const { return plan_; }

  /* Convierte un instante del reloj local del nodo a la referencia de la
   * central, aplicando el offset calculado. */
  uint64_t aSesion(uint64_t monoUs) const { return monoUs + offsetUs_; }
  float incertidumbreMs() const;

  /* Construye el frame_id con la gramatica que la central valida:
   *     machine-session-node-boot-seq   ->  M01-R001-CAM02-B03-000036 */
  String frameId(uint32_t seq) const;

  void led(uint8_t r, uint8_t g, uint8_t b);

 private:
  void ordenConsola(String linea);
  bool cargarIdentidad();
  bool conectarWifi();
  bool descubrirCentral();
  bool probarSalud(const String& host);
  bool registrar();
  void sincronizar();
  uint32_t conJitter(uint32_t ms) const;
  void cabeceras(HTTPClient& http) const;
  String url(const char* ruta) const;

  // consola de provision
  String lineaConsola_;
  uint32_t ultimaOrdenMs_ = 0;

  // identidad
  String nodeId_, token_, tipo_, rol_, bootId_;
  String ssid_, pass_, ipCentral_;

  // sesion
  String base_, sessionId_, clockEpochId_;
  JsonDocument plan_;
  uint8_t ranura_ = 0;
  float ranuraOffsetS_ = 0;
  float cicloSyncS_ = RICEVI_SYNC_CICLO_S;

  // reloj
  int64_t offsetUs_ = 0;
  int64_t mejorRttUs_ = 0;
  uint64_t ultimaSyncMs_ = 0;
  // Resultado del intercambio anterior, que viaja colgado del siguiente
  // (piggyback): la central nunca podria conocer t4 de otra forma, porque lo
  // mide el nodo al recibir la respuesta. Cuesta 40 octetos y cero viajes.
  int64_t t4Previo_ = 0, rttPrevio_ = 0, offsetPrevio_ = 0;
  bool hayPrevio_ = false;

  uint64_t ultimoLatidoMs_ = 0;
  Estado estado_ = Estado::SinIdentidad;

  // bateria
  int adcBateria_ = -1;
  float divisorBateria_ = 2.0f;
  int avisoMv_ = 3400, criticoMv_ = 3150;
  int ultimaBateriaMv_ = -1;
  bool avisoBateriaEnviado_ = false;
  int pendientesSd_ = -1;
};

extern Nodo nodo;

/* Microsegundos monotonicos desde el arranque del nodo. */
inline uint64_t monoUs() { return (uint64_t)esp_timer_get_time(); }

/* Texto del motivo del ultimo reinicio. Distinguir un brownout de un watchdog
 * es la diferencia entre un problema electrico y uno de firmware, y no se puede
 * averiguar despues si no se anota ahora. */
const char* motivoReinicio();

}  // namespace ricevi
