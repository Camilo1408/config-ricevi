/*
 * ricevi_config.h - Valores de fabrica de un nodo ESP32-S3 de RiceVi.
 *
 * QUE VA AQUI Y QUE NO
 * --------------------
 * Aqui va SOLO lo que el nodo no puede recibir de la central: como llegar a la
 * red, como encontrarla y quien dice ser. Todo lo demas -- ritmo de captura,
 * resolucion, calidad JPEG, ranura de reloj, pulsos por vuelta, offset del
 * ultrasonico, ROI -- llega en GET /v1/nodes/{id}/plan.
 *
 * POR QUE ESA FRONTERA: cambiar el ritmo de una camara tiene que ser editar
 * config/censo.py y reiniciar la central. Si estuviera aqui, seria desmontar la
 * caja, sacar la placa del cabezal de una cosechadora, conectarla por USB y
 * reflashear. Siete veces.
 *
 * UN BINARIO POR ROL, NO POR NODO
 * -------------------------------
 * Se compilan TRES binarios -- camara, hall, ultrasonico -- y la identidad se
 * graba en NVS al aprovisionar. Las cuatro camaras corren el mismo binario y
 * solo se distinguen por su NVS, asi que un binario mal copiado no puede
 * convertir a CAM03 en CAM02. Con un binario por nodo ese error es cuestion de
 * tiempo, y produce dos nodos reclamando la misma identidad.
 *
 * Los valores de abajo son los POR DEFECTO: lo que usa el nodo si su NVS esta
 * vacia. Sirven para el banco, no para campo.
 */

#pragma once

/* ------------------------------------------------------------------ */
/* Identidad                                                           */
/* ------------------------------------------------------------------ */

/* Claves que el firmware lee del espacio NVS "ricevi" al arrancar:
 *
 *   node_id     cadena  "CAM01".."NU02"            OBLIGATORIA
 *   token       cadena  token portador del nodo    OBLIGATORIA
 *   wifi_ssid   cadena  sobrescribe el de abajo
 *   wifi_pass   cadena  sobrescribe el de abajo
 *   central_ip  cadena  sobrescribe el de abajo
 *
 * Si falta node_id o token, el nodo NO arranca el ciclo normal: LED rojo fijo
 * y espera provision por consola. Un nodo sin identidad que empezara a enviar
 * contaminaria el dataset con un origen desconocido, que es peor que no enviar.
 */

#define RICEVI_MACHINE_ID        "M01"
#define RICEVI_SCHEMA_VERSION    "1.1"
#define RICEVI_FIRMWARE_VERSION  "esp32-1.0.0"
#define RICEVI_NVS_ESPACIO       "ricevi"

/* Al arrancar, el nodo escucha la consola de provision este tiempo antes de
 * conectarse. provisionar_nodo.py abre el puerto (lo que reinicia la placa) y
 * envia la primera orden a los 2 s: tiene que caer dentro. */
#define RICEVI_VENTANA_CONSOLA_MS 5000

/* ------------------------------------------------------------------ */
/* Red                                                                 */
/* ------------------------------------------------------------------ */

#define RICEVI_WIFI_SSID         "RiceVi-M01"
#define RICEVI_WIFI_PASS         "cambiar-en-provision"

/* 2,4 GHz obligatorio: el ESP32-S3 no tiene radio de 5 GHz. Si el punto de
 * acceso esta en 5 GHz o en "automatico", el nodo no vera la red y el sintoma
 * sera indistinguible de una placa averiada. */
#define RICEVI_WIFI_INTENTOS     40
#define RICEVI_WIFI_ESPERA_MS    500

/* Ahorro de energia del Wi-Fi APAGADO a proposito. Con modem-sleep el nodo
 * duerme el radio entre balizas y anade decenas de milisegundos impredecibles a
 * cada peticion, justo en el enlace que es el cuello de botella del sistema.
 * Se gana bateria en un equipo que va enchufado a la maquina, y se pierde la
 * unica parte de la latencia sobre la que se puede actuar. */
#define RICEVI_WIFI_SIN_AHORRO   1

/* ------------------------------------------------------------------ */
/* Descubrimiento de la central: tres vias en cascada                  */
/* ------------------------------------------------------------------ */

/* Via 1: IP fija. La de campo, con reserva DHCP en el router. */
#define RICEVI_CENTRAL_IP        "192.168.40.2"
/* Via 2: mDNS. Necesaria cuando el AP es un movil y reparte direcciones que no
 * controlamos. Cuesta unos cientos de milisegundos en el arranque. */
