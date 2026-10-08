#ifndef SIMRT_NETWORK_H
#define SIMRT_NETWORK_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
#define SIMRT_NET_MAX_BYTES 4096U
#define SIMRT_NET_CHANNELS 16U
enum {
    SIMRT_NET_OK = 0, SIMRT_NET_PENDING = 1, SIMRT_NET_BUSY = 2,
    SIMRT_NET_INVALID = -1, SIMRT_NET_DUPLICATE = -2,
    SIMRT_NET_UNCONFIGURED = -3, SIMRT_NET_SOCKET = -4,
    SIMRT_NET_BIND = -5, SIMRT_NET_CONNECT = -6,
    SIMRT_NET_QUEUE_FULL = -7, SIMRT_NET_IO = -8,
    SIMRT_NET_TRUNCATED = -9, SIMRT_NET_THREAD = -10,
    SIMRT_NET_HOST_DISABLED = -11
};
/* protocol: 0 TCP, 1 UDP; server: 0 TCP client, 1 TCP server (ignored for UDP). */
int32_t simrt_net_configure(uint8_t channel, uint8_t protocol, uint8_t server,
    const char *local_ip, uint16_t local_port, const char *remote_ip,
    uint16_t remote_port, uint32_t *token);
int32_t simrt_net_status(uint8_t channel, uint32_t token);
int32_t simrt_net_send(uint8_t channel, const uint8_t *data, uint16_t length);
int32_t simrt_net_receive(uint8_t channel, uint8_t *data, uint16_t capacity,
    uint16_t *length, uint8_t *valid);
void simrt_net_release(uint32_t token);
#ifdef __cplusplus
}
#endif
#endif
