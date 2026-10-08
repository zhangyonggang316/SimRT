#ifndef SIMRT_TC1013_CAN_H
#define SIMRT_TC1013_CAN_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum {
    SIMRT_CAN_OK = 0,
    SIMRT_CAN_INVALID_ARGUMENT = -1,
    SIMRT_CAN_ALREADY_OPEN = -2,
    SIMRT_CAN_LIBRARY_ERROR = -3,
    SIMRT_CAN_SDK_ERROR = -4,
    SIMRT_CAN_INVALID_DEVICE = -5,
    SIMRT_CAN_BUSY = -6,
    SIMRT_CAN_TX_FULL = -7,
    SIMRT_CAN_THREAD_ERROR = -8,
    SIMRT_CAN_RX_OVERFLOW = -9,
    SIMRT_CAN_TX_ERROR = -10,
    SIMRT_CAN_RX_ERROR = -11,
    SIMRT_CAN_DEVICE_CONFLICT = -12,
    SIMRT_CAN_MODE_MISMATCH = -13,
    SIMRT_CAN_DIRECTORY_ERROR = -14
};

/* One no-port Setup owns one channel (1/2); both share one physical adapter.
 * Setup/release are not step APIs. Baud rates use kbit/s. canfd=1 selects ISO FD.
 * Failed or duplicate setup returns token=0; releasing it cannot close a peer.
 * Failed setup logs an error and persists its status for channel Send/Receive;
 * callers need not terminate the process to make a no-port Setup error visible. */
int32_t simrt_can_configure_channel(const char *library_dir, const char *serial,
                                  uint8_t channel, uint8_t canfd,
                                  double nominal_kbps, double data_kbps,
                                  uint8_t termination, uint32_t *ownership_token);
void simrt_can_release(uint32_t ownership_token);

/* Channels are 1/2. Success means queued, not confirmed on the CAN bus.
 * Step APIs use trylock and bounded queues; they never call the USB SDK. */
int32_t simrt_can_send(uint8_t channel, uint32_t id,
                     uint8_t extended, uint8_t remote, uint8_t length,
                     const uint8_t data[8]);

/* timestamp is SDK microseconds converted to seconds. No frame/error/busy clears
 * every output and leaves received=0. Pending async errors are consumed once. */
int32_t simrt_can_receive(uint8_t channel, uint32_t *id,
                        uint8_t *extended, uint8_t *remote, uint8_t *error,
                        uint8_t *length, double *timestamp, uint8_t data[8],
                        uint8_t *received);
/* FD length is bytes: 0..8,12,16,20,24,32,48,64. Nonrepresentable lengths are
 * rejected; this layer never silently pads a caller's declared length. */
int32_t simrt_can_send_fd(uint8_t channel, uint32_t id, uint8_t extended,
                        uint8_t brs, uint8_t esi, uint8_t length,
                        const uint8_t data[64]);
int32_t simrt_can_receive_fd(uint8_t channel, uint32_t *id, uint8_t *extended,
                           uint8_t *brs, uint8_t *esi, uint8_t *error,
                           uint8_t *length, double *timestamp, uint8_t data[64],
                           uint8_t *received);
const char *simrt_can_status_string(int32_t status);

#ifdef __cplusplus
}
#endif

#endif