#define RICEVI_CENTRAL_MDNS      "ricevi-rasp-01"
/* Via 3: la puerta de enlace. Util solo si la central es tambien el AP. */
#define RICEVI_PROBAR_GATEWAY    1

#define RICEVI_CENTRAL_PUERTO    8000

/* ------------------------------------------------------------------ */
/* Cliente HTTP                                                        */
/* ------------------------------------------------------------------ */

#define RICEVI_HTTP_TIMEOUT_MS        8000
#define RICEVI_HTTP_TIMEOUT_FRAME_MS  20000   /* subir un JPEG tarda mas */

/* Retroceso ante 429 o error de red.
 * EL JITTER NO ES DECORACION: sin el, siete nodos que pierden la red a la vez la
 * recuperan a la vez y reintentan en el mismo milisegundo, produciendo
 * exactamente la tormenta que el control de admision intenta evitar. */
#define RICEVI_RETROCESO_BASE_MS      150
#define RICEVI_RETROCESO_MAX_MS       5000
#define RICEVI_RETROCESO_JITTER_MS    120

/* ------------------------------------------------------------------ */
/* Reloj                                                               */
/* ------------------------------------------------------------------ */

/* Repeticiones del intercambio de cuatro tiempos por ciclo. Se conserva la de
 * MENOR RTT: es la que menos ha sufrido encolado, y por tanto aquella en la que
 * el supuesto de simetria ida/vuelta es menos falso. */
#define RICEVI_SYNC_REPETICIONES      7
#define RICEVI_SYNC_CICLO_S           30

/* Si el offset no se refresca en este tiempo, el nodo NO finge precision:
 * sigue enviando, pero con sync_uncertainty_ms alto. Es preferible un dato
 * marcado como incierto a uno con una marca temporal falsamente exacta. */
#define RICEVI_SYNC_CADUCIDAD_S       90

/* ------------------------------------------------------------------ */
/* Almacenamiento local (solo nodos de camara)                         */
/* ------------------------------------------------------------------ */

/* DESACTIVADA (decision del equipo, oct-2026): los nodos NO llevan microSD y
 * todo se guarda en el SSD de la Pi. Consecuencia aceptada: si la Pi esta
 * caida o el Wi-Fi se corta, los frames de ese intervalo se pierden (el LED lo
 * indica en ambar). Con 1, el JPEG se escribe en la microSD ANTES de subirlo y
 * se borra solo cuando la central confirma 201; un corte no pierde el frame y
 * se reenvia con el MISMO frame_id. */
#define RICEVI_SD_HABILITADA          0
#define RICEVI_SD_DIR                 "/pendientes"
#define RICEVI_SD_MAX_PENDIENTES      400    /* ~60 MB a 150 kB por frame */

/* Cuando la SD se llena se descarta EL MAS ANTIGUO, no el mas nuevo: un frame
 * de hace diez minutos vale menos que el de ahora, tanto para el dataset como
 * para el diagnostico. El descarte se cuenta y se reporta como evento. */
#define RICEVI_SD_DESCARTAR_ANTIGUO   1

/* ------------------------------------------------------------------ */
/* Diagnostico                                                         */
/* ------------------------------------------------------------------ */

/* El LED RGB es el unico diagnostico disponible con el nodo dentro de una caja
 * atornillada al cabezal. Conviene pegar este codigo de colores en la cabina:
 *
 *   rojo fijo        sin identidad en NVS
 *   rojo parpadeo    sin Wi-Fi
 *   ambar parpadeo   con Wi-Fi, sin central
 *   verde parpadeo   registrado y operando
 *   verde doble      subiendo un frame
 *   azul             sincronizando reloj
 *   morado           pendientes en la SD por reenviar
 */
#define RICEVI_LED_HABILITADO         1
/* RGB de la placa: G48 en la GOOUUU ESP32-S3-CAM (camaras), GPIO8 en la
 * ESP32-C6 DevKitC (nodos de sensor). */
#if CONFIG_IDF_TARGET_ESP32C6
#define RICEVI_LED_PIN                8
#else
#define RICEVI_LED_PIN                48
#endif

/* Latido a POST /v1/events. Permite al HMI saber que un nodo sigue vivo aunque
 * no tenga nada que enviar. No es redundante con la telemetria: un ultrasonico
 * averiado sigue enviando lotes invalidos. El latido dice que la placa vive; la
 * telemetria dice que el sensor no. */
#define RICEVI_LATIDO_S               10
