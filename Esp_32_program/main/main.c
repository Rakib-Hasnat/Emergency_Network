/*
 * ================================================================
 *  emergency_node.c  —  Emergency Communication Network Node
 *  ESP-IDF v5.x  |  AP+STA Proxy  |  Self-Healing Reconnect
 *
 *  BEFORE FLASHING: change NODE_ID to 1, 2, or 3
 *
 *  Node 1: SSID=EmergencyNet_1  IP=192.168.10.1  (battery monitor)
 *  Node 2: SSID=EmergencyNet_2  IP=192.168.11.1
 *  Node 3: SSID=EmergencyNet_3  IP=192.168.12.1
 *
 *  Pi hotspot SSID : EmergencyPi   password: emergency123
 *  Pi server       : http://192.168.4.1:5000
 *
 *  CMakeLists.txt REQUIRES:
 *    esp_wifi esp_event nvs_flash esp_netif
 *    esp_http_server esp_http_client esp_adc
 * ================================================================ */

#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_log.h"
#include "nvs_flash.h"
#include "esp_netif.h"
#include "esp_http_server.h"
#include "esp_http_client.h"
#include "esp_adc/adc_oneshot.h"

/* ================================================================
 *  CHANGE THIS BEFORE FLASHING  (1, 2, or 3)
 * ================================================================ */
#define NODE_ID  1

/* ================================================================
 *  PER-NODE CONFIG  — derived automatically from NODE_ID
 * ================================================================ */
#if NODE_ID == 1
  #define AP_SSID        "EmergencyNet_1"
  #define AP_IP_ADDR     "192.168.10.1"
  #define AP_IP_BYTE     10
  #define BATTERY_ENABLE 1   /* only node 1 has the battery circuit */

#elif NODE_ID == 2
  #define AP_SSID        "EmergencyNet_2"
  #define AP_IP_ADDR     "192.168.11.1"
  #define AP_IP_BYTE     11
  #define BATTERY_ENABLE 0

#elif NODE_ID == 3
  #define AP_SSID        "EmergencyNet_3"
  #define AP_IP_ADDR     "192.168.12.1"
  #define AP_IP_BYTE     12
  #define BATTERY_ENABLE 0

#else
  #error "NODE_ID must be 1, 2, or 3"
#endif

/* ================================================================
 *  SHARED CONFIG
 * ================================================================ */
#define AP_PASS           "emergency123"
#define AP_MAX_CONN       4

#define PI_SSID           "EmergencyPi"
#define PI_PASS           "emergency123"
#define PI_BASE_URL       "http://192.168.4.1:5000"

#define WIFI_CONNECTED_BIT  BIT0
#define MAX_RECONNECT       10      /* attempts before 30s cool-down */

/* ================================================================
 *  BATTERY CONFIG  (GPIO34, 10k+10k divider, Li-ion)
 * ================================================================ */
#define BATT_ADC_CHANNEL   ADC_CHANNEL_6   /* GPIO34 = ADC1_CH6 */
#define BATT_DIVIDER_RATIO 2.0f
#define BATT_REF_V         3.3f
#define BATT_ADC_MAX       4095.0f
#define BATT_FULL_V        4.2f
#define BATT_EMPTY_V       3.3f
#define BATT_AVG_SAMPLES   5
#define BATT_READ_INTERVAL_MS  10000

/* ================================================================
 *  HEARTBEAT CONFIG
 * ================================================================ */
#define HEARTBEAT_INTERVAL_MS  30000   /* POST to Pi every 30 seconds */

/* ================================================================
 *  GLOBALS
 * ================================================================ */
static const char          *TAG = "NODE";
static EventGroupHandle_t   s_wifi_evtgrp;

#if BATTERY_ENABLE
static adc_oneshot_unit_handle_t s_adc_handle;
#endif

/* ================================================================
 *  HELPER — simple POST to Pi, fire and forget
 *  Returns ESP_OK on HTTP success, ESP_FAIL otherwise
 * ================================================================ */
