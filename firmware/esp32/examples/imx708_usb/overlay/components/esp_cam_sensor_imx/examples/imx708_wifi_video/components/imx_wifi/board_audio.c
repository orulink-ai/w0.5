/* SPDX-License-Identifier: Apache-2.0 */
/* ES8311 + NS4150B on ESP32-P4-WIFI6. 24 kHz mono PCM over USB UART. */
#include <stdio.h>
#include <string.h>
#include <inttypes.h>
#include "board_audio.h"
#include "board_audio_buffer.h"
#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "driver/i2s_std.h"
#include "driver/uart.h"
#include "sdkconfig.h"
#include "esp_codec_dev.h"
#include "esp_codec_dev_defaults.h"
#include "esp_rom_crc.h"
#include "mbedtls/base64.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"

static esp_codec_dev_handle_t s_dev;
static i2s_chan_handle_t s_tx, s_rx;
static volatile bool s_mic_enabled;
static volatile bool s_playing;
static bool s_attempted;
static bool s_audio_ready;
static bool s_output_muted = true;
static board_audio_buffer_t s_buffer;
static portMUX_TYPE s_buffer_lock = portMUX_INITIALIZER_UNLOCKED;
static SemaphoreHandle_t s_player_done;
static volatile bool s_stop_requested, s_player_failed;
static int16_t s_pcm[480], s_stereo[960];
/* 200 ms absorbs a large video record holding stdout without stopping preview.
 * Keep drain and stop silence sized to the complete DMA cycle. */
#define AUDIO_DMA_DESCRIPTORS 20
#define AUDIO_DMA_FRAMES 240
static const int16_t s_silence[AUDIO_DMA_DESCRIPTORS * AUDIO_DMA_FRAMES * 2] = {0};

bool board_audio_is_active(void) { return s_mic_enabled || s_playing; }

/* Only the playback task (or the synchronous diagnostic tone while idle)
 * changes output state. Avoid two I2C transactions for every 20 ms packet. */
static void output_mute(bool muted)
{
    if (s_output_muted != muted) {
        esp_codec_dev_set_out_mute(s_dev, muted);
        s_output_muted = muted;
    }
}

static bool playback_flush(void)
{
    output_mute(true);
    esp_err_t disabled = i2s_channel_disable(s_tx);
    size_t loaded = 0;
    esp_err_t preloaded = i2s_channel_preload_data(s_tx, s_silence, sizeof(s_silence), &loaded);
    esp_err_t enabled = i2s_channel_enable(s_tx);
    return disabled == ESP_OK && preloaded == ESP_OK && enabled == ESP_OK && loaded == sizeof(s_silence);
}

static void playback_task(void *unused)
{
    (void)unused;
    board_audio_packet_t packet;
    int16_t stereo[BOARD_AUDIO_PACKET_SAMPLES * 2];
    for (;;) {
        bool stop, have_packet, drain;
        uint32_t generation;
        portENTER_CRITICAL(&s_buffer_lock);
        stop = s_stop_requested;
        if (stop) s_stop_requested = false;
        generation = s_buffer.generation;
        have_packet = !stop && board_audio_buffer_pop(&s_buffer, &packet);
        drain = !stop && !have_packet && board_audio_buffer_drained(&s_buffer);
        if (drain) s_buffer.ending = false;
        portEXIT_CRITICAL(&s_buffer_lock);
        if (stop) {
            s_player_failed = !playback_flush();
            s_playing = false;
            xSemaphoreGive(s_player_done);
        } else if (have_packet) {
            /* STOP may invalidate an already removed packet. If it arrives
             * during write, STOPPED is delayed until flush removes that DMA. */
            portENTER_CRITICAL(&s_buffer_lock);
            bool current = packet.generation == s_buffer.generation && !s_stop_requested;
            portEXIT_CRITICAL(&s_buffer_lock);
            if (!current) continue;
            for (unsigned i = 0; i < packet.samples; i++) stereo[2*i] = stereo[2*i+1] = packet.pcm[i];
            output_mute(false);
            if (esp_codec_dev_write(s_dev, stereo, packet.samples * 4) != ESP_CODEC_DEV_OK) s_player_failed = true;
        } else if (drain) {
            /* Fill the whole DMA cycle with silence, then allow that cycle to
             * finish. END acknowledges audible completion, not enqueue. */
            if (esp_codec_dev_write(s_dev, (void *)s_silence, sizeof(s_silence)) != ESP_CODEC_DEV_OK) s_player_failed = true;
            vTaskDelay(pdMS_TO_TICKS(210));
            output_mute(true);
            portENTER_CRITICAL(&s_buffer_lock);
            bool current = generation == s_buffer.generation && !s_stop_requested;
            if (current) s_buffer.playing = false;
            portEXIT_CRITICAL(&s_buffer_lock);
            if (current) { s_playing = false; xSemaphoreGive(s_player_done); }
        } else {
            vTaskDelay(1);
        }
    }
}

