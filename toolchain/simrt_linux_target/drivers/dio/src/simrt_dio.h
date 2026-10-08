#ifndef SIMRT_DIO_H
#define SIMRT_DIO_H
#include <stdint.h>

#define SIMRT_DIO_MAX_LINES 64u

#ifdef __cplusplus
extern "C" {
#endif

/* Values follow offsets order: 0=inactive, 1=active (ActiveLow is applied by Linux).
 * Setup owns the request until close; all errors are negative errno values. */
int32_t simrt_dio_open(const char *device, const uint32_t *offsets, uint32_t count,
    uint8_t output, uint8_t active_low, const uint8_t *initial, uint32_t *token);
int32_t simrt_dio_read(uint32_t token, uint8_t *values, uint32_t count);
int32_t simrt_dio_write(uint32_t token, const uint8_t *values, uint32_t count);
/* Closing releases ownership; the kernel/board controls the resulting pin state. */
void simrt_dio_close(uint32_t token);

#ifdef __cplusplus
}
#endif
#endif
