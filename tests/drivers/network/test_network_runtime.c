#include <assert.h>
#include <stdio.h>
/* Include implementation to exercise lock contention and queue limits deterministically. */
#include "../../../toolchain/simrt_linux_target/drivers/network/src/simrt_network.c"

static void ready(uint8_t channel, uint32_t token)
{
    unsigned attempt;
    int32_t status = SIMRT_NET_PENDING;
    for (attempt = 0; attempt < 8000; ++attempt) {
        status = simrt_net_status(channel, token);
        if (status == SIMRT_NET_OK) return;
        pause_worker();
    }
    fprintf(stderr, "channel %u failed to become ready: %d\n", channel, (int)status);
    assert(0);
}
static void send_bytes(uint8_t channel, const uint8_t *data, uint16_t length)
{
    unsigned attempt;
    int32_t status;
    for (attempt = 0; attempt < 8000; ++attempt) {
        status = simrt_net_send(channel, data, length);
        if (status == SIMRT_NET_OK) return;
        assert(status == SIMRT_NET_BUSY || status == SIMRT_NET_QUEUE_FULL);
        pause_worker();
    }
    assert(0);
}
static uint16_t read_bytes(uint8_t channel, uint8_t *data, uint16_t capacity, int32_t expected)
{
    unsigned attempt;
    uint16_t length;
    uint8_t valid;
    for (attempt = 0; attempt < 8000; ++attempt) {
        int32_t status = simrt_net_receive(channel, data, capacity, &length, &valid);
        if (valid) { assert(status == expected); return length; }
        assert(status == SIMRT_NET_OK || status == SIMRT_NET_BUSY);
        assert(length == 0);
        pause_worker();
    }
    assert(0);
    return 0;
}
static void validation_and_contention(void)
{
    uint32_t token = 123;
    uint8_t data[4] = {1, 2, 3, 4}, valid;
    uint16_t length;
    assert(simrt_net_configure(0, 0, 0, "0.0.0.0", 0, "127.0.0.1", 5010, &token) == SIMRT_NET_INVALID);
    assert(token == 0);
    assert(simrt_net_configure(1, 1, 0, "1.2.3", 0, "127.0.0.1", 5010, &token) == SIMRT_NET_INVALID);
    assert(simrt_net_configure(1, 0, 1, "0.0.0.0", 0, "127.0.0.1", 5010, &token) == SIMRT_NET_INVALID);
    assert(simrt_net_configure(1, 1, 0, "0.0.0.0", 0, "0.0.0.0", 5010, &token) == SIMRT_NET_INVALID);
    assert(simrt_net_send(1, data, 4) == SIMRT_NET_UNCONFIGURED);
    assert(simrt_net_send(1, data, 0) == SIMRT_NET_INVALID);
    assert(simrt_net_send(1, data, 4097) == SIMRT_NET_INVALID);
    assert(simrt_net_receive(1, data, 0, &length, &valid) == SIMRT_NET_INVALID);
    assert(length == 0 && valid == 0);
    pthread_mutex_lock(&queue_lock);
    assert(simrt_net_send(1, data, 4) == SIMRT_NET_BUSY);
    assert(simrt_net_receive(1, data, 4, &length, &valid) == SIMRT_NET_BUSY);
    assert(simrt_net_status(1, 1) == SIMRT_NET_BUSY);
    pthread_mutex_unlock(&queue_lock);
}
static void udp_roundtrip(void)
{
    uint32_t first, second, duplicate;
    uint8_t input[32], output[32];
    unsigned i;
    for (i = 0; i < sizeof(input); ++i) input[i] = (uint8_t)i;
    assert(simrt_net_configure(1, 1, 0, "127.0.0.1", 45181, "127.0.0.1", 45182, &first) == SIMRT_NET_PENDING);
    assert(simrt_net_configure(2, 1, 0, "127.0.0.1", 45182, "127.0.0.1", 45181, &second) == SIMRT_NET_PENDING);
    ready(1, first); ready(2, second);
    assert(simrt_net_configure(1, 1, 0, "127.0.0.1", 45181, "127.0.0.1", 45182, &duplicate) == SIMRT_NET_DUPLICATE);
    assert(duplicate == 0);
    simrt_net_release(duplicate);
    send_bytes(1, input, sizeof(input));
    assert(read_bytes(2, output, sizeof(output), SIMRT_NET_OK) == sizeof(input));
    assert(memcmp(input, output, sizeof(input)) == 0);
    send_bytes(2, input, sizeof(input));
    assert(read_bytes(1, output, 4, SIMRT_NET_TRUNCATED) == 4);
    assert(memcmp(input, output, 4) == 0);
    simrt_net_release(first); simrt_net_release(second); simrt_net_release(first);
    assert(simrt_net_send(1, input, 4) == SIMRT_NET_UNCONFIGURED);
    assert(simrt_net_configure(1, 1, 0, "127.0.0.1", 45181, "127.0.0.1", 45182, &second) == SIMRT_NET_PENDING);
    assert(first != second);
    simrt_net_release(first);
    ready(1, second);
    simrt_net_release(second);
}
static void tcp_stream_and_reconnect(void)
{
    uint32_t server, client;
    uint8_t input[SIMRT_NET_MAX_BYTES], output[SIMRT_NET_MAX_BYTES];
    unsigned i, offset = 0;
    for (i = 0; i < sizeof(input); ++i) input[i] = (uint8_t)(i * 17U);
    assert(simrt_net_configure(3, 0, 1, "127.0.0.1", 45183, "0.0.0.0", 0, &server) == SIMRT_NET_PENDING);
    assert(simrt_net_configure(4, 0, 0, "127.0.0.1", 0, "127.0.0.1", 45183, &client) == SIMRT_NET_PENDING);
    ready(3, server); ready(4, client);
    send_bytes(4, input, sizeof(input));
    while (offset < sizeof(input)) {
        uint8_t chunk[7];
        uint16_t count = read_bytes(3, chunk, sizeof(chunk), SIMRT_NET_OK);
        assert(offset + count <= sizeof(input));
        memcpy(output + offset, chunk, count); offset += count;
    }
    assert(memcmp(input, output, sizeof(input)) == 0);
    send_bytes(3, input, 31);
    assert(read_bytes(4, output, sizeof(output), SIMRT_NET_OK) == 31);
    assert(memcmp(input, output, 31) == 0);
    simrt_net_release(client);
    /* Wait for server to observe FIN, then reconnect a new client. */
    for (i = 0; i < 8000; ++i) {
        if (simrt_net_status(3, server) == SIMRT_NET_PENDING) break;
        pause_worker();
    }
    assert(i < 8000);
    assert(simrt_net_configure(4, 0, 0, "127.0.0.1", 0, "127.0.0.1", 45183, &client) == SIMRT_NET_PENDING);
    ready(3, server); ready(4, client);
    /* Consume the observable disconnect error before the next exchange. */
    pthread_mutex_lock(&queue_lock);
    assert(endpoints[2].pending_error == SIMRT_NET_IO);
    endpoints[2].pending_error = 0;
    pthread_mutex_unlock(&queue_lock);
    send_bytes(4, input, 32);
    assert(read_bytes(3, output, sizeof(output), SIMRT_NET_OK) == 32);
    assert(memcmp(input, output, 32) == 0);
    simrt_net_release(server); simrt_net_release(client);
}
static void deterministic_queue_bounds(void)
{
    uint8_t data[4] = {4, 3, 2, 1};
    unsigned i;
    /* A configured endpoint without a worker gives deterministic pressure. */
    pthread_mutex_lock(&queue_lock);
    memset(&endpoints[15], 0, sizeof(endpoints[15]));
    endpoints[15].token = UINT32_MAX;
    endpoints[15].status = SIMRT_NET_OK;
    pthread_mutex_unlock(&queue_lock);
    for (i = 0; i < QUEUE_CAPACITY; ++i) assert(simrt_net_send(16, data, sizeof(data)) == SIMRT_NET_OK);
    assert(simrt_net_send(16, data, sizeof(data)) == SIMRT_NET_QUEUE_FULL);
    simrt_net_release(UINT32_MAX);
}
int main(void)
{
    validation_and_contention();
    deterministic_queue_bounds();
    udp_roundtrip();
    tcp_stream_and_reconnect();
    puts("network runtime: validation, nonblocking APIs, queues, UDP, TCP stream, ownership and reconnect passed");
    return 0;
}
