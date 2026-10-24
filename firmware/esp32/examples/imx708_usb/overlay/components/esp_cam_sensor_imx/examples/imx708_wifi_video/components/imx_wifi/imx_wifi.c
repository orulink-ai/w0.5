/*
 * SPDX-FileCopyrightText: 2026 esp_cam_sensor_imx contributors
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * See imx_wifi.h. The reasoning behind the non-obvious choices here was worked
 * out in examples/c6_wifi_sta and is written up in docs/esp32c6-bringup.md.
 */
#include <string.h>
#include "imx_wifi.h"
#include "camera_provision.h"
#include "esp_log.h"
#include "esp_idf_version.h"
#include "esp_wifi.h"
#include "esp_netif.h"
#include "esp_event.h"
#include "nvs_flash.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/timers.h"

static const char *TAG = "imx_wifi";

#define CONNECT_TIMEOUT_MS 30000

#define CONNECTED_BIT BIT0
#define FAILED_BIT    BIT1

static EventGroupHandle_t s_events;
static unsigned s_retries;
static TimerHandle_t s_retry_timer;
static uint8_t s_last_reason;
static esp_netif_t *s_netif;
static char s_ip[16];

static void reconnect_timer(TimerHandle_t timer)
{
    (void)timer;
    (void)esp_wifi_connect();
}

static const char *reason_hint(uint8_t reason)
{
    switch (reason) {
    case WIFI_REASON_NO_AP_FOUND:
        return "SSID not seen. Check spelling, and remember the C6 is "
               "2.4 GHz only - a 5 GHz-only SSID is invisible to it";
    case WIFI_REASON_AUTH_FAIL:
    case WIFI_REASON_HANDSHAKE_TIMEOUT:
    case WIFI_REASON_4WAY_HANDSHAKE_TIMEOUT:
        return "authentication failed - almost always a wrong password";
    case WIFI_REASON_ASSOC_FAIL:
        return "the AP refused the association (MAC filtering? band steering?)";
    case WIFI_REASON_AUTH_EXPIRE:
#if ESP_IDF_VERSION >= ESP_IDF_VERSION_VAL(6, 0, 0)
    case WIFI_REASON_DISASSOC_DUE_TO_INACTIVITY:
#else
    case WIFI_REASON_ASSOC_EXPIRE:
#endif
        return "the AP dropped us after associating - weak signal, or the AP "
               "aged the session out";
    default:
        return "see WIFI_REASON_* in esp_wifi_types.h";
    }
}

static void on_wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (id == WIFI_EVENT_STA_START) {
        /* From the event, not from the caller: connecting before the driver has
         * finished starting returns ESP_ERR_WIFI_NOT_STARTED. */
        esp_wifi_connect();
        return;
    }

    if (id == WIFI_EVENT_STA_DISCONNECTED) {
        wifi_event_sta_disconnected_t *e = (wifi_event_sta_disconnected_t *)data;
        s_last_reason = e->reason;
        xEventGroupClearBits(s_events, CONNECTED_BIT);
        s_retries++;
        ESP_LOGW(TAG, "disconnected, reason %u - retry %u: %s",
                 e->reason, s_retries, reason_hint(e->reason));
        (void)xTimerReset(s_retry_timer, 0);
    }
}

static void on_ip_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    if (id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *e = (ip_event_got_ip_t *)data;
        snprintf(s_ip, sizeof(s_ip), IPSTR, IP2STR(&e->ip_info.ip));
        s_retries = 0;
        xEventGroupClearBits(s_events, FAILED_BIT);
        printf("CAMERA_IP %s\n", s_ip);
        ESP_LOGI(TAG, "got IP %s  gateway " IPSTR, s_ip, IP2STR(&e->ip_info.gw));
        xEventGroupSetBits(s_events, CONNECTED_BIT);
    }
}

bool imx_wifi_have_credentials(void)
{
    return camera_provision_init() == ESP_OK && camera_wifi_ssid()[0] != '\0';
}

