# SPDX-License-Identifier: Apache-2.0
idf_component_register(
    SRCS "imx_wifi.c" "camera_provision.c"
    INCLUDE_DIRS "include"
    REQUIRES esp_wifi esp_netif esp_event nvs_flash esp_driver_uart mbedtls
)
