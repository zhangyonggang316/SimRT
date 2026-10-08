#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif
#include "simrt_network.h"
#include <pthread.h>
#include <sched.h>
#include <string.h>
#include <time.h>
#ifdef _WIN32
/* Winsock is only used by the offline harness; generated deployment is Linux. */
#include <winsock2.h>
#include <ws2tcpip.h>
typedef SOCKET net_socket;
typedef int net_socklen;
#define NET_INVALID INVALID_SOCKET
#define net_close closesocket
#else
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <unistd.h>
typedef int net_socket;
typedef socklen_t net_socklen;
#define NET_INVALID (-1)
#define net_close close
#endif

#define QUEUE_CAPACITY 64U
#define BATCH_SIZE 8U
typedef struct { uint16_t size; uint8_t data[SIMRT_NET_MAX_BYTES]; } Packet;
typedef struct { Packet packets[QUEUE_CAPACITY]; unsigned head, count; } Queue;
typedef struct {
    uint32_t token;
    uint8_t protocol, server;
    int stop, running;
    int32_t status, pending_error;
    struct sockaddr_in local, remote;
    pthread_t worker;
    Queue tx, rx;
} Endpoint;
static Endpoint endpoints[SIMRT_NET_CHANNELS];
static pthread_mutex_t lifecycle_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t queue_lock = PTHREAD_MUTEX_INITIALIZER;
static uint32_t next_token;