static esp_err_t pi_post_json(const char *path, const char *body)
{
    /* Only attempt if STA is connected */
    EventBits_t bits = xEventGroupWaitBits(
        s_wifi_evtgrp, WIFI_CONNECTED_BIT, pdFALSE, pdFALSE, 0);
    if (!(bits & WIFI_CONNECTED_BIT)) return ESP_FAIL;

    char url[128];
    snprintf(url, sizeof(url), "%s%s", PI_BASE_URL, path);

    esp_http_client_config_t cfg = {
        .url        = url,
        .method     = HTTP_METHOD_POST,
        .timeout_ms = 5000,
    };
    esp_http_client_handle_t cl = esp_http_client_init(&cfg);
    if (!cl) return ESP_FAIL;

    esp_http_client_set_header(cl, "Content-Type", "application/json");
    esp_http_client_set_post_field(cl, body, strlen(body));
    esp_err_t ret = esp_http_client_perform(cl);
    esp_http_client_cleanup(cl);
    return ret;
}

/* ================================================================
 *  BATTERY MONITORING  (compiled only on node 1)
 * ================================================================ */
#if BATTERY_ENABLE

static void battery_init(void)
{
    adc_oneshot_unit_init_cfg_t unit_cfg = { .unit_id = ADC_UNIT_1 };
    ESP_ERROR_CHECK(adc_oneshot_new_unit(&unit_cfg, &s_adc_handle));

    adc_oneshot_chan_cfg_t ch_cfg = {
        .bitwidth = ADC_BITWIDTH_12,
        .atten    = ADC_ATTEN_DB_12,   /* 0–3.3 V input range */
    };
    ESP_ERROR_CHECK(adc_oneshot_config_channel(s_adc_handle, BATT_ADC_CHANNEL, &ch_cfg));
    ESP_LOGI(TAG, "Battery ADC ready — GPIO34, 10k+10k divider");
}

static float battery_read_voltage(void)
{
    int raw = 0;
    if (adc_oneshot_read(s_adc_handle, BATT_ADC_CHANNEL, &raw) != ESP_OK) {
        ESP_LOGE(TAG, "ADC read error");
        return 0.0f;
    }
    float v_pin = (raw * BATT_REF_V) / BATT_ADC_MAX;
    return v_pin * BATT_DIVIDER_RATIO;   /* actual battery voltage */
}

static float battery_percentage(float v)
{
    float pct = (v - BATT_EMPTY_V) / (BATT_FULL_V - BATT_EMPTY_V) * 100.0f;
    if (pct > 100.0f) pct = 100.0f;
    if (pct <   0.0f) pct =   0.0f;
    return pct;
}

static void battery_task(void *arg)
{
    battery_init();

    float samples[BATT_AVG_SAMPLES];
    for (int i = 0; i < BATT_AVG_SAMPLES; i++) {
        samples[i] = battery_read_voltage();
        vTaskDelay(pdMS_TO_TICKS(20));
    }
    int idx = 0;

    while (1) {
        samples[idx] = battery_read_voltage();
        idx = (idx + 1) % BATT_AVG_SAMPLES;

        float avg = 0;
        for (int i = 0; i < BATT_AVG_SAMPLES; i++) avg += samples[i];
        avg /= BATT_AVG_SAMPLES;

        float pct = battery_percentage(avg);
        ESP_LOGI(TAG, "--- Battery: %.2fV  %.1f%% ---", avg, pct);

        if      (avg > 4.0f) ESP_LOGI(TAG, "Status: FULL");
        else if (avg > 3.7f) ESP_LOGI(TAG, "Status: GOOD");
        else if (avg > 3.5f) ESP_LOGI(TAG, "Status: OK");
        else if (avg > 3.3f) ESP_LOGW(TAG, "Status: LOW");
        else                 ESP_LOGE(TAG, "Status: CRITICAL — RECHARGE NOW");

        /* POST battery reading to Pi so it appears in the web UI */
        char body[128];
        snprintf(body, sizeof(body),
                 "{\"node\":%d,\"voltage\":%.2f,\"percent\":%.1f}",
                 NODE_ID, avg, pct);
        if (pi_post_json("/battery", body) == ESP_OK) {
            ESP_LOGI(TAG, "Battery posted to Pi");
        } else {
            ESP_LOGW(TAG, "Battery POST failed — Pi unreachable");
        }

        vTaskDelay(pdMS_TO_TICKS(BATT_READ_INTERVAL_MS));
    }
}

