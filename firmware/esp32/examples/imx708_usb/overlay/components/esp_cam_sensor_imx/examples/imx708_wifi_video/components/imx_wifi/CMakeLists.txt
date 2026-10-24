# SPDX-License-Identifier: Apache-2.0
idf_component_register(
    SRCS "imx_wifi.c" "camera_provision.c" "board_audio.c"
    INCLUDE_DIRS "include"
    REQUIRES esp_wifi esp_netif esp_event nvs_flash esp_driver_uart mbedtls esp_driver_i2s esp_driver_i2c esp_driver_gpio esp_codec_dev
)
