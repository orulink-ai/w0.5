/* SPDX-License-Identifier: Apache-2.0 */
#pragma once
#include <stdbool.h>
/* USB control callback. Shares camera I2C bus; initializes audio on demand. */
void board_audio_command(const char *line);
/* True while microphone capture or acknowledged speaker packets are active. */
bool board_audio_is_active(void);