static bool playback_stop(void)
{
    while (xSemaphoreTake(s_player_done, 0) == pdTRUE) {}
    portENTER_CRITICAL(&s_buffer_lock);
    board_audio_buffer_reset(&s_buffer);
    s_stop_requested = true;
    portEXIT_CRITICAL(&s_buffer_lock);
    return xSemaphoreTake(s_player_done, pdMS_TO_TICKS(2000)) == pdTRUE && !s_player_failed;
}

static bool playback_enqueue(const int16_t *pcm, unsigned samples)
{
    TickType_t deadline = xTaskGetTickCount() + pdMS_TO_TICKS(2000);
    do {
        if (s_player_failed) return false;
        portENTER_CRITICAL(&s_buffer_lock);
        bool accepted = board_audio_buffer_push(&s_buffer, pcm, samples);
        portEXIT_CRITICAL(&s_buffer_lock);
        if (accepted) return true;
        vTaskDelay(1);
    } while ((int32_t)(deadline - xTaskGetTickCount()) > 0);
    return false;
}

static void microphone_task(void *unused)
{
    (void)unused;
    int16_t stereo[960], mono[480];
    unsigned char encoded[1284];
    uint32_t sequence = 0;
    for (;;) {
        if (esp_codec_dev_read(s_dev, stereo, sizeof(stereo)) != ESP_CODEC_DEV_OK) {
            vTaskDelay(pdMS_TO_TICKS(20)); continue;
        }
        if (!s_mic_enabled) continue;
        for (size_t i = 0; i < 480; i++) mono[i] = stereo[2*i];
        size_t length = 0;
        if (mbedtls_base64_encode(encoded, sizeof(encoded), &length, (const unsigned char *)mono, sizeof(mono)) == 0) {
            encoded[length] = 0;
            printf("MIC_DATA %" PRIu32 " %s\n", ++sequence, encoded);
            fflush(stdout);
        }
    }
}