#endif /* BATTERY_ENABLE */

/* ================================================================
 *  HEARTBEAT TASK  —  runs on ALL nodes every 30 seconds
 *  POSTs node ID and SSID to /heartbeat on the Pi
 *  Pi uses last-seen time to show ONLINE / OFFLINE in the UI
 * ================================================================ */
static void heartbeat_task(void *arg)
{
    /* Stagger startup so all nodes don't POST at the exact same time */
    vTaskDelay(pdMS_TO_TICKS(5000 + (NODE_ID * 2000)));

    while (1) {
        char body[128];
        snprintf(body, sizeof(body),
                 "{\"node\":%d,\"ssid\":\"%s\",\"ip\":\"%s\"}",
                 NODE_ID, AP_SSID, AP_IP_ADDR);

        if (pi_post_json("/heartbeat", body) == ESP_OK) {
            ESP_LOGI(TAG, "[HEARTBEAT] Sent to Pi OK");
        } else {
            ESP_LOGW(TAG, "[HEARTBEAT] POST failed — not connected yet");
        }

        vTaskDelay(pdMS_TO_TICKS(HEARTBEAT_INTERVAL_MS));
    }
}

/* ================================================================
 *  WIFI EVENT HANDLER  —  self-healing reconnect logic
 * ================================================================ */
static void wifi_event_handler(void *arg, esp_event_base_t base,
                               int32_t id, void *data)
{
    static int s_reconnects = 0;

    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        ESP_LOGI(TAG, "STA started — connecting to Pi...");
        esp_wifi_connect();
    }

    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        wifi_event_sta_disconnected_t *ev = (wifi_event_sta_disconnected_t *)data;
        ESP_LOGW(TAG, "[SELF-HEAL] Disconnected (reason %d) — reconnecting...", ev->reason);
        xEventGroupClearBits(s_wifi_evtgrp, WIFI_CONNECTED_BIT);

        s_reconnects++;
        if (s_reconnects >= MAX_RECONNECT) {
            ESP_LOGW(TAG, "[SELF-HEAL] %d failures — cooling down 30 s", MAX_RECONNECT);
            s_reconnects = 0;
            vTaskDelay(pdMS_TO_TICKS(30000));
        } else {
            vTaskDelay(pdMS_TO_TICKS(3000));
        }
        esp_wifi_connect();
    }

    if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *ev = (ip_event_got_ip_t *)data;
        ESP_LOGI(TAG, "[SELF-HEAL] Connected — IP: " IPSTR, IP2STR(&ev->ip_info.ip));
        xEventGroupSetBits(s_wifi_evtgrp, WIFI_CONNECTED_BIT);
        s_reconnects = 0;
    }
}

/* ================================================================
 *  WIFI INIT
 * ================================================================ */