static int retryable(void)
{
#ifdef _WIN32
    int error = WSAGetLastError();
    return error == WSAEWOULDBLOCK || error == WSAEINPROGRESS || error == WSAEINTR;
#else
    return errno == EAGAIN || errno == EWOULDBLOCK || errno == EINPROGRESS || errno == EINTR;
#endif
}
static int nonblocking(net_socket fd)
{
#ifdef _WIN32
    u_long one = 1;
    return ioctlsocket(fd, FIONBIO, &one) == 0;
#else
    int flags = fcntl(fd, F_GETFL, 0);
    int fd_flags = fcntl(fd, F_GETFD, 0);
    return flags >= 0 && fd_flags >= 0 &&
        fcntl(fd, F_SETFL, flags | O_NONBLOCK) == 0 &&
        fcntl(fd, F_SETFD, fd_flags | FD_CLOEXEC) == 0;
#endif
}
static void pause_worker(void)
{
    struct timespec delay = {0, 1000000L};
    nanosleep(&delay, NULL);
}
static void set_status(Endpoint *endpoint, int32_t status)
{
    pthread_mutex_lock(&queue_lock);
    endpoint->status = status;
    pthread_mutex_unlock(&queue_lock);
}
static void set_error(Endpoint *endpoint, int32_t error)
{
    pthread_mutex_lock(&queue_lock);
    endpoint->pending_error = error;
    pthread_mutex_unlock(&queue_lock);
}
static void reset_connection(Endpoint *endpoint, net_socket *fd, Packet *outgoing)
{
    if (*fd != NET_INVALID) net_close(*fd);
    *fd = NET_INVALID;
    outgoing->size = 0;
    pthread_mutex_lock(&queue_lock);
    endpoint->tx.head = endpoint->tx.count = 0;
    /* Retain received bytes already accepted from this connection. */
    endpoint->status = SIMRT_NET_PENDING;
    endpoint->pending_error = SIMRT_NET_IO;
    pthread_mutex_unlock(&queue_lock);
}
static net_socket open_socket(Endpoint *endpoint)
{
    net_socket fd = socket(AF_INET, endpoint->protocol ? SOCK_DGRAM : SOCK_STREAM, 0);
    int one = 1;
    if (fd == NET_INVALID) { set_status(endpoint, SIMRT_NET_SOCKET); return fd; }
    if (!nonblocking(fd)) {
        net_close(fd); set_status(endpoint, SIMRT_NET_SOCKET); return NET_INVALID;
    }
    if (!endpoint->protocol && endpoint->server)
        (void)setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, (const char *)&one, sizeof(one));
    if (bind(fd, (struct sockaddr *)&endpoint->local, sizeof(endpoint->local)) != 0) {
        net_close(fd); set_status(endpoint, SIMRT_NET_BIND); return NET_INVALID;
    }
    if (!endpoint->protocol) {
        (void)setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, (const char *)&one, sizeof(one));
        (void)setsockopt(fd, SOL_SOCKET, SO_KEEPALIVE, (const char *)&one, sizeof(one));
    }
    return fd;
}
static int connected(net_socket fd)
{
#ifdef _WIN32
    fd_set write_fds, error_fds;
    struct timeval timeout = {0, 0};
    int result;
    FD_ZERO(&write_fds); FD_ZERO(&error_fds);
    FD_SET(fd, &write_fds); FD_SET(fd, &error_fds);
    result = select((int)fd + 1, NULL, &write_fds, &error_fds, &timeout);
#else
    struct pollfd descriptor;
    int result;
    descriptor.fd = fd; descriptor.events = POLLOUT; descriptor.revents = 0;
    result = poll(&descriptor, 1, 0);
#endif
    int error = 0;
    net_socklen length = sizeof(error);
    if (result == 0) return 0;
    if (result < 0) return retryable() ? 0 : -1;
    if (getsockopt(fd, SOL_SOCKET, SO_ERROR, (char *)&error, &length) != 0 || error != 0) return -1;
    return 1;
}
static int transmit(Endpoint *endpoint, net_socket fd, Packet *packet, uint16_t *offset)
{
    int count, flags = 0;
    if (packet->size == 0) {
        pthread_mutex_lock(&queue_lock);
        if (endpoint->tx.count) {
            *packet = endpoint->tx.packets[endpoint->tx.head];
            endpoint->tx.head = (endpoint->tx.head + 1U) % QUEUE_CAPACITY;
            --endpoint->tx.count;
        }
        pthread_mutex_unlock(&queue_lock);
        *offset = 0;
    }
    if (packet->size == 0) return 1;
#ifdef MSG_NOSIGNAL
    flags = MSG_NOSIGNAL;
#endif
    if (endpoint->protocol)
        count = (int)sendto(fd, (const char *)packet->data, packet->size, flags,
            (struct sockaddr *)&endpoint->remote, sizeof(endpoint->remote));
    else
        count = (int)send(fd, (const char *)packet->data + *offset, packet->size - *offset, flags);
    if (count < 0) return retryable() ? 1 : 0;
    if (count == 0 || (endpoint->protocol && count != packet->size)) return 0;
    *offset = (uint16_t)(*offset + count);
    if (*offset == packet->size) packet->size = 0;
    return 1;
}
static int receive_packets(Endpoint *endpoint, net_socket fd)
{
    unsigned batch;
    for (batch = 0; batch < BATCH_SIZE; ++batch) {
        Packet packet;
        int count, flags = 0;
        pthread_mutex_lock(&queue_lock);
        /* TCP backpressure preserves stream bytes instead of dropping a chunk. */
        if (!endpoint->protocol && endpoint->rx.count == QUEUE_CAPACITY) {
            pthread_mutex_unlock(&queue_lock);
            return 1;
        }
        pthread_mutex_unlock(&queue_lock);
#ifdef MSG_TRUNC
        if (endpoint->protocol) flags = MSG_TRUNC;
#endif
        count = (int)recv(fd, (char *)packet.data, sizeof(packet.data), flags);
        if (count < 0) {
#ifdef _WIN32
            if (endpoint->protocol && WSAGetLastError() == WSAEMSGSIZE) {
                set_error(endpoint, SIMRT_NET_TRUNCATED); continue;
            }
#endif
            return retryable() ? 1 : 0;
        }
        if (count == 0 && !endpoint->protocol) return 0;
        if (count > (int)SIMRT_NET_MAX_BYTES) {
            set_error(endpoint, SIMRT_NET_TRUNCATED); continue;
        }
        packet.size = (uint16_t)count;
        pthread_mutex_lock(&queue_lock);
        if (endpoint->rx.count == QUEUE_CAPACITY) endpoint->pending_error = SIMRT_NET_QUEUE_FULL;
        else {
            endpoint->rx.packets[(endpoint->rx.head + endpoint->rx.count) % QUEUE_CAPACITY] = packet;
            ++endpoint->rx.count;
        }
        pthread_mutex_unlock(&queue_lock);
    }
    return 1;
}
static void *worker_main(void *argument)
{
    Endpoint *endpoint = (Endpoint *)argument;
    net_socket fd = NET_INVALID, listener = NET_INVALID;
    Packet outgoing;
    uint16_t offset = 0;
    unsigned retry_ticks = 0, connect_ticks = 0;
    int connecting = 0;
    memset(&outgoing, 0, sizeof(outgoing));
    for (;;) {
        int stop;
        pthread_mutex_lock(&queue_lock);
        stop = endpoint->stop;
        pthread_mutex_unlock(&queue_lock);
        if (stop) break;
        if (retry_ticks) { --retry_ticks; pause_worker(); continue; }
        if (endpoint->server && !endpoint->protocol) {
            if (listener == NET_INVALID) {
                listener = open_socket(endpoint);
                if (listener != NET_INVALID && listen(listener, 1) != 0) {
                    net_close(listener); listener = NET_INVALID; set_status(endpoint, SIMRT_NET_SOCKET);
                }
                if (listener == NET_INVALID) { retry_ticks = 250; continue; }
                set_status(endpoint, SIMRT_NET_PENDING);
            }
            if (fd == NET_INVALID) {
                int one = 1;
                fd = accept(listener, NULL, NULL);
                if (fd != NET_INVALID) {
                    if (!nonblocking(fd)) { net_close(fd); fd = NET_INVALID; }
                    else {
                        (void)setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, (const char *)&one, sizeof(one));
                        set_status(endpoint, SIMRT_NET_OK);
                    }
                }
            }
        } else if (fd == NET_INVALID) {
            fd = open_socket(endpoint);
            if (fd == NET_INVALID) { retry_ticks = 250; continue; }
            if (endpoint->protocol) set_status(endpoint, SIMRT_NET_OK);
            else {
                int result = connect(fd, (struct sockaddr *)&endpoint->remote, sizeof(endpoint->remote));
                if (result == 0) set_status(endpoint, SIMRT_NET_OK);
                else if (retryable()) { connecting = 1; connect_ticks = 0; set_status(endpoint, SIMRT_NET_PENDING); }
                else {
                    net_close(fd); fd = NET_INVALID; set_status(endpoint, SIMRT_NET_CONNECT);
                    retry_ticks = 250; continue;
                }
            }
        }
        if (connecting) {
            int result = connected(fd);
            if (result < 0 || ++connect_ticks > 5000U) {
                net_close(fd); fd = NET_INVALID; connecting = 0;
                set_status(endpoint, SIMRT_NET_CONNECT); retry_ticks = 250; continue;
            }
            if (result > 0) { connecting = 0; set_status(endpoint, SIMRT_NET_OK); }
        }
        if (fd != NET_INVALID && !connecting) {
            if (!transmit(endpoint, fd, &outgoing, &offset) || !receive_packets(endpoint, fd)) {
                reset_connection(endpoint, &fd, &outgoing);
                retry_ticks = 250;
            }
        }
        pause_worker();
    }
    if (fd != NET_INVALID) net_close(fd);
    if (listener != NET_INVALID) net_close(listener);
    return NULL;
}
static int start_worker(Endpoint *endpoint)
{
    pthread_attr_t attributes;
    struct sched_param scheduling;
    int result = pthread_attr_init(&attributes);
    if (result != 0) return result;
    memset(&scheduling, 0, sizeof(scheduling));
    result = pthread_attr_setinheritsched(&attributes, PTHREAD_EXPLICIT_SCHED);
    if (result == 0) result = pthread_attr_setschedpolicy(&attributes, SCHED_OTHER);
    if (result == 0) result = pthread_attr_setschedparam(&attributes, &scheduling);
    if (result == 0) result = pthread_create(&endpoint->worker, &attributes, worker_main, endpoint);
    pthread_attr_destroy(&attributes);
    return result;
}
int32_t simrt_net_configure(uint8_t channel, uint8_t protocol, uint8_t server,
    const char *local_ip, uint16_t local_port, const char *remote_ip,
    uint16_t remote_port, uint32_t *token)
{
    struct sockaddr_in local, remote;
    Endpoint *endpoint;
    if (token == NULL) return SIMRT_NET_INVALID;
    *token = 0;
    memset(&local, 0, sizeof(local)); memset(&remote, 0, sizeof(remote));
    local.sin_family = remote.sin_family = AF_INET;
    local.sin_port = htons(local_port); remote.sin_port = htons(remote_port);
    if (channel < 1 || channel > SIMRT_NET_CHANNELS || protocol > 1 || server > 1 ||
        local_ip == NULL || remote_ip == NULL ||
        inet_pton(AF_INET, local_ip, &local.sin_addr) != 1 ||
        inet_pton(AF_INET, remote_ip, &remote.sin_addr) != 1 ||
        ((!server || protocol) && (remote_port == 0 || remote.sin_addr.s_addr == htonl(INADDR_ANY))) ||
        (server && !protocol && local_port == 0)) return SIMRT_NET_INVALID;
    pthread_mutex_lock(&lifecycle_lock);
#ifdef _WIN32
    {
        static int started;
        WSADATA data;
        if (!started && WSAStartup(MAKEWORD(2, 2), &data) != 0) {
            pthread_mutex_unlock(&lifecycle_lock); return SIMRT_NET_SOCKET;
        }
        started = 1;
    }
#endif
    pthread_mutex_lock(&queue_lock);
    endpoint = &endpoints[channel - 1U];
    if (endpoint->token != 0) {
        pthread_mutex_unlock(&queue_lock); pthread_mutex_unlock(&lifecycle_lock);
        return SIMRT_NET_DUPLICATE;
    }
    /* Never reuse a token: exhaustion requires restarting the model process. */
    if (next_token == UINT32_MAX) {
        pthread_mutex_unlock(&queue_lock); pthread_mutex_unlock(&lifecycle_lock);
        return SIMRT_NET_INVALID;
    }
    memset(endpoint, 0, sizeof(*endpoint));
    endpoint->token = ++next_token;
    endpoint->local = local; endpoint->remote = remote;
    endpoint->protocol = protocol; endpoint->server = server;
    endpoint->status = SIMRT_NET_PENDING;
    pthread_mutex_unlock(&queue_lock);
    if (start_worker(endpoint) != 0) {
        pthread_mutex_lock(&queue_lock);
        endpoint->token = 0; endpoint->status = SIMRT_NET_THREAD;
        pthread_mutex_unlock(&queue_lock);
        pthread_mutex_unlock(&lifecycle_lock);
        return SIMRT_NET_THREAD;
    }
    endpoint->running = 1;
    *token = endpoint->token;
    pthread_mutex_unlock(&lifecycle_lock);
    return SIMRT_NET_PENDING;
}
int32_t simrt_net_status(uint8_t channel, uint32_t token)
{
    int32_t result;
    Endpoint *endpoint;
    if (channel < 1 || channel > SIMRT_NET_CHANNELS || token == 0) return SIMRT_NET_INVALID;
    if (pthread_mutex_trylock(&queue_lock) != 0) return SIMRT_NET_BUSY;
    endpoint = &endpoints[channel - 1U];
    result = endpoint->token == token ? endpoint->status : SIMRT_NET_UNCONFIGURED;
    pthread_mutex_unlock(&queue_lock);
    return result;
}
int32_t simrt_net_send(uint8_t channel, const uint8_t *data, uint16_t length)
{
    Endpoint *endpoint;
    int32_t result;
    if (channel < 1 || channel > SIMRT_NET_CHANNELS || data == NULL ||
        length == 0 || length > SIMRT_NET_MAX_BYTES) return SIMRT_NET_INVALID;
    if (pthread_mutex_trylock(&queue_lock) != 0) return SIMRT_NET_BUSY;
    endpoint = &endpoints[channel - 1U];
    result = endpoint->token ? endpoint->status : SIMRT_NET_UNCONFIGURED;
    if (result == SIMRT_NET_OK) {
        if (endpoint->tx.count == QUEUE_CAPACITY) result = SIMRT_NET_QUEUE_FULL;
        else {
            Packet *packet = &endpoint->tx.packets[(endpoint->tx.head + endpoint->tx.count) % QUEUE_CAPACITY];
            packet->size = length;
            memcpy(packet->data, data, length);
            ++endpoint->tx.count;
        }
    }
    pthread_mutex_unlock(&queue_lock);
    return result;
}
int32_t simrt_net_receive(uint8_t channel, uint8_t *data, uint16_t capacity,
    uint16_t *length, uint8_t *valid)
{
    Endpoint *endpoint;
    int32_t result;
    if (length != NULL) *length = 0;
    if (valid != NULL) *valid = 0;
    if (channel < 1 || channel > SIMRT_NET_CHANNELS || data == NULL || length == NULL ||
        valid == NULL || capacity == 0 || capacity > SIMRT_NET_MAX_BYTES) return SIMRT_NET_INVALID;
    memset(data, 0, capacity);
    if (pthread_mutex_trylock(&queue_lock) != 0) return SIMRT_NET_BUSY;
    endpoint = &endpoints[channel - 1U];
    result = endpoint->token ? endpoint->status : SIMRT_NET_UNCONFIGURED;
    if (endpoint->token && endpoint->pending_error) {
        result = endpoint->pending_error; endpoint->pending_error = 0;
    }
    if (endpoint->token && endpoint->rx.count) {
        Packet *packet = &endpoint->rx.packets[endpoint->rx.head];
        *length = packet->size > capacity ? capacity : packet->size;
        *valid = 1;
        memcpy(data, packet->data, *length);
        if (packet->size > capacity && !endpoint->protocol) {
            packet->size = (uint16_t)(packet->size - capacity);
            memmove(packet->data, packet->data + capacity, packet->size);
        } else {
            if (packet->size > capacity) result = SIMRT_NET_TRUNCATED;
            endpoint->rx.head = (endpoint->rx.head + 1U) % QUEUE_CAPACITY;
            --endpoint->rx.count;
        }
    }
    pthread_mutex_unlock(&queue_lock);
    return result;
}
void simrt_net_release(uint32_t token)
{
    unsigned channel;
    Endpoint *endpoint = NULL;
    if (!token) return;
    pthread_mutex_lock(&lifecycle_lock);
    pthread_mutex_lock(&queue_lock);
    for (channel = 0; channel < SIMRT_NET_CHANNELS; ++channel)
        if (endpoints[channel].token == token) { endpoint = &endpoints[channel]; break; }
    if (endpoint != NULL) endpoint->stop = 1;
    pthread_mutex_unlock(&queue_lock);
    if (endpoint != NULL) {
        if (endpoint->running) pthread_join(endpoint->worker, NULL);
        pthread_mutex_lock(&queue_lock);
        memset(endpoint, 0, sizeof(*endpoint));
        pthread_mutex_unlock(&queue_lock);
    }
    pthread_mutex_unlock(&lifecycle_lock);
}
