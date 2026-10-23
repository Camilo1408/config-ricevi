#include "ricevi_nodo.h"

#include <ESPmDNS.h>
#include <Preferences.h>
#include <esp_mac.h>
#include <esp_system.h>
#include <mbedtls/sha256.h>

namespace ricevi {

Nodo nodo;

/* ------------------------------------------------------------------ */
/* Utilidades                                                          */
/* ------------------------------------------------------------------ */

const char* motivoReinicio() {
  switch (esp_reset_reason()) {
    case ESP_RST_POWERON:  return "POWERON";
    case ESP_RST_SW:       return "SW";
    case ESP_RST_PANIC:    return "PANIC";
    case ESP_RST_INT_WDT:  return "INT_WDT";
    case ESP_RST_TASK_WDT: return "TASK_WDT";
    case ESP_RST_WDT:      return "WDT";
    case ESP_RST_BROWNOUT: return "BROWNOUT";   // problema ELECTRICO
    case ESP_RST_DEEPSLEEP:return "DEEPSLEEP";
    default:               return "DESCONOCIDO";
  }
}

static String sha256Hex(const uint8_t* datos, size_t largo) {
  uint8_t h[32];
  mbedtls_sha256_context c;
  mbedtls_sha256_init(&c);
  mbedtls_sha256_starts(&c, 0);
  mbedtls_sha256_update(&c, datos, largo);
  mbedtls_sha256_finish(&c, h);
  mbedtls_sha256_free(&c);
  char buf[65];
  for (int i = 0; i < 32; i++) sprintf(buf + i * 2, "%02x", h[i]);
  buf[64] = 0;
  return String(buf);
}

void Nodo::led(uint8_t r, uint8_t g, uint8_t b) {
#if RICEVI_LED_HABILITADO
  neopixelWrite(RICEVI_LED_PIN, r, g, b);
#endif
}

uint32_t Nodo::conJitter(uint32_t ms) const {
  // Sin jitter, siete nodos que pierden la red a la vez reintentan en el mismo
  // milisegundo y reproducen la colision que el retroceso queria evitar.
  return ms + (uint32_t)random(0, RICEVI_RETROCESO_JITTER_MS);
}

String Nodo::url(const char* ruta) const { return base_ + ruta; }

void Nodo::cabeceras(HTTPClient& http) const {
  http.addHeader("X-Ricevi-Node", nodeId_);
  http.addHeader("X-Ricevi-Token", token_);
}

String Nodo::frameId(uint32_t seq) const {
  char buf[64];
  snprintf(buf, sizeof(buf), "%s-%s-%s-%s-%06u",
           RICEVI_MACHINE_ID, sessionId_.c_str(), nodeId_.c_str(),
           bootId_.c_str(), (unsigned)seq);
  return String(buf);
}

float Nodo::incertidumbreMs() const {
  // La mitad del mejor RTT es la cota razonable del error de la estimacion,
  // bajo el supuesto de simetria. Si el offset esta caducado, se declara una
  // incertidumbre grande en vez de fingir precision que ya no se tiene.
  uint64_t edadS = (millis() - ultimaSyncMs_) / 1000;
  float base = mejorRttUs_ / 2000.0f;
  if (edadS > RICEVI_SYNC_CADUCIDAD_S) return base + (float)edadS * 10.0f;
  return base;
}

/* ------------------------------------------------------------------ */
/* Consola de provision                                                */
/* ------------------------------------------------------------------ */

void Nodo::atenderConsola() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      String l = lineaConsola_;
      lineaConsola_ = "";
      l.trim();
      if (l.length()) { ultimaOrdenMs_ = millis(); ordenConsola(l); }
    } else if (lineaConsola_.length() < 200) {
      lineaConsola_ += c;
    }
  }
}

