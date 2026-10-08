#ifndef SIMRT_SERIAL_H
#define SIMRT_SERIAL_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Status is zero on success, otherwise a negative Linux errno. */
int32_t simrt_serial_open(const char *device, uint32_t baud, uint8_t bits,
    uint8_t parity, uint8_t stop_bits, uint8_t mode, uint8_t rts_on_send,
    uint32_t before_ms, uint32_t after_ms, uint32_t *token);
int32_t simrt_serial_send(uint32_t token, const uint8_t *data, uint32_t length,
    uint32_t capacity, uint32_t *sent);
int32_t simrt_serial_receive(uint32_t token, uint8_t *data, uint32_t capacity,
    uint32_t *received);
void simrt_serial_close(uint32_t token);
#ifdef __cplusplus
}
#endif
#endif
