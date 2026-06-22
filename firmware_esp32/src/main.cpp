/*
 * esp32_nodo.cpp  ->  src/main.cpp en PlatformIO  (firmware DEFINITIVO)
 * ------------------------------------------------------------------
 * Un nodo, DOS modos (Federer decide cual via cluster/mode):
 *   - Config A (fedavg): reactivo. Entrena al recibir el modelo global,
 *     devuelve pesos al maestro. (fedavg/global, fedavg/update)
 *   - Config B (gossip): autonomo. Entrena de continuo, cada T elige un
 *     vecino al azar y le envia sus pesos; al recibir, promedia
 *     w_local=(w_local+w_vecino)/2. Sin maestro. Reporta a Federer.
 * Mas: ArduinoOTA (grabado por red) y metricas ampliadas.
 *
 * Primera grabacion por USB (env esp32dev); siguientes por red (esp32ota).
 * Copia datos_nodo_k.h de ESTE nodo como include/datos_nodo.h
 * ------------------------------------------------------------------
 */
#include <Arduino.h>
#include <WiFi.h>
#include <ArduinoOTA.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include "datos_nodo.h"

// ---------------- EDITAR ----------------
const char* WIFI_SSID = "TU_RED_WIFI";
const char* WIFI_PASS = "TU_PASSWORD";
const char* BROKER_IP = "192.168.1.100";
const uint16_t BROKER_PORT = 1883;
const char* OTA_PASS  = "federer";
// ----------------------------------------

const char* T_ANNOUNCE = "cluster/announce";
const char* T_DISCOVER = "cluster/discover";
const char* T_CONFIG   = "cluster/config";
const char* T_CMD      = "cluster/cmd";
const char* T_MODE     = "cluster/mode";
const char* T_GLOBAL   = "fedavg/global";
const char* T_UPDATE   = "fedavg/update";
const char* T_GREPORT  = "gossip/report";
const char* FW_VER     = "3.0-AB";

const int N_PESOS = N_FEATURES + 1;
const unsigned long HEARTBEAT_MS = 5000;
const unsigned long TRAIN_STEP_MS = 150;     // en gossip: una epoca cada 150 ms

// modos: 0=idle, 1=fedavg, 2=gossip
int g_mode = 1;
float g_lr = 0.01f, g_beta = 0.9f;
int   g_epocas = 5;

// gossip
int   g_peers[16]; int g_npeers = 0;
unsigned long g_tgossip = 3000, g_report = 2000;
unsigned long last_gossip = 0, last_report = 0, last_train = 0;
long  exch = 0;
float v_g[7];                                  // momentum persistente en gossip
String g_inbox;                                // gossip/inbox/<NODE_ID>

WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);

float w[N_PESOS];
volatile bool pendiente = false;
int ronda_rx = -1; float w_rx[7];
unsigned long ult_heartbeat = 0;

float predecir(const float* x) {
  float yhat = w[N_FEATURES];
  for (int j = 0; j < N_FEATURES; j++) yhat += w[j] * x[j];
  return yhat;
}
void entrenar_una_epoca(float* v) {
  float grad[7]; for (int k=0;k<N_PESOS;k++) grad[k]=0.0f;
  for (int i=0;i<N_SAMPLES;i++) {
    float err = predecir(X_LOCAL[i]) - Y_LOCAL[i];
    for (int j=0;j<N_FEATURES;j++) grad[j] += err*X_LOCAL[i][j];
    grad[N_FEATURES] += err;
  }
  for (int k=0;k<N_PESOS;k++) grad[k] /= (float)N_SAMPLES;
  for (int k=0;k<N_PESOS;k++) { v[k]=g_beta*v[k]-g_lr*grad[k]; w[k]+=v[k]; }
}
float calcular_mse() {
  float s=0.0f;
  for (int i=0;i<N_SAMPLES;i++){ float e=predecir(X_LOCAL[i])-Y_LOCAL[i]; s+=e*e; }
  return s/(float)N_SAMPLES;
}

void publicarAnnounce() {
  JsonDocument d;
  d["node"]=NODE_ID; d["mac"]=WiFi.macAddress(); d["ip"]=WiFi.localIP().toString();
  d["n"]=N_SAMPLES; d["heap"]=ESP.getFreeHeap(); d["rssi"]=WiFi.RSSI();
  d["fw"]=FW_VER; d["lr"]=g_lr; d["beta"]=g_beta; d["epocas"]=g_epocas; d["mode"]=g_mode;
  char b[256]; size_t n=serializeJson(d,b,sizeof(b));
  mqtt.publish(T_ANNOUNCE,(const uint8_t*)b,n,false);
}