static void wifi_init(void)
{
    nvs_flash_erase();   /* one-time clear of stale mesh/WPA2 cache */
    nvs_flash_init();

    esp_netif_init();
    esp_event_loop_create_default();
    s_wifi_evtgrp = xEventGroupCreate();

    /* AP netif — configure subnet to avoid conflict with Pi (192.168.4.x) */
    esp_netif_t *ap_netif = esp_netif_create_default_wifi_ap();
    esp_netif_create_default_wifi_sta();

    esp_netif_dhcps_stop(ap_netif);
    esp_netif_ip_info_t ip_info;
    IP4_ADDR(&ip_info.ip,      192, 168, AP_IP_BYTE, 1);
    IP4_ADDR(&ip_info.gw,      192, 168, AP_IP_BYTE, 1);
    IP4_ADDR(&ip_info.netmask, 255, 255, 255, 0);
    esp_netif_set_ip_info(ap_netif, &ip_info);
    esp_netif_dhcps_start(ap_netif);
    ESP_LOGI(TAG, "AP IP: %s", AP_IP_ADDR);

    wifi_init_config_t wcfg = WIFI_INIT_CONFIG_DEFAULT();
    esp_wifi_init(&wcfg);
    esp_wifi_set_storage(WIFI_STORAGE_RAM);  /* no stale PMK reuse from flash */

    /* AP config */
    wifi_config_t ap_cfg = {
        .ap = {
            .ssid_len      = strlen(AP_SSID),
            .max_connection = AP_MAX_CONN,
            .authmode      = WIFI_AUTH_WPA2_PSK,
        }
    };
    memcpy(ap_cfg.ap.ssid,     AP_SSID, strlen(AP_SSID));
    memcpy(ap_cfg.ap.password, AP_PASS, strlen(AP_PASS));

    /* STA config — connects to Pi */
    wifi_config_t sta_cfg = {0};
    memcpy(sta_cfg.sta.ssid,     PI_SSID, strlen(PI_SSID));
    memcpy(sta_cfg.sta.password, PI_PASS, strlen(PI_PASS));
    sta_cfg.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    sta_cfg.sta.pmf_cfg.capable  = false;
    sta_cfg.sta.pmf_cfg.required = false;

    esp_wifi_set_mode(WIFI_MODE_APSTA);
    esp_wifi_set_config(WIFI_IF_AP,  &ap_cfg);
    esp_wifi_set_config(WIFI_IF_STA, &sta_cfg);

    esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID,    &wifi_event_handler, NULL);
    esp_event_handler_register(IP_EVENT,   IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL);

    esp_wifi_start();
    esp_wifi_set_ps(WIFI_PS_NONE);   /* disable power save — reduces latency */

    ESP_LOGI(TAG, "WiFi init done");
}

/* ================================================================
 *  HTTP PROXY HANDLER
 * ================================================================ */
static esp_err_t proxy_handler(httpd_req_t *req)
{
    /* Block if not connected to Pi */
    EventBits_t bits = xEventGroupWaitBits(
        s_wifi_evtgrp, WIFI_CONNECTED_BIT, pdFALSE, pdFALSE, pdMS_TO_TICKS(1000));
    if (!(bits & WIFI_CONNECTED_BIT)) {
        httpd_resp_set_status(req, "503 Service Unavailable");
        httpd_resp_send(req, "Node not connected to Pi — self-healing in progress",
                        HTTPD_RESP_USE_STRLEN);
        return ESP_FAIL;
    }

    /* Build Pi URL */
    char url[600];
    snprintf(url, sizeof(url), "%s%s", PI_BASE_URL, req->uri);
    ESP_LOGI(TAG, "Proxy → %s", url);

    esp_http_client_config_t cfg = {
        .url        = url,
        .method     = (req->method == HTTP_GET) ? HTTP_METHOD_GET : HTTP_METHOD_POST,
        .timeout_ms = 20000,
    };
    esp_http_client_handle_t cl = esp_http_client_init(&cfg);
    if (!cl) {
        httpd_resp_set_status(req, "502 Bad Gateway");
        httpd_resp_send(req, "Proxy init failed", HTTPD_RESP_USE_STRLEN);
        return ESP_FAIL;
    }

    /* Forward Content-Type on POST */
    if (req->method == HTTP_POST) {
        char ct[256] = {0};
        if (httpd_req_get_hdr_value_str(req, "Content-Type", ct, sizeof(ct)) == ESP_OK && ct[0])
            esp_http_client_set_header(cl, "Content-Type", ct);
    }

    int body_len = (req->method == HTTP_POST) ? (int)req->content_len : 0;
    if (esp_http_client_open(cl, body_len) != ESP_OK) {
        esp_http_client_cleanup(cl);
        httpd_resp_set_status(req, "502 Bad Gateway");
        httpd_resp_send(req, "Cannot reach Pi", HTTPD_RESP_USE_STRLEN);
        return ESP_FAIL;
    }

    /* Stream POST body to Pi */
    if (req->method == HTTP_POST) {
        char buf[1024];
        int rem = body_len;
        while (rem > 0) {
            int n = httpd_req_recv(req, buf, (rem < (int)sizeof(buf)) ? rem : (int)sizeof(buf));
            if (n <= 0) { esp_http_client_cleanup(cl); return ESP_FAIL; }
            esp_http_client_write(cl, buf, n);
            rem -= n;
        }
    }

    /* Read Pi response headers */
    esp_http_client_fetch_headers(cl);
    int status = esp_http_client_get_status_code(cl);

    char status_line[32];
    snprintf(status_line, sizeof(status_line), "%d OK", status);
    httpd_resp_set_status(req, status_line);
    httpd_resp_set_type(req, strstr(req->uri, "/alerts") ? "application/json" : "text/html");

    /* Stream Pi response back to client */
    char chunk[1024];
    int n;
    while ((n = esp_http_client_read(cl, chunk, sizeof(chunk))) > 0) {
        if (httpd_resp_send_chunk(req, chunk, n) != ESP_OK) {
            esp_http_client_cleanup(cl);
            return ESP_FAIL;
        }
    }
    httpd_resp_send_chunk(req, NULL, 0);   /* end chunked response */
    esp_http_client_cleanup(cl);
    return ESP_OK;
}