void Nodo::ordenConsola(String linea) {
  String orden = linea, resto = "";
  int esp = linea.indexOf(' ');
  if (esp > 0) { orden = linea.substring(0, esp); resto = linea.substring(esp + 1); }
  orden.toLowerCase();

  if (orden == "mac") {
    // La MAC de la estacion Wi-Fi: es la que ve el router y la que va en la
    // reserva DHCP. Se lee del eFuse, sin necesidad de arrancar el Wi-Fi.
    uint8_t m[6];
    esp_read_mac(m, ESP_MAC_WIFI_STA);
    Serial.printf("MAC %02X:%02X:%02X:%02X:%02X:%02X\n", m[0], m[1], m[2], m[3], m[4], m[5]);

  } else if (orden == "set") {
    int e = resto.indexOf(' ');
    String clave = e > 0 ? resto.substring(0, e) : resto;
    String valor = e > 0 ? resto.substring(e + 1) : "";
    valor.trim();
    const bool valida = clave == "node_id" || clave == "token" || clave == "wifi_ssid" ||
                        clave == "wifi_pass" || clave == "central_ip";
    // Las respuestas de error no repiten la clave: el script busca "OK" en la
    // respuesta, y "token" en mayusculas contiene "OK".
    if (!valida) { Serial.println("ERROR clave no reconocida"); return; }
    if (valor.isEmpty()) { Serial.println("ERROR falta el valor"); return; }
    Preferences p;
    p.begin(RICEVI_NVS_ESPACIO, false);
    const bool escrito = p.putString(clave.c_str(), valor) > 0;
    p.end();
    Serial.println(escrito ? "OK " + clave : String("ERROR no se pudo escribir en NVS"));

  } else if (orden == "verificar") {
    Preferences p;
    p.begin(RICEVI_NVS_ESPACIO, true);
    String id = p.getString("node_id", ""), tk = p.getString("token", "");
    String ss = p.getString("wifi_ssid", RICEVI_WIFI_SSID);
    String pw = p.getString("wifi_pass", "");
    String ip = p.getString("central_ip", RICEVI_CENTRAL_IP);
    p.end();
    Serial.printf("node_id=%s token=%s wifi_ssid=%s wifi_pass=%s central_ip=%s\n",
                  id.isEmpty() ? "(vacio)" : id.c_str(),
                  tk.isEmpty() ? "(vacio)" : "********",
                  ss.c_str(), pw.isEmpty() ? "(vacia)" : "********", ip.c_str());

  } else if (orden == "borrar") {
    Preferences p;
    p.begin(RICEVI_NVS_ESPACIO, false);
    p.clear();
    p.end();
    Serial.println("OK borrado");

  } else if (orden == "reiniciar") {
    Serial.println("OK reiniciando");
    Serial.flush();
    delay(100);
    ESP.restart();

  } else {
    Serial.println("ERROR orden desconocida");
  }
}

/* ------------------------------------------------------------------ */
/* Arranque                                                            */
/* ------------------------------------------------------------------ */

bool Nodo::cargarIdentidad() {
  Preferences p;
  p.begin(RICEVI_NVS_ESPACIO, true);
  nodeId_ = p.getString("node_id", "");
  token_ = p.getString("token", "");
  ssid_ = p.getString("wifi_ssid", RICEVI_WIFI_SSID);
  pass_ = p.getString("wifi_pass", RICEVI_WIFI_PASS);
  ipCentral_ = p.getString("central_ip", RICEVI_CENTRAL_IP);
  p.end();

  if (nodeId_.isEmpty() || token_.isEmpty()) {
    // LED rojo FIJO y silencio absoluto. Un nodo sin identidad que empezara a
    // enviar contaminaria el dataset con un origen desconocido.
    Serial.println("[ricevi] SIN IDENTIDAD en NVS. Provisiona con "
                   "herramientas/provisionar_nodo.py");
    estado_ = Estado::SinIdentidad;
    led(64, 0, 0);
    return false;
  }

  // boot_id derivado del contador de arranques: hace unica la pareja
  // (boot_id, seq) despues de cualquier reinicio.
  p.begin(RICEVI_NVS_ESPACIO, false);
  uint32_t n = p.getUInt("boots", 0) + 1;
  p.putUInt("boots", n);
  p.end();
  char buf[8];
  snprintf(buf, sizeof(buf), "B%02u", (unsigned)(n % 10000));
  bootId_ = String(buf);

  Serial.printf("[ricevi] %s boot %s\n", nodeId_.c_str(), bootId_.c_str());
  return true;
}

