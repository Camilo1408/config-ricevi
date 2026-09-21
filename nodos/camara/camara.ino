/*
 * camara.ino - Firmware de CAM01..CAM04 (ESP32-S3-CAM con OV3660).
 *
 * EL MISMO BINARIO PARA LAS CUATRO. La identidad y el plan llegan de la NVS y
 * de la central: aqui no hay nada especifico de una vista.
 *
 * EL ORDEN DE LAS COSAS, Y POR QUE
 * --------------------------------
 *   1. Capturar
 *   2. Escribir en la microSD del nodo          <- ANTES de subir
 *   3. Pedir turno
 *   4. Subir
 *   5. Borrar de la SD solo con 201 o 200
 *
 * El paso 2 antes del 4 es lo que hace que un reinicio de la central o un corte
 * de Wi-Fi no pierdan el frame. Al volver, el nodo reenvia con el MISMO
 * frame_id y la central responde 200 sin duplicar: la idempotencia del endpoint
 * es lo que hace seguro ese reenvio.
 *
 * ANTES DE COMPILAR
 * -----------------
 * Herramientas -> Placa: "ESP32S3 Dev Module"
 *   PSRAM: "OPI PSRAM"          <- sin esto no hay buffer para el JPEG
 *   Flash Size: 16MB (128Mb)
 *   Partition Scheme: "16M Flash (3MB APP/9.9MB FATFS)"
 *   USB CDC On Boot: Enabled
 *
 * El pinout de abajo es el habitual de estas placas, pero VERIFICALO contra la
 * serigrafia y el ejemplo del fabricante antes de dar nada por bueno. Lo
 * primero que hay que hacer con una placa nueva es correr su ejemplo de camara.
 */

#include <Arduino.h>
#include <FS.h>
#include <SD_MMC.h>
#include <esp_camera.h>

#include "../comun/ricevi_nodo.h"

using ricevi::nodo;

/* ---- pinout de la ESP32-S3-CAM (VERIFICAR con la placa recibida) ---- */
#define PIN_PWDN   -1
#define PIN_RESET  -1
#define PIN_XCLK   15
#define PIN_SIOD    4
#define PIN_SIOC    5
#define PIN_D7     16
#define PIN_D6     17
#define PIN_D5     18
#define PIN_D4     12
#define PIN_D3     10
#define PIN_D2      8
#define PIN_D1      9
#define PIN_D0     11
#define PIN_VSYNC   6
#define PIN_HREF    7
#define PIN_PCLK   13

/* microSD en modo SD_MMC de 1 bit. Ocupa pines del rango JTAG, asi que con la
 * SD en uso no se puede depurar por JTAG: la depuracion va por consola serie. */
#define PIN_SD_CLK 39
#define PIN_SD_CMD 38
#define PIN_SD_D0  40

static uint32_t seq_ = 0;
static bool haySd_ = false;
static int pendientes_ = 0;

/* ------------------------------------------------------------------ */
/* Camara                                                              */
/* ------------------------------------------------------------------ */

static bool iniciarCamara() {
  camera_config_t c = {};
  c.ledc_channel = LEDC_CHANNEL_0;
  c.ledc_timer = LEDC_TIMER_0;
  c.pin_d0 = PIN_D0; c.pin_d1 = PIN_D1; c.pin_d2 = PIN_D2; c.pin_d3 = PIN_D3;
  c.pin_d4 = PIN_D4; c.pin_d5 = PIN_D5; c.pin_d6 = PIN_D6; c.pin_d7 = PIN_D7;
  c.pin_xclk = PIN_XCLK; c.pin_pclk = PIN_PCLK;
  c.pin_vsync = PIN_VSYNC; c.pin_href = PIN_HREF;
  c.pin_sccb_sda = PIN_SIOD; c.pin_sccb_scl = PIN_SIOC;
  c.pin_pwdn = PIN_PWDN; c.pin_reset = PIN_RESET;
  c.xclk_freq_hz = 20000000;

  // JPEG directo del controlador. Espressif advierte del coste de RGB/YUV con
  // el Wi-Fi activo: capturar en RGB y comprimir despues costaria CPU y RAM
  // para obtener exactamente el mismo archivo.
  c.pixel_format = PIXFORMAT_JPEG;
  c.frame_size = FRAMESIZE_HD;      // 1280x720; el plan puede pedir otro
  c.jpeg_quality = 12;              // en OV, MENOR numero = MAYOR calidad
  c.fb_count = 2;
  c.fb_location = CAMERA_FB_IN_PSRAM;
  // LATEST y no EMPTY: con EMPTY el controlador puede devolver un frame
  // anterior que quedo en el buffer, y el instante de captura registrado no
  // corresponderia a la imagen. Con LATEST siempre sale el mas reciente.
  c.grab_mode = CAMERA_GRAB_LATEST;

  esp_err_t e = esp_camera_init(&c);
  if (e != ESP_OK) {
    Serial.printf("[cam] fallo la camara: 0x%x\n", e);
    return false;
  }
  return true;
}

