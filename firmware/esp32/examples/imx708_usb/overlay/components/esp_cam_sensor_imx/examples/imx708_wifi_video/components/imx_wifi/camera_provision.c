/* SPDX-License-Identifier: Apache-2.0 */
#include <stdio.h>
#include <string.h>
#include "camera_provision.h"
#include "board_audio.h"
#include "driver/uart.h"
#include "esp_netif.h"
#include "esp_wifi.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "mbedtls/base64.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "sdkconfig.h"

static char s_ssid[33], s_password[65];
static bool s_initialized;
static esp_err_t s_nvs_error = ESP_ERR_INVALID_STATE;
static void (*s_video_callback)(bool enabled);
static void (*s_image_callback)(const char *command);

void camera_video_register(void (*callback)(bool enabled)) { s_video_callback = callback; }
void camera_image_register(void (*callback)(const char *command)) { s_image_callback = callback; }

const char *camera_wifi_ssid(void) { return s_ssid; }
const char *camera_wifi_password(void) { return s_password; }

static bool valid_password(const char *password)
{
    size_t n = strlen(password);
    if (n == 0 || (n >= 8 && n <= 63)) return true;
    if (n != 64) return false;
    for (size_t i = 0; i < n; ++i) {
        char c = password[i];
        if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') ||
              (c >= 'A' && c <= 'F'))) return false;
    }
    return true;
}

static bool decode_field(const char *encoded, char *out, size_t cap)
{
    size_t n = 0;
    if (mbedtls_base64_decode((unsigned char *)out, cap - 1, &n,
            (const unsigned char *)encoded, strlen(encoded)) != 0 || n >= cap) return false;
    out[n] = '\0';
    return memchr(out, '\0', n) == NULL;
}

static void status(void)
{
    printf("CAMERA_STATUS ip=0.0.0.0 configured=%d fw=wtcc-live-19 connected=0 transport=usb baud=4000000 audio=pcm24k mic=pcm24k volume=80\n",
           s_ssid[0] != '\0');
    fflush(stdout);
}

static void command(char *line)
{
    if (strncmp(line, "AUDIO ", 6) == 0) { board_audio_command(line); return; }
    if (strncmp(line, "MIC ", 4) == 0) { board_audio_command(line); return; }
    if (strcmp(line, "STATUS") == 0) { status(); return; }
    if (strncmp(line, "IMAGE ", 6) == 0) {
        if (s_image_callback) s_image_callback(line);
        return;
    }
    if (strcmp(line, "VIDEO ON") == 0 || strcmp(line, "VIDEO OFF") == 0) {
        if (s_video_callback) s_video_callback(strcmp(line, "VIDEO ON") == 0);
        return;
    }
    if (strncmp(line, "CONFIG ", 7) != 0) { printf("CAMERA_COMMAND_ERROR length=%u\n", (unsigned)strlen(line)); fflush(stdout); return; }
    char *ssid_b64 = line + 7;
    char *password_b64 = strchr(ssid_b64, ' ');
    char ssid[33] = {0}, password[65] = {0};
    if (!password_b64) { puts("CAMERA_CONFIG_ERROR invalid_fields"); return; }
    *password_b64++ = '\0';
    if (!decode_field(ssid_b64, ssid, sizeof(ssid)) || !ssid[0] ||
        !decode_field(password_b64, password, sizeof(password)) || !valid_password(password)) {
        puts("CAMERA_CONFIG_ERROR invalid_credentials"); return;
    }
    if (s_nvs_error != ESP_OK) { puts("CAMERA_CONFIG_ERROR nvs_unavailable"); return; }
    nvs_handle_t handle;
    esp_err_t err = nvs_open("camera_wifi", NVS_READWRITE, &handle);
    if (err == ESP_OK) {
        err = nvs_set_str(handle, "ssid", ssid);
        if (err == ESP_OK) err = nvs_set_str(handle, "pass", password);
        if (err == ESP_OK) err = nvs_commit(handle);
        nvs_close(handle);
    }
    /* Never echo credentials, decoded or base64-encoded, to the console. */
    memset(password, 0, sizeof(password));
    if (err != ESP_OK) { puts("CAMERA_CONFIG_ERROR save_failed"); return; }
    puts("CAMERA_CONFIG_SAVED"); fflush(stdout);
    vTaskDelay(pdMS_TO_TICKS(200));
    esp_restart();
}

static void serial_task(void *unused)
{
    (void)unused;
    char line[1536]; size_t n = 0; bool discard = false;
    for (;;) {
        uint8_t c;
        if (uart_read_bytes(CONFIG_ESP_CONSOLE_UART_NUM, &c, 1, pdMS_TO_TICKS(200)) <= 0) continue;
        if (c == '\r') continue;
        if (c == '\n') {
            if (discard) { puts("CAMERA_COMMAND_ERROR overflow"); fflush(stdout); }
            if (!discard && n) { line[n] = '\0'; command(line); }
            memset(line, 0, sizeof(line)); n = 0; discard = false;
        } else if (n + 1 < sizeof(line) && !discard) line[n++] = (char)c;
        else discard = true;
    }
}

esp_err_t camera_provision_init(void)
{
    if (s_initialized) return s_nvs_error;
    s_initialized = true;
    s_nvs_error = nvs_flash_init();
    if (s_nvs_error == ESP_OK) {
        nvs_handle_t handle;
        if (nvs_open("camera_wifi", NVS_READONLY, &handle) == ESP_OK) {
            size_t ssid_len = sizeof(s_ssid), password_len = sizeof(s_password);
            esp_err_t a = nvs_get_str(handle, "ssid", s_ssid, &ssid_len);
            esp_err_t b = nvs_get_str(handle, "pass", s_password, &password_len);
            nvs_close(handle);
            if (a != ESP_OK || b != ESP_OK || !valid_password(s_password)) {
                memset(s_ssid, 0, sizeof(s_ssid)); memset(s_password, 0, sizeof(s_password));
            }
        }
    }
    const uart_config_t config = {
        .baud_rate = CONFIG_ESP_CONSOLE_UART_BAUDRATE,
        .data_bits = UART_DATA_8_BITS, .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1, .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    esp_err_t err = uart_driver_install(CONFIG_ESP_CONSOLE_UART_NUM, 8192, 0, 0, NULL, 0);
    if (err == ESP_OK) err = uart_param_config(CONFIG_ESP_CONSOLE_UART_NUM, &config);
    /* At 4 Mbaud a 120-byte FIFO threshold leaves almost no ISR headroom.
     * Request service after 32 bytes, with a short tail timeout. */
    if (err == ESP_OK) err = uart_set_rx_full_threshold(CONFIG_ESP_CONSOLE_UART_NUM, 32);
    if (err == ESP_OK) err = uart_set_rx_timeout(CONFIG_ESP_CONSOLE_UART_NUM, 2);
    if (err == ESP_OK && xTaskCreate(serial_task, "camera_config", 8192, NULL, 4, NULL) != pdPASS) {
        err = ESP_ERR_NO_MEM;
    }
    if (err != ESP_OK) { printf("CAMERA_UART_ERROR %s\n", esp_err_to_name(err)); return err; }
    printf("CAMERA_CONFIG_READY configured=%d\n", s_ssid[0] != '\0');
    return s_nvs_error;
}