bool Nodo::conectarWifi() {
  estado_ = Estado::SinRed;
  WiFi.mode(WIFI_STA);
  // El ahorro de energia del radio lo decide el PLAN, no el firmware, porque no
  // es la misma decision para todos los nodos:
  //
  //   Camaras   -> desactivado. El enlace es el cuello de botella de la
  //                latencia y dormir el radio anade decenas de milisegundos
  //                impredecibles a cada peticion.
  //   Sensores  -> activado. Su telemetria viaja por lotes de ~1 s y cada
  //                muestra lleva su propio instante de captura, asi que el
  //                retraso de entrega no degrada la medida. Casi duplica la
  //                autonomia del paquete de 18650 a coste practicamente nulo.
  //
  // Antes de registrarse aun no hay plan, asi que se arranca sin ahorro y se
  // aplica el del plan en cuanto llega.
  WiFi.setSleep(plan_["ahorro_wifi"] | false);
  WiFi.begin(ssid_.c_str(), pass_.c_str());

  for (int i = 0; i < RICEVI_WIFI_INTENTOS; i++) {
    if (WiFi.status() == WL_CONNECTED) {
      Serial.printf("[ricevi] Wi-Fi OK, IP %s, RSSI %d\n",
                    WiFi.localIP().toString().c_str(), WiFi.RSSI());
      return true;
    }
    led((i % 2) ? 48 : 0, 0, 0);       // rojo parpadeando
    delay(RICEVI_WIFI_ESPERA_MS);
  }
  Serial.println("[ricevi] sin Wi-Fi");
  return false;
}

bool Nodo::probarSalud(const String& host) {
  // Se prueba /salud y no un socket a secas: que el puerto acepte una conexion
  // TCP no significa que la central este lista, porque uvicorn escucha antes de
  // que el motor este cargado.
  HTTPClient http;
  String u = "http://" + host + ":" + String(RICEVI_CENTRAL_PUERTO) + "/salud";
  http.setConnectTimeout(1500);
  http.setTimeout(2000);
  if (!http.begin(u)) return false;
  int c = http.GET();
  http.end();
  return c == 200;
}

bool Nodo::descubrirCentral() {
  estado_ = Estado::SinCentral;

  // Via 1: IP fija. La de campo, con reserva DHCP.
  if (!ipCentral_.isEmpty() && probarSalud(ipCentral_)) {
    base_ = "http://" + ipCentral_ + ":" + String(RICEVI_CENTRAL_PUERTO);
    Serial.printf("[ricevi] central por IP fija: %s\n", base_.c_str());
    return true;
  }

  // Via 2: mDNS. Necesaria cuando el AP es un movil y reparte direcciones que
  // no controlamos.
  if (MDNS.begin(nodeId_.c_str())) {
    IPAddress ip = MDNS.queryHost(RICEVI_CENTRAL_MDNS, 3000);
    if (ip != IPAddress((uint32_t)0) && probarSalud(ip.toString())) {
      base_ = "http://" + ip.toString() + ":" + String(RICEVI_CENTRAL_PUERTO);
      Serial.printf("[ricevi] central por mDNS: %s\n", base_.c_str());
      return true;
    }
  }

#if RICEVI_PROBAR_GATEWAY
  // Via 3: la puerta de enlace. Util solo si la central es tambien el AP.
  String gw = WiFi.gatewayIP().toString();
  if (probarSalud(gw)) {
    base_ = "http://" + gw + ":" + String(RICEVI_CENTRAL_PUERTO);
    Serial.printf("[ricevi] central en la puerta de enlace: %s\n", base_.c_str());
    return true;
  }
#endif

  led(48, 24, 0);   // ambar: hay red, no hay central
  return false;
}

bool Nodo::registrar() {
  estado_ = Estado::Registrando;
  JsonDocument d;
  d["schema_version"] = RICEVI_SCHEMA_VERSION;
  d["machine_id"] = RICEVI_MACHINE_ID;
  d["node_id"] = nodeId_;
  d["boot_id"] = bootId_;
  d["tipo"] = tipo_;
  d["rol"] = rol_;
  d["firmware"] = RICEVI_FIRMWARE_VERSION;
  d["plataforma"] = ESP.getChipModel();
  d["motivo_reinicio"] = motivoReinicio();

  String cuerpo;
  serializeJson(d, cuerpo);

  HTTPClient http;
  http.begin(url("/v1/nodes/register"));
  http.addHeader("Content-Type", "application/json");
  cabeceras(http);
  http.setTimeout(RICEVI_HTTP_TIMEOUT_MS);
  int c = http.POST(cuerpo);
  String resp = http.getString();
  http.end();

  if (c != 200) {
    Serial.printf("[ricevi] registro fallido %d: %s\n", c, resp.c_str());
    return false;
  }

  JsonDocument r;
  if (deserializeJson(r, resp)) return false;

  sessionId_ = r["session_id"].as<String>();
  clockEpochId_ = r["clock_epoch_id"].as<String>();
  ranura_ = r["ranura_indice"] | 0;
  ranuraOffsetS_ = r["ranura_offset_s"] | 0.0f;
  cicloSyncS_ = r["ciclo_sync_s"] | (float)RICEVI_SYNC_CICLO_S;
  plan_.set(r["plan"]);

  // Umbrales de bateria y pin de medida: tambien llegan en el plan.
  JsonVariantConst b = plan_["bateria"];
  if (!b.isNull()) {
    adcBateria_ = b["adc_pin"] | -1;
    divisorBateria_ = b["divisor"] | 2.0f;
    avisoMv_ = b["aviso_mv"] | 3400;
    criticoMv_ = b["critico_mv"] | 3150;
    if (adcBateria_ >= 0) {
      analogReadResolution(12);
      // 11 dB lleva el fondo de escala a ~2,5 V, que con el divisor 2:1 cubre
      // los 4,2 V de una celda a plena carga con margen.
      analogSetPinAttenuation(adcBateria_, ADC_11db);
    }
  }

  // El ahorro de energia del radio se aplica ya con el plan en la mano.
  WiFi.setSleep(plan_["ahorro_wifi"] | false);

  Serial.printf("[ricevi] sesion %s, ranura %u (+%.2f s), modelo '%s', "
                "ahorro_wifi=%s\n",
                sessionId_.c_str(), ranura_, ranuraOffsetS_,
                r["modelo_activo"].as<const char*>(),
                (plan_["ahorro_wifi"] | false) ? "si" : "no");
  return true;
}

/* ------------------------------------------------------------------ */
/* Bateria                                                             */
/* ------------------------------------------------------------------ */

int Nodo::bateriaMv() {
  if (adcBateria_ < 0) return -1;
  // Se promedian ocho lecturas: el ADC del ESP32-S3 es ruidoso, y una sola
  // lectura tomada durante un pico de transmision da un valor artificialmente
  // bajo que dispararia el aviso sin motivo.
  uint32_t suma = 0;
  for (int i = 0; i < 8; i++) { suma += analogReadMilliVolts(adcBateria_); delay(2); }
  ultimaBateriaMv_ = (int)((suma / 8) * divisorBateria_);
  return ultimaBateriaMv_;
}

bool Nodo::bateriaCritica() {
  return ultimaBateriaMv_ > 0 && ultimaBateriaMv_ < criticoMv_;
}