/* Aplica el plan que mando la central: resolucion, calidad y, en la tolva, los
 * controles manuales. */
static void aplicarPlan() {
  sensor_t* s = esp_camera_sensor_get();
  if (!s) return;

  int ancho = nodo.plan()["ancho"] | 1280;
  s->set_framesize(s, ancho >= 1280 ? FRAMESIZE_HD : FRAMESIZE_VGA);

  int q = nodo.plan()["jpeg_calidad"] | 85;
  // El plan viene en escala 1..100 (mayor = mejor) y el sensor OV usa 0..63
  // (menor = mejor). Convertir mal aqui produce imagenes sistematicamente peores
  // de lo que dice el acta de sesion.
  s->set_quality(s, map(q, 1, 100, 63, 4));

  if (nodo.plan()["exposicion_manual"] | false) {
    // Solo en CAM04. Si la exposicion varia entre frames, el porcentaje
    // segmentado cambia por razones que no tienen que ver con el material, y
    // las tolvadas dejan de ser comparables entre si.
    s->set_gain_ctrl(s, 0);
    s->set_exposure_ctrl(s, 0);
    s->set_whitebal(s, 0);
    s->set_awb_gain(s, 0);
    s->set_aec_value(s, 300);
    s->set_agc_gain(s, 4);
    Serial.println("[cam] tolva: exposicion, ganancia y balance MANUALES");
  }
}

/* ------------------------------------------------------------------ */
/* microSD: el seguro contra perder frames                             */
/* ------------------------------------------------------------------ */

static void iniciarSd() {
#if RICEVI_SD_HABILITADA
  SD_MMC.setPins(PIN_SD_CLK, PIN_SD_CMD, PIN_SD_D0);
  haySd_ = SD_MMC.begin("/sdcard", true);   // true = modo 1 bit
  if (!haySd_) {
    Serial.println("[cam] SIN microSD: un corte de enlace perdera frames");
    nodo.enviarEvento("sd_ausente", "no monta la microSD del nodo");
    return;
  }
  if (!SD_MMC.exists(RICEVI_SD_DIR)) SD_MMC.mkdir(RICEVI_SD_DIR);
  File d = SD_MMC.open(RICEVI_SD_DIR);
  for (File f = d.openNextFile(); f; f = d.openNextFile()) pendientes_++;
  Serial.printf("[cam] microSD OK, %d pendiente(s) de la sesion anterior\n",
                pendientes_);
#endif
}

static String rutaPendiente(uint32_t seq) {
  char b[64];
  snprintf(b, sizeof(b), "%s/%06u.jpg", RICEVI_SD_DIR, (unsigned)seq);
  return String(b);
}

static void guardarPendiente(uint32_t seq, const uint8_t* d, size_t n) {
  if (!haySd_) return;
  if (pendientes_ >= RICEVI_SD_MAX_PENDIENTES) {
#if RICEVI_SD_DESCARTAR_ANTIGUO
    // Se descarta el MAS ANTIGUO. Un frame de hace diez minutos vale menos que
    // el de ahora, tanto para el dataset como para el diagnostico. Y el
    // descarte se cuenta y se reporta: nunca en silencio.
    File dir = SD_MMC.open(RICEVI_SD_DIR);
    File primero = dir.openNextFile();
    if (primero) {
      String r = String(RICEVI_SD_DIR) + "/" + primero.name();
      primero.close();
      SD_MMC.remove(r);
      pendientes_--;
      nodo.enviarEvento("sd_llena", "descartado el pendiente mas antiguo");
    }
#else
    return;
#endif
  }
  File f = SD_MMC.open(rutaPendiente(seq), FILE_WRITE);
  if (!f) return;
  f.write(d, n);
  f.close();
  pendientes_++;
}

