/* SPDX-License-Identifier: Apache-2.0 */
#pragma once
#include <stdbool.h>
#include "esp_err.h"

/* Compatible with deployed p4_live's camera_wifi namespace and ssid/pass keys.
 * No credentials are compiled into the image. Never erase NVS automatically. */
esp_err_t camera_provision_init(void);
const char *camera_wifi_ssid(void);
const char *camera_wifi_password(void);
void camera_video_register(void (*callback)(bool enabled));
void camera_image_register(void (*callback)(const char *command));