bool Nodo::comenzar(const char* tipo, const char* rol) {
  tipo_ = tipo;
  rol_ = rol;
  randomSeed(esp_random());

  // Ventana de provision: unos segundos escuchando la consola ANTES de tocar el
  // Wi-Fi. Abrir el puerto serie reinicia la placa, asi que provisionar_nodo.py
  // siempre cae dentro de esta ventana, incluso en un nodo ya provisionado que
  // se quedaria atascado intentando una red con la clave equivocada. Mientras
  // lleguen ordenes, la ventana se prolonga.
  Serial.println("[ricevi] consola de provision: 'mac', 'set <clave> <valor>', "
                 "'verificar', 'reiniciar'");
  ultimaOrdenMs_ = 0;
  const uint32_t inicio = millis();
  while (millis() - inicio < RICEVI_VENTANA_CONSOLA_MS ||
         (ultimaOrdenMs_ && millis() - ultimaOrdenMs_ < RICEVI_VENTANA_CONSOLA_MS)) {
    atenderConsola();
    delay(10);
  }

  if (!cargarIdentidad()) {
    // Se queda aqui para siempre, con el LED en rojo y la consola abierta. Es
    // deliberado: un nodo sin identidad no envia nada.
    while (true) { led(64, 0, 0); atenderConsola(); delay(10); }
  }

  while (!conectarWifi()) delay(2000);

  // Reintenta sin limite: en campo, un nodo que se rinde hay que ir a
  // reiniciarlo subido a una cosechadora.
  uint32_t espera = RICEVI_RETROCESO_BASE_MS;
  while (!descubrirCentral() || !registrar()) {
    delay(conJitter(espera));
    espera = min<uint32_t>(espera * 2, RICEVI_RETROCESO_MAX_MS);
    if (WiFi.status() != WL_CONNECTED) conectarWifi();
  }

  sincronizar();
  enviarEvento("arranque", String("motivo=") + motivoReinicio());
  estado_ = Estado::Operando;
  return true;
}

/* ------------------------------------------------------------------ */
/* Reloj                                                               */
/* ------------------------------------------------------------------ */

void Nodo::sincronizar() {
  estado_ = Estado::Sincronizando;
  led(0, 0, 48);

  int64_t mejorRtt = INT64_MAX, mejorOffset = 0;

  for (int i = 0; i < RICEVI_SYNC_REPETICIONES; i++) {
    JsonDocument d;
    d["node_id"] = nodeId_;
    int64_t t1 = (int64_t)monoUs();
    d["t1_us"] = t1;
    if (hayPrevio_) {
      d["t4_previo_us"] = t4Previo_;
      d["rtt_previo_us"] = rttPrevio_;
      d["offset_previo_us"] = offsetPrevio_;
    }
    String cuerpo;
    serializeJson(d, cuerpo);

    HTTPClient http;
    http.begin(url("/v1/time/exchange"));
    http.addHeader("Content-Type", "application/json");
    cabeceras(http);
    http.setTimeout(RICEVI_HTTP_TIMEOUT_MS);
    int c = http.POST(cuerpo);
    int64_t t4 = (int64_t)monoUs();
    String resp = http.getString();
    http.end();
    if (c != 200) continue;

    JsonDocument r;
    if (deserializeJson(r, resp)) continue;
    // as<int64_t>() y no `| 0`: con un int por defecto, ArduinoJson devuelve el
    // 0 en cuanto el valor no cabe en 32 bits, es decir, cuando la central
    // lleva mas de 35 minutos en marcha. El offset salia como -t1 y todas las
    // marcas de tiempo quedaban horas en el pasado.
    if (!r["t2_us"].is<int64_t>() || !r["t3_us"].is<int64_t>()) continue;
    int64_t t2 = r["t2_us"].as<int64_t>();
    int64_t t3 = r["t3_us"].as<int64_t>();

    // El termino (t3 - t2) resta lo que la central tardo en procesar, de modo
    // que el RTT mide solo el viaje. Sin el, con la CPU cargada de inferencia
    // se confundiria carga de CPU con mala red.
    int64_t rtt = (t4 - t1) - (t3 - t2);
    int64_t offset = ((t2 - t1) + (t3 - t4)) / 2;

    // Se conserva el de MENOR RTT: es el que menos encolado ha sufrido, y por
    // tanto aquel en el que el supuesto de simetria es menos falso.
    if (rtt >= 0 && rtt < mejorRtt) { mejorRtt = rtt; mejorOffset = offset; }

    t4Previo_ = t4; rttPrevio_ = rtt; offsetPrevio_ = offset;
    hayPrevio_ = true;

    String epoch = r["clock_epoch_id"].as<String>();
    if (!clockEpochId_.isEmpty() && epoch != clockEpochId_) {
      // La central se reinicio: su cero de sesion cambio y todos los offsets
      // calculados dejan de valer. Volver a registrarse es lo unico correcto;
      // seguir convirtiendo con el offset viejo corromperia en silencio las
      // marcas de tiempo de todo lo que llegue despues.
      Serial.println("[ricevi] clock_epoch_id cambio: hay que registrarse otra vez");
      estado_ = Estado::Registrando;
      clockEpochId_ = epoch;
      return;
    }
    delay(20);
  }

  if (mejorRtt != INT64_MAX) {
    offsetUs_ = mejorOffset;
    mejorRttUs_ = mejorRtt;
    ultimaSyncMs_ = millis();
    Serial.printf("[ricevi] reloj: offset %lld us, mejor RTT %lld us\n",
                  (long long)offsetUs_, (long long)mejorRttUs_);
  }
  estado_ = Estado::Operando;
}

