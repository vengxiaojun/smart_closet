#ifndef CHAT_ESP32_H
#define CHAT_ESP32_H
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdbool.h>
#include <stdint.h>
#define MBEDTLS_DEBUG_C
#define DEBUG_LEVEL 2
#include "onesdk_config.h"
int chat_main();
int realtime_main();
int audio_main();
#endif