static void log_ap_details(void)
{
    wifi_ap_record_t ap;
    if (esp_wifi_sta_get_ap_info(&ap) != ESP_OK) {
        return;
    }
    ESP_LOGI(TAG, "associated with \"%s\"  channel %u  rssi %d dBm  phy %s%s%s%s",
             (const char *)ap.ssid, ap.primary, ap.rssi,
             ap.phy_11b ? "b" : "", ap.phy_11g ? "g" : "",
             ap.phy_11n ? "n" : "", ap.phy_11ax ? "/ax" : "");
}

esp_err_t imx_wifi_connect(char *ip_out, size_t ip_len)
{
    if (!imx_wifi_have_credentials()) {
        ESP_LOGE(TAG, "no saved credentials; use UART CONFIG <base64-ssid> <base64-password>");
        return ESP_ERR_INVALID_STATE;
    }

    esp_err_t err = camera_provision_init();
    if (err != ESP_OK) return err;

    s_events = xEventGroupCreate();
    s_retry_timer = xTimerCreate("wifi_retry", pdMS_TO_TICKS(1000), pdFALSE,
                                 NULL, reconnect_timer);
    if (!s_events || !s_retry_timer) {
        return ESP_ERR_NO_MEM;
    }

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    s_netif = esp_netif_create_default_wifi_sta();

    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        WIFI_EVENT, ESP_EVENT_ANY_ID, &on_wifi_event, NULL, NULL));
    ESP_ERROR_CHECK(esp_event_handler_instance_register(
        IP_EVENT, IP_EVENT_STA_GOT_IP, &on_ip_event, NULL, NULL));

    /* A failure here is the C6 not answering, not a network problem. Report it
     * as such instead of aborting - the distinction is the whole point. */
    wifi_init_config_t init_cfg = WIFI_INIT_CONFIG_DEFAULT();
    err = esp_wifi_init(&init_cfg);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "esp_wifi_init failed: %s - the C6 did not answer. "
                      "Run examples/c6_link_check.", esp_err_to_name(err));
        return ESP_ERR_WIFI_NOT_INIT;
    }

    wifi_config_t sta_cfg = { 0 };
    memcpy(sta_cfg.sta.ssid, camera_wifi_ssid(), strlen(camera_wifi_ssid()));
    memcpy(sta_cfg.sta.password, camera_wifi_password(), strlen(camera_wifi_password()));
    /* threshold.authmode stays at its default (open): raising it to WPA2_PSK,
     * as Espressif's examples do, silently filters weaker APs out and reports
     * it as NO_AP_FOUND, which reads as a missing AP rather than a policy. */
    sta_cfg.sta.sae_pwe_h2e = WPA3_SAE_PWE_BOTH;

    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &sta_cfg));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_LOGI(TAG, "connecting to \"%s\" ...", camera_wifi_ssid());

    EventBits_t bits = xEventGroupWaitBits(s_events, CONNECTED_BIT | FAILED_BIT,
                                           pdFALSE, pdFALSE,
                                           pdMS_TO_TICKS(CONNECT_TIMEOUT_MS));
    if (!(bits & CONNECTED_BIT)) {
        if (bits & FAILED_BIT) {
            ESP_LOGE(TAG, "could not associate. last reason %u: %s",
                     s_last_reason, reason_hint(s_last_reason));
        } else {
            ESP_LOGE(TAG, "timed out after %d ms with no result at all",
                     CONNECT_TIMEOUT_MS);
        }
        return ESP_ERR_TIMEOUT;
    }

    log_ap_details();

    /*
     * Latency and steady throughput over idle power. Power save has the AP
     * buffer traffic between beacons, which turns a stream of frames into
     * bursts - the opposite of what this component exists to carry.
     */
    esp_wifi_set_ps(WIFI_PS_NONE);

    if (ip_out && ip_len) {
        strncpy(ip_out, s_ip, ip_len - 1);
        ip_out[ip_len - 1] = '\0';
    }
    return ESP_OK;
}