/* ------------------------------------------------------------------ */
/* Bucle de mantenimiento                                              */
/* ------------------------------------------------------------------ */

void Nodo::atender() {
  atenderConsola();
  if (WiFi.status() != WL_CONNECTED) {
    estado_ = Estado::SinRed;
    conectarWifi();
    return;
  }
  if (estado_ == Estado::Registrando) {
    if (descubrirCentral() && registrar()) sincronizar();
    return;
  }

  uint64_t ahora = millis();

  // Le toca sincronizar cuando el ciclo pasa por su ranura. El escalonado lo
  // asigna la central, no el firmware: asi se puede reordenar sin reflashear
  // siete placas.
  uint32_t cicloMs = (uint32_t)(cicloSyncS_ * 1000);
  uint32_t fase = (uint32_t)(ahora % cicloMs);
  uint32_t miFase = (uint32_t)(ranuraOffsetS_ * 1000);
  if (ahora - ultimaSyncMs_ > cicloMs &&
      fase >= miFase && fase < miFase + 500) {
    sincronizar();
  }

  if (ahora - ultimoLatidoMs_ > (uint64_t)RICEVI_LATIDO_S * 1000) {
    int mv = bateriaMv();
    enviarEvento("latido", String("rssi=") + WiFi.RSSI());
    ultimoLatidoMs_ = ahora;

    // Aviso UNA sola vez por cruce de umbral, no en cada latido: siete nodos
    // repitiendo el mismo evento cada diez segundos ahogarian la tabla de
    // eventos justo cuando hace falta leerla.
    if (mv > 0 && mv < avisoMv_ && !avisoBateriaEnviado_) {
      enviarEvento(mv < criticoMv_ ? "bateria_critica" : "bateria_baja",
                   String(mv) + " mV");
      avisoBateriaEnviado_ = true;
    } else if (mv > avisoMv_ + 100) {
      // Histeresis de 100 mV: sin ella, un paquete justo en el umbral
      // dispararia el aviso en cada pico de transmision.
      avisoBateriaEnviado_ = false;
    }
  }

  // Aviso visible: con el nodo dentro de una caja cerrada, el LED es lo unico
  // que se puede mirar sin desmontar nada.
  if (ultimaBateriaMv_ > 0 && ultimaBateriaMv_ < avisoMv_)
    led(48, ultimaBateriaMv_ < criticoMv_ ? 0 : 24, 0);
}

/* ------------------------------------------------------------------ */
/* Envio                                                               */
/* ------------------------------------------------------------------ */