/* ================================================================
 *  HTTP SERVER
 * ================================================================ */
static void start_server(void)
{
    httpd_config_t hcfg       = HTTPD_DEFAULT_CONFIG();
    hcfg.stack_size            = 8192;
    hcfg.lru_purge_enable      = true;
    hcfg.uri_match_fn          = httpd_uri_match_wildcard;
    hcfg.max_uri_handlers      = 4;
    hcfg.server_port           = 80;

    httpd_handle_t server = NULL;
    if (httpd_start(&server, &hcfg) != ESP_OK) {
        ESP_LOGE(TAG, "httpd_start failed"); return;
    }

    httpd_uri_t get_h  = { .uri = "/*", .method = HTTP_GET,  .handler = proxy_handler };
    httpd_uri_t post_h = { .uri = "/*", .method = HTTP_POST, .handler = proxy_handler };
    httpd_register_uri_handler(server, &get_h);
    httpd_register_uri_handler(server, &post_h);

    ESP_LOGI(TAG, "HTTP proxy server started on port 80");
}

/* ================================================================
 *  APP MAIN
 * ================================================================ */
void app_main(void)
{
    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, " Emergency Node  ID=%d", NODE_ID);
    ESP_LOGI(TAG, " AP SSID : %s", AP_SSID);
    ESP_LOGI(TAG, " AP IP   : %s", AP_IP_ADDR);
    ESP_LOGI(TAG, " Pi SSID : %s  (self-healing reconnect)", PI_SSID);
    ESP_LOGI(TAG, " Battery : %s", BATTERY_ENABLE ? "YES (GPIO34)" : "NO");
    ESP_LOGI(TAG, "========================================");

    wifi_init();

    /* Give WiFi stack time to start before launching server */
    vTaskDelay(pdMS_TO_TICKS(3000));

    start_server();

#if BATTERY_ENABLE
    xTaskCreate(battery_task, "battery", 3072, NULL, 4, NULL);
#endif

    /* Heartbeat runs on ALL nodes — Pi uses this to show online/offline */
    xTaskCreate(heartbeat_task, "heartbeat", 3072, NULL, 3, NULL);

    ESP_LOGI(TAG, "========================================");
    ESP_LOGI(TAG, " READY");
    ESP_LOGI(TAG, " Connect phone to: %s", AP_SSID);
    ESP_LOGI(TAG, " Password        : %s", AP_PASS);
    ESP_LOGI(TAG, " Open browser    : http://%s", AP_IP_ADDR);
    ESP_LOGI(TAG, "========================================");
}