static void borrarPendiente(uint32_t seq) {
  if (!haySd_) return;
  if (SD_MMC.remove(rutaPendiente(seq))) pendientes_--;
}

/* ------------------------------------------------------------------ */

void setup() {
  Serial.begin(115200);
  delay(300);
  Serial.println("\n[cam] RiceVi camara " RICEVI_FIRMWARE_VERSION);

  if (!iniciarCamara()) {
    while (true) { nodo.led(64, 0, 0); delay(400); nodo.led(0, 0, 0); delay(400); }
  }
  nodo.comenzar("camara", "camara");
  aplicarPlan();
  iniciarSd();
  if (pendientes_ > 0)
    nodo.enviarEvento("sd_reenvio",
                      String(pendientes_) + " pendientes de la sesion anterior");
}

void loop() {
  nodo.atender();
  nodo.fijarPendientes(pendientes_);

  // Paquete de bateria agotado: se deja de capturar ORDENADAMENTE en vez de
  // morirse a mitad de una subida y dejar un archivo a medias. La central lo
  // vera como un nodo que sigue vivo pero no produce, y el LED lo dira en rojo.
  if (nodo.bateriaCritica()) {
    static bool avisado = false;
    if (!avisado) {
      nodo.enviarEvento("captura_detenida", "bateria critica");
      avisado = true;
    }
    nodo.led(64, 0, 0);
    delay(5000);
    return;
  }

  const float fps = nodo.plan()["captura_fps"] | 1.0f;
  const uint32_t periodoMs = (uint32_t)(1000.0f / max(0.05f, fps));
  const uint32_t t0 = millis();

  // --- capturar ---------------------------------------------------------
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) {
    nodo.enviarEvento("captura_fallida", "esp_camera_fb_get devolvio null");
    delay(periodoMs);
    return;
  }
  // El instante se toma JUSTO DESPUES de obtener el frame, no antes de pedirlo:
  // entre la peticion y la entrega puede pasar tiempo variable.
  const uint64_t capturaUs = ricevi::monoUs();
  seq_++;

  guardarPendiente(seq_, fb->buf, fb->len);

  // --- turno --------------------------------------------------------------
  String turno;
  uint32_t esperar = 0;
  bool subido = false;

  if (nodo.pedirTurno(fb->len, turno, esperar)) {
    int c = nodo.subirFrame(fb->buf, fb->len, seq_, fb->width, fb->height,
                            nodo.plan()["jpeg_calidad"] | 85,
                            capturaUs, turno, pendientes_);
    if (c == 201 || c == 200) {
      borrarPendiente(seq_);
      subido = true;
      nodo.led(0, 32, 0);
    } else if (c == 409 || c == 422) {
      // Fallo de firmware o de identidad: reintentar dara siempre lo mismo y
      // solo gastaria tiempo de aire. Se descarta el pendiente y se avisa.
      borrarPendiente(seq_);
      nodo.enviarEvento("frame_rechazado", String("http=") + c);
    } else {
      // Error de red o 507 sin disco: se conserva en la SD y se reintentara.
      nodo.led(48, 0, 48);
    }
  } else {
    // Sin turno: el frame ya esta a salvo en la SD.
    nodo.led(48, 0, 48);
  }

  esp_camera_fb_return(fb);

  // El ritmo DESCUENTA lo que ya se tardo. Si se hiciera delay(periodo) a
  // secas, el periodo real seria periodo + tiempo_de_subida y la tasa de
  // captura caeria por debajo de la del plan sin que nadie lo notara.
  const uint32_t gastado = millis() - t0;
  const uint32_t espera = (esperar > 0 && !subido)
                              ? max(esperar, (uint32_t)10)
                              : (periodoMs > gastado ? periodoMs - gastado : 0);
  delay(espera);
}
