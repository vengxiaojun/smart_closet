#ifndef AUDIO_UTILS_H
#include <stddef.h>
int onesdk_base64_encode(const char *input, size_t input_length, char **output, size_t *output_length);
int onesdk_base64_decode(const char *input, size_t input_length, char **output, size_t *output_length);
#define AUDIO_UTILS_H
#endif