static esp_err_t audio_init(void)
{
    if (s_dev) return s_audio_ready ? ESP_OK : ESP_ERR_INVALID_STATE;
    if (s_attempted) return ESP_ERR_INVALID_STATE;
    s_attempted = true;
    gpio_config_t pa = {.pin_bit_mask = 1ULL << 53, .mode = GPIO_MODE_OUTPUT};
    if (gpio_config(&pa) != ESP_OK) return ESP_FAIL;
    gpio_set_level(53, 0);
    i2c_master_bus_handle_t bus;
    if (i2c_master_get_bus_handle(0, &bus) != ESP_OK) return ESP_FAIL;
    if (i2c_master_probe(bus, 0x18, 500) != ESP_OK) return ESP_ERR_NOT_FOUND;
    i2s_chan_config_t chan = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    chan.auto_clear = true;
    chan.dma_desc_num = AUDIO_DMA_DESCRIPTORS;
    chan.dma_frame_num = AUDIO_DMA_FRAMES;
    if (i2s_new_channel(&chan, &s_tx, &s_rx) != ESP_OK) return ESP_FAIL;
    i2s_std_config_t cfg = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(24000),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {.mclk = 13, .bclk = 12, .ws = 10, .dout = 9, .din = 11},
    };
    if (i2s_channel_init_std_mode(s_tx, &cfg) != ESP_OK || i2s_channel_enable(s_tx) != ESP_OK) return ESP_FAIL;
    if (i2s_channel_init_std_mode(s_rx, &cfg) != ESP_OK || i2s_channel_enable(s_rx) != ESP_OK) return ESP_FAIL;
    audio_codec_i2c_cfg_t ctrl_cfg = {.port = 0, .addr = ES8311_CODEC_DEFAULT_ADDR, .bus_handle = bus};
    const audio_codec_ctrl_if_t *ctrl = audio_codec_new_i2c_ctrl(&ctrl_cfg);
    audio_codec_i2s_cfg_t data_cfg = {.port = 0, .tx_handle = s_tx, .rx_handle = s_rx};
    const audio_codec_data_if_t *data = audio_codec_new_i2s_data(&data_cfg);
    const audio_codec_gpio_if_t *gpio = audio_codec_new_gpio();
    if (!ctrl || !data || !gpio) return ESP_ERR_NO_MEM;
    es8311_codec_cfg_t codec_cfg = {
        .ctrl_if = ctrl, .gpio_if = gpio, .codec_mode = ESP_CODEC_DEV_WORK_MODE_BOTH,
        .master_mode = false, .use_mclk = true, .pa_pin = 53,
        .hw_gain = {.pa_voltage = 5.0, .codec_dac_voltage = 3.3}, .mclk_div = 256,
    };
    const audio_codec_if_t *codec = es8311_codec_new(&codec_cfg);
    if (!codec) return ESP_FAIL;
    esp_codec_dev_cfg_t dev_cfg = {.dev_type = ESP_CODEC_DEV_TYPE_IN_OUT, .codec_if = codec, .data_if = data};
    esp_codec_dev_handle_t dev = esp_codec_dev_new(&dev_cfg);
    esp_codec_dev_sample_info_t sample = {.bits_per_sample = 16, .channel = 2, .channel_mask = 3, .sample_rate = 24000};
    if (!dev || esp_codec_dev_open(dev, &sample) != ESP_CODEC_DEV_OK) return ESP_FAIL;
    if (esp_codec_dev_set_out_vol(dev, 80) != ESP_CODEC_DEV_OK) return ESP_FAIL;
    if (esp_codec_dev_set_out_mute(dev, true) != ESP_CODEC_DEV_OK) return ESP_FAIL;
    if (esp_codec_dev_set_in_gain(dev, 30) != ESP_CODEC_DEV_OK) return ESP_FAIL;
    s_dev = dev;
    s_player_done = xSemaphoreCreateBinary();
    if (!s_player_done || xTaskCreate(playback_task, "board_play", 6144, NULL, 6, NULL) != pdPASS) return ESP_ERR_NO_MEM;
    if (xTaskCreate(microphone_task, "board_mic", 8192, NULL, 5, NULL) != pdPASS) return ESP_ERR_NO_MEM;
    s_audio_ready = true;
    return ESP_OK;
}

void board_audio_command(const char *line)
{
    if (strcmp(line, "AUDIO START") == 0) {
        esp_err_t err = audio_init();
        if (err == ESP_OK) puts("AUDIO_READY rate=24000 volume=80");
        else printf("AUDIO_ERROR init=%s\n", esp_err_to_name(err));
    } else if (!s_audio_ready) {
        puts("AUDIO_ERROR not_initialized");
    } else if (strncmp(line, "AUDIO BAUD ", 11) == 0) {
        unsigned rate;
        if (sscanf(line, "AUDIO BAUD %u", &rate) != 1 || (rate != 1000000 && rate != 4000000)) {
            puts("AUDIO_ERROR baud");
        } else {
            printf("AUDIO_BAUD %u\n", rate); fflush(stdout);
            uart_wait_tx_done(CONFIG_ESP_CONSOLE_UART_NUM, pdMS_TO_TICKS(1000));
            uart_set_baudrate(CONFIG_ESP_CONSOLE_UART_NUM, rate);
        }
    } else if (strcmp(line, "MIC START") == 0) {
        s_mic_enabled = true;
        puts("MIC_READY rate=24000 channels=1");
    } else if (strcmp(line, "MIC STOP") == 0) {
        s_mic_enabled = false;
        puts("MIC_STOPPED");
    } else if (strcmp(line, "AUDIO TONE") == 0) {
        if (!playback_stop()) { puts("AUDIO_ERROR stop"); fflush(stdout); return; }
        s_playing = true;
        output_mute(false);
        gpio_set_level(53, 1);
        for (int block = 0; block < 100; block++) {
            for (int i = 0; i < 240; i++) s_stereo[2*i] = s_stereo[2*i+1] = (i % 24 < 12 ? 6000 : -6000);
            esp_codec_dev_write(s_dev, s_stereo, 960);
        }
        esp_codec_dev_write(s_dev, (void *)s_silence, sizeof(s_silence));
        vTaskDelay(pdMS_TO_TICKS(210));
        output_mute(true);
        s_playing = false;
        printf("AUDIO_TONE_DONE volume=80 pa=%d\n", gpio_get_level(53));
    } else if (strcmp(line, "AUDIO STOP") == 0) {
        puts(playback_stop() ? "AUDIO_STOPPED" : "AUDIO_ERROR stop");
    } else if (strcmp(line, "AUDIO END") == 0) {
        while (xSemaphoreTake(s_player_done, 0) == pdTRUE) {}
        portENTER_CRITICAL(&s_buffer_lock);
        s_buffer.ending = true;  /* Also starts a reply shorter than 200 ms. */
        portEXIT_CRITICAL(&s_buffer_lock);
        bool done = xSemaphoreTake(s_player_done, pdMS_TO_TICKS(2500)) == pdTRUE;
        puts(done && !s_player_failed ? "AUDIO_DONE" : "AUDIO_ERROR drain");
    } else if (strncmp(line, "AUDIO BIN ", 10) == 0) {
        uint32_t seq, crc;
        unsigned bytes;
        if (sscanf(line, "AUDIO BIN %" SCNu32 " %u %" SCNx32, &seq, &bytes, &crc) != 3 || !bytes || bytes > sizeof(s_pcm) || bytes % 2) {
            puts("AUDIO_ERROR command");
        } else {
            s_playing = true;
            size_t received = 0;
            printf("AUDIO_RX %" PRIu32 " %u\n", seq, bytes); fflush(stdout);
            /* AUDIO_RX is the receive credit. The host must wait for it before
             * transmitting PCM, including at 4 Mbaud alongside video. */
            while (received < bytes) {
                int count = uart_read_bytes(CONFIG_ESP_CONSOLE_UART_NUM, (uint8_t *)s_pcm + received, bytes - received, pdMS_TO_TICKS(1000));
                if (count <= 0) break;
                received += count;
            }
            if (received != bytes || esp_rom_crc32_le(0, (const uint8_t *)s_pcm, bytes) != crc) {
                printf("AUDIO_ERROR invalid_pcm received=%u expected=%u\n", (unsigned)received, bytes);
            } else {
                if (playback_enqueue(s_pcm, bytes / 2))
                    printf("AUDIO_ACK %" PRIu32 "\n", seq);
                else puts("AUDIO_ERROR write");
            }
        }
    } else {
        uint32_t seq, crc;
        int offset = 0;
        if (sscanf(line, "AUDIO DATA %" SCNu32 " %" SCNx32 " %n", &seq, &crc, &offset) != 2 || offset == 0) {
            puts("AUDIO_ERROR command");
        } else {
            size_t bytes = 0;
            int err = mbedtls_base64_decode((unsigned char *)s_pcm, sizeof(s_pcm), &bytes,
                                           (const unsigned char *)line + offset, strlen(line + offset));
            if (err || !bytes || bytes % 2 || esp_rom_crc32_le(0, (const uint8_t *)s_pcm, bytes) != crc) {
                printf("AUDIO_ERROR invalid_pcm decode=%d bytes=%u crc=%08" PRIx32 " expected=%08" PRIx32 "\n", err, (unsigned)bytes, esp_rom_crc32_le(0, (const uint8_t *)s_pcm, bytes <= sizeof(s_pcm) ? bytes : 0), crc);
            } else {
                s_playing = true;
                if (playback_enqueue(s_pcm, bytes / 2))
                    printf("AUDIO_ACK %" PRIu32 "\n", seq);
                else puts("AUDIO_ERROR write");
            }
        }
    }
    fflush(stdout);
}