void gossipEnviar() {
  if (g_npeers==0) return;
  int p=-1;
  for (int intento=0; intento<5; intento++) {
    int cand = g_peers[random(0, g_npeers)];
    if (cand != NODE_ID) { p = cand; break; }
  }
  if (p < 0) return;
  char topic[24]; snprintf(topic,sizeof(topic),"gossip/inbox/%d",p);
  JsonDocument d; d["from"]=NODE_ID;
  JsonArray wa=d["w"].to<JsonArray>(); for (int k=0;k<N_PESOS;k++) wa.add(w[k]);
  char b[400]; size_t n=serializeJson(d,b,sizeof(b));
  mqtt.publish(topic,(const uint8_t*)b,n,false);
}
void gossipReporte() {
  JsonDocument d; d["node"]=NODE_ID; d["mse"]=calcular_mse(); d["exch"]=exch;
  d["heap"]=ESP.getFreeHeap(); d["rssi"]=WiFi.RSSI();
  JsonArray wa=d["w"].to<JsonArray>(); for (int k=0;k<N_PESOS;k++) wa.add(w[k]);
  char b[640]; size_t n=serializeJson(d,b,sizeof(b));
  mqtt.publish(T_GREPORT,(const uint8_t*)b,n,false);
}

void onMessage(char* topic, byte* payload, unsigned int len) {
  String t = String(topic);

  if (t == g_inbox) {                          // gossip: llego un vecino -> fusionar
    JsonDocument d; if (deserializeJson(d,payload,len)) return;
    JsonArray wa=d["w"].as<JsonArray>(); int k=0; float wp[7];
    for (JsonVariant v : wa) { if (k<N_PESOS) wp[k++]=v.as<float>(); }
    for (int i=0;i<N_PESOS;i++) w[i]=(w[i]+wp[i])*0.5f;
    exch++;
    return;
  }
  if (t == T_DISCOVER) { publicarAnnounce(); return; }

  if (t == T_MODE) {
    JsonDocument d; if (deserializeJson(d,payload,len)) return;
    String m = d["mode"] | "fedavg";
    g_mode = (m=="gossip") ? 2 : (m=="idle" ? 0 : 1);
    if (!d["t_gossip"].isNull()) g_tgossip = d["t_gossip"].as<unsigned long>();
    if (!d["report"].isNull())   g_report  = d["report"].as<unsigned long>();
    if (!d["peers"].isNull()) {
      g_npeers = 0;
      for (JsonVariant v : d["peers"].as<JsonArray>())
        if (g_npeers < 16) g_peers[g_npeers++] = v.as<int>();
    }
    if (g_mode==2) { for (int k=0;k<N_PESOS;k++) v_g[k]=0.0f; exch=0; }
    Serial.printf("[nodo %d] modo=%d peers=%d\n", NODE_ID, g_mode, g_npeers);
    publicarAnnounce();
    return;
  }
  if (t == T_CONFIG) {
    JsonDocument d; if (deserializeJson(d,payload,len)) return;
    if (!d["lr"].isNull())     g_lr=d["lr"].as<float>();
    if (!d["beta"].isNull())   g_beta=d["beta"].as<float>();
    if (!d["epocas"].isNull()) g_epocas=d["epocas"].as<int>();
    publicarAnnounce(); return;
  }
  if (t == T_CMD) {
    JsonDocument d; if (deserializeJson(d,payload,len)) return;
    int dest=d["node"]|-1; if (dest!=-1 && dest!=NODE_ID) return;
    String cmd=d["cmd"]|"";
    if (cmd=="reboot"){ delay(150); ESP.restart(); }
    if (cmd=="reset") { for (int k=0;k<N_PESOS;k++) w[k]=0.0f; }
    return;
  }
  if (t == T_GLOBAL) {                          // Config A
    if (g_mode != 1) return;                    // en gossip se ignora al maestro
    JsonDocument d; if (deserializeJson(d,payload,len)) return;
    if (d["stop"] | false) { Serial.println("[nodo] fin"); return; }
    ronda_rx = d["round"] | 0;
    JsonArray wa=d["w"].as<JsonArray>(); int k=0;
    for (JsonVariant v : wa) { if (k<N_PESOS) w_rx[k++]=v.as<float>(); }
    pendiente = true;
  }
}