bool Nodo::pedirTurno(size_t bytesEstimados, String& turnoId, uint32_t& esperarMs) {
  JsonDocument d;
  d["node_id"] = nodeId_;
  d["bytes_estimados"] = (uint32_t)bytesEstimados;
  String cuerpo;
  serializeJson(d, cuerpo);

  HTTPClient http;
  http.begin(url("/v1/upload-slots"));
  http.addHeader("Content-Type", "application/json");
  cabeceras(http);
  http.setTimeout(RICEVI_HTTP_TIMEOUT_MS);
  int c = http.POST(cuerpo);
  String resp = http.getString();
  http.end();

  if (c != 200) { esperarMs = conJitter(RICEVI_RETROCESO_BASE_MS); return false; }

  JsonDocument r;
  if (deserializeJson(r, resp)) { esperarMs = conJitter(RICEVI_RETROCESO_BASE_MS); return false; }

  // Si la central dejo de aceptar frames por falta de disco, hay que conservar
  // en la SD en vez de descartar.
  if (!(r["aceptando_frames"] | true)) {
    esperarMs = conJitter(5000);
    return false;
  }
  if (r["concedido"] | false) {
    turnoId = r["turno_id"].as<String>();
    return true;
  }
  esperarMs = conJitter(r["reintentar_en_ms"] | RICEVI_RETROCESO_BASE_MS);
  return false;
}

int Nodo::subirFrame(const uint8_t* jpeg, size_t largo, uint32_t seq,
                     uint16_t ancho, uint16_t alto, uint8_t calidadJpeg,
                     uint64_t captureMonoUs, const String& turnoId,
                     int pendientesEnSd) {
  JsonDocument m;
  m["schema_version"] = RICEVI_SCHEMA_VERSION;
  m["machine_id"] = RICEVI_MACHINE_ID;
  m["node_id"] = nodeId_;
  m["boot_id"] = bootId_;
  m["seq"] = seq;
  m["session_id"] = sessionId_;
  m["camera_id"] = nodeId_;
  m["frame_id"] = frameId(seq);
  m["capture_mono_us"] = captureMonoUs;
  m["capture_session_us"] = aSesion(captureMonoUs);
  m["sync_uncertainty_ms"] = incertidumbreMs();
  m["clock_epoch_id"] = clockEpochId_;
  m["utc_quality"] = "desconocida";   // el nodo no tiene hora civil propia
  m["bytes"] = (uint32_t)largo;
  m["sha256"] = sha256Hex(jpeg, largo);
  m["ancho"] = ancho;
  m["alto"] = alto;
  m["jpeg_calidad"] = calidadJpeg;
  if (!turnoId.isEmpty()) m["turno_id"] = turnoId;
  m["config_version"] = plan_["config_version"] | "";
  m["censo_version"] = plan_["censo_version"] | "";
  if (pendientesEnSd >= 0) m["pendientes_en_sd"] = pendientesEnSd;

  String meta;
  serializeJson(m, meta);

  const String limite = "----RiceViFrame";
  String cabeza =
      "--" + limite + "\r\n"
      "Content-Disposition: form-data; name=\"meta\"\r\n\r\n" + meta + "\r\n"
      "--" + limite + "\r\n"
      "Content-Disposition: form-data; name=\"imagen\"; filename=\"f.jpg\"\r\n"
      "Content-Type: image/jpeg\r\n\r\n";
  const String cola = "\r\n--" + limite + "--\r\n";

  // Se arma el cuerpo completo en RAM. Con 8 MB de PSRAM y un JPEG de 150 kB
  // sobra de largo, y evita la complicacion de un envio por bloques.
  size_t total = cabeza.length() + largo + cola.length();
  uint8_t* cuerpo = (uint8_t*)malloc(total);
  if (!cuerpo) return -1;
  memcpy(cuerpo, cabeza.c_str(), cabeza.length());
  memcpy(cuerpo + cabeza.length(), jpeg, largo);
  memcpy(cuerpo + cabeza.length() + largo, cola.c_str(), cola.length());

  HTTPClient http;
  http.begin(url("/v1/frames"));
  http.addHeader("Content-Type", "multipart/form-data; boundary=" + limite);
  cabeceras(http);
  http.setTimeout(RICEVI_HTTP_TIMEOUT_FRAME_MS);
  led(0, 64, 0);
  int c = http.POST(cuerpo, total);
  http.end();
  free(cuerpo);

  return c;
}