void conectarWiFi() {
  WiFi.mode(WIFI_STA); WiFi.begin(WIFI_SSID,WIFI_PASS);
  Serial.print("[nodo] Wi-Fi");
  while (WiFi.status()!=WL_CONNECTED){ delay(400); Serial.print("."); }
  Serial.printf(" OK %s\n", WiFi.localIP().toString().c_str());
}
void iniciarOTA() {
  char host[24]; snprintf(host,sizeof(host),"esp32-nodo-%d",NODE_ID);
  ArduinoOTA.setHostname(host); ArduinoOTA.setPassword(OTA_PASS);
  ArduinoOTA.onStart([](){ Serial.println("[nodo] OTA..."); });
  ArduinoOTA.begin();
}
void conectarMQTT() {
  mqtt.setServer(BROKER_IP,BROKER_PORT); mqtt.setBufferSize(1024); mqtt.setCallback(onMessage);
  char cid[24]; snprintf(cid,sizeof(cid),"esp32-nodo-%d",NODE_ID);
  while (!mqtt.connected()) {
    Serial.print("[nodo] MQTT...");
    if (mqtt.connect(cid)) {
      Serial.println(" OK");
      mqtt.subscribe(T_DISCOVER,1); mqtt.subscribe(T_CONFIG,1); mqtt.subscribe(T_CMD,1);
      mqtt.subscribe(T_MODE,1);     mqtt.subscribe(T_GLOBAL,1);
      mqtt.subscribe(g_inbox.c_str(),1);        // buzon gossip propio
      publicarAnnounce();
    } else { Serial.printf(" rc=%d\n",mqtt.state()); delay(2000); }
  }
}

void setup() {
  Serial.begin(115200); delay(300);
  randomSeed(esp_random());
  g_inbox = String("gossip/inbox/") + String(NODE_ID);
  for (int k=0;k<N_PESOS;k++){ w[k]=0.0f; v_g[k]=0.0f; }
  conectarWiFi(); iniciarOTA(); conectarMQTT();
}

void loop() {
  ArduinoOTA.handle();
  if (!mqtt.connected()) conectarMQTT();
  mqtt.loop();

  if (millis()-ult_heartbeat > HEARTBEAT_MS) { ult_heartbeat=millis(); publicarAnnounce(); }

  // ---------- Config A: FedAvg reactivo ----------
  if (pendiente) {
    pendiente=false;
    for (int k=0;k<N_PESOS;k++) w[k]=w_rx[k];
    float v[7]; for (int k=0;k<N_PESOS;k++) v[k]=0.0f;
    unsigned long t0=millis();
    for (int e=0;e<g_epocas;e++) entrenar_una_epoca(v);
    unsigned long train_ms=millis()-t0; float mse=calcular_mse();
    JsonDocument d;
    d["node"]=NODE_ID; d["round"]=ronda_rx; d["n"]=N_SAMPLES;
    d["mse"]=mse; d["rmse"]=sqrtf(mse); d["train_ms"]=train_ms;
    d["heap"]=ESP.getFreeHeap(); d["min_heap"]=ESP.getMinFreeHeap(); d["rssi"]=WiFi.RSSI();
    JsonArray wa=d["w"].to<JsonArray>(); for (int k=0;k<N_PESOS;k++) wa.add(w[k]);
    char b[640]; size_t n=serializeJson(d,b,sizeof(b));
    mqtt.publish(T_UPDATE,(const uint8_t*)b,n,false);
    Serial.printf("[nodo %d] A r%d mse=%.3f %lums\n", NODE_ID, ronda_rx, mse, train_ms);
  }

  // ---------- Config B: gossip autonomo ----------
  if (g_mode == 2) {
    unsigned long now = millis();
    if (now-last_train  > TRAIN_STEP_MS) { last_train=now;  entrenar_una_epoca(v_g); }
    if (now-last_gossip > g_tgossip)     { last_gossip=now; gossipEnviar(); }
    if (now-last_report > g_report)      { last_report=now; gossipReporte(); }
  }
}