int Nodo::enviarLote(const Muestra* muestras, size_t n, uint32_t seqLote) {
  JsonDocument d;
  d["schema_version"] = RICEVI_SCHEMA_VERSION;
  d["machine_id"] = RICEVI_MACHINE_ID;
  d["node_id"] = nodeId_;
  d["boot_id"] = bootId_;
  d["seq"] = seqLote;
  d["session_id"] = sessionId_;
  d["sync_uncertainty_ms"] = incertidumbreMs();
  d["clock_epoch_id"] = clockEpochId_;
  d["config_version"] = plan_["config_version"] | "";
  d["censo_version"] = plan_["censo_version"] | "";

  JsonArray arr = d["muestras"].to<JsonArray>();
  for (size_t i = 0; i < n; i++) {
    const Muestra& s = muestras[i];
    JsonObject o = arr.add<JsonObject>();
    o["sensor_id"] = s.sensorId;
    o["magnitud"] = s.magnitud;
    o["seq"] = s.seq;
    o["capture_mono_us"] = s.captureMonoUs;
    o["capture_session_us"] = s.captureSessionUs;
    o["ventana_us"] = s.ventanaUs;
    o["unidad"] = s.unidad;
    o["calidad"] = s.calidad;
    o["codigo_calidad"] = s.codigoCalidad;
    // LA REGLA DEL NULO: si no hay medida, el campo va a null. Nunca cero.
    if (s.tieneValor) o["valor"] = s.valor;
    else              o["valor"] = nullptr;
    if (s.calibrationId) o["calibration_id"] = s.calibrationId;
    if (s.pulsosVentana >= 0)     o["pulsos_ventana"] = s.pulsosVentana;
    if (s.pulsosAcumulados >= 0)  o["pulsos_acumulados"] = s.pulsosAcumulados;
    if (s.pulsosPorVuelta >= 0)   o["pulsos_por_vuelta"] = s.pulsosPorVuelta;
    if (s.edadUltimoPulsoMs >= 0) o["edad_ultimo_pulso_ms"] = s.edadUltimoPulsoMs;
    if (s.periodoUltimoUs >= 0)   o["periodo_ultimo_us"] = s.periodoUltimoUs;
    if (s.distanciaCrudaMm >= 0)  o["distancia_cruda_mm"] = s.distanciaCrudaMm;
    if (s.offsetBMm >= 0)         o["offset_b_mm"] = s.offsetBMm;
    if (s.tramasDescartadas >= 0) o["tramas_descartadas"] = s.tramasDescartadas;
  }

  String cuerpo;
  serializeJson(d, cuerpo);

  HTTPClient http;
  http.begin(url("/v1/telemetry"));
  http.addHeader("Content-Type", "application/json");
  cabeceras(http);
  http.setTimeout(RICEVI_HTTP_TIMEOUT_MS);
  int c = http.POST(cuerpo);
  http.end();
  return c;
}

int Nodo::enviarEvento(const char* tipo, const String& detalle) {
  JsonDocument d;
  d["node_id"] = nodeId_;
  d["tipo"] = tipo;
  d["detalle"] = detalle;
  // El estado del nodo viaja colgado de cualquier evento. Con siete juegos de
  // bateria independientes, saber cual se esta agotando es lo que evita perder
  // una vista a mitad de jornada sin aviso.
  if (ultimaBateriaMv_ > 0) d["bateria_mv"] = ultimaBateriaMv_;
  if (WiFi.status() == WL_CONNECTED) d["rssi_dbm"] = WiFi.RSSI();
  d["heap_libre"] = (uint32_t)ESP.getFreeHeap();
  if (pendientesSd_ >= 0) d["pendientes_en_sd"] = pendientesSd_;
  String cuerpo;
  serializeJson(d, cuerpo);

  HTTPClient http;
  http.begin(url("/v1/events"));
  http.addHeader("Content-Type", "application/json");
  cabeceras(http);
  http.setTimeout(RICEVI_HTTP_TIMEOUT_MS);
  int c = http.POST(cuerpo);
  http.end();
  return c;
}

}  // namespace ricevi
