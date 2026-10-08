#ifndef _DEFAULT_SOURCE
#define _DEFAULT_SOURCE
#endif
#include "simrt_serial.h"
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <linux/serial.h>
#include <pthread.h>
#include <string.h>
#include <sys/ioctl.h>
#include <termios.h>
#include <unistd.h>

#define SLOT_COUNT 16
#define MAX_BYTES 65536u
typedef struct { int fd; uint32_t token; char device[256]; } serial_slot;
static serial_slot slots[SLOT_COUNT];
static uint32_t next_token;
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;

static speed_t baud_value(uint32_t baud)
{
    switch (baud) {
    case 1200: return B1200; case 2400: return B2400;
    case 4800: return B4800; case 9600: return B9600;
    case 19200: return B19200; case 38400: return B38400;
    case 57600: return B57600; case 115200: return B115200;
    case 230400: return B230400; case 460800: return B460800;
    case 921600: return B921600; default: return 0;
    }
}

static serial_slot *find_slot(uint32_t token)
{
    int i;
    for (i = 0; i < SLOT_COUNT; ++i)
        if (token && slots[i].token == token) return &slots[i];
    return NULL;
}

int32_t simrt_serial_open(const char *device, uint32_t baud, uint8_t bits,
    uint8_t parity, uint8_t stop_bits, uint8_t mode, uint8_t rts_on_send,
    uint32_t before_ms, uint32_t after_ms, uint32_t *token)
{
    struct termios config;
    struct serial_rs485 rs485;
    speed_t speed = baud_value(baud);
    int fd = -1, i, free_slot = -1, status = 0;
    if (token) *token = 0;
    if (!token || !device || strncmp(device, "/dev/", 5) ||
        strlen(device) >= sizeof(slots[0].device) || !speed ||
        bits < 5 || bits > 8 || parity > 2 || stop_bits < 1 || stop_bits > 2 ||
        mode > 2 || rts_on_send > 1 || before_ms > 1000 || after_ms > 1000)
        return -EINVAL;
    pthread_mutex_lock(&lock);
    for (i = 0; i < SLOT_COUNT; ++i) {
        if (!slots[i].token) free_slot = i;
        else if (!strcmp(slots[i].device, device)) { status = -EBUSY; goto done; }
    }
    if (free_slot < 0) { status = -ENOSPC; goto done; }
    fd = open(device, O_RDWR | O_NOCTTY | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0) { status = -errno; goto done; }
    if (ioctl(fd, TIOCEXCL) < 0 || tcgetattr(fd, &config) < 0) {
        status = -errno; goto fail;
    }
    cfmakeraw(&config);
    config.c_cflag &= ~(CSIZE | PARENB | PARODD | CSTOPB | CRTSCTS);
    config.c_cflag |= CLOCAL | CREAD;
    switch (bits) {
    case 5: config.c_cflag |= CS5; break;
    case 6: config.c_cflag |= CS6; break;
    case 7: config.c_cflag |= CS7; break;
    default: config.c_cflag |= CS8; break;
    }
    if (parity) { config.c_cflag |= PARENB; config.c_iflag |= INPCK; }
    if (parity == 1) config.c_cflag |= PARODD;
    if (stop_bits == 2) config.c_cflag |= CSTOPB;
    config.c_cc[VMIN] = 0; config.c_cc[VTIME] = 0;
    if (cfsetispeed(&config, speed) < 0 || cfsetospeed(&config, speed) < 0 ||
        tcsetattr(fd, TCSANOW, &config) < 0) { status = -errno; goto fail; }
    /* mode 1 uses the ARK's hardware auto-direction configured in BIOS/jumpers. */
    if (mode != 1) {
        memset(&rs485, 0, sizeof(rs485));
        if (mode == 2) {
            rs485.flags = SER_RS485_ENABLED |
                (rts_on_send ? SER_RS485_RTS_ON_SEND : SER_RS485_RTS_AFTER_SEND);
            rs485.delay_rts_before_send = before_ms;
            rs485.delay_rts_after_send = after_ms;
        }
        if (ioctl(fd, TIOCSRS485, &rs485) < 0 &&
            (mode == 2 || (errno != ENOTTY && errno != EINVAL && errno != EOPNOTSUPP))) {
            status = -errno; goto fail;
        }
        if (mode == 2) {
            memset(&rs485, 0, sizeof(rs485));
            if (ioctl(fd, TIOCGRS485, &rs485) < 0) { status = -errno; goto fail; }
            if (!(rs485.flags & SER_RS485_ENABLED) ||
                !!(rs485.flags & SER_RS485_RTS_ON_SEND) != !!rts_on_send ||
                !!(rs485.flags & SER_RS485_RTS_AFTER_SEND) == !!rts_on_send ||
                rs485.delay_rts_before_send != before_ms || rs485.delay_rts_after_send != after_ms) {
                status = -EOPNOTSUPP; goto fail;
            }
        }
    }
    do { ++next_token; } while (!next_token || find_slot(next_token));
    slots[free_slot].fd = fd;
    slots[free_slot].token = next_token;
    strcpy(slots[free_slot].device, device);
    *token = next_token;
    goto done;
fail:
    ioctl(fd, TIOCNXCL); close(fd);
done:
    pthread_mutex_unlock(&lock);
    return status;
}

int32_t simrt_serial_send(uint32_t token, const uint8_t *data, uint32_t length,
    uint32_t capacity, uint32_t *sent)
{
    serial_slot *slot;
    ssize_t result;
    int status = 0;
    if (sent) *sent = 0;
    if (!sent || !data || length > capacity || capacity > MAX_BYTES) return -EINVAL;
    if (pthread_mutex_trylock(&lock)) return -EAGAIN;
    slot = find_slot(token);
    if (!slot) { status = -EBADF; goto done; }
    result = write(slot->fd, data, length);
    if (result < 0) status = -errno;
    else { *sent = (uint32_t)result; if (*sent < length) status = -EAGAIN; }
done:
    pthread_mutex_unlock(&lock);
    return status;
}

int32_t simrt_serial_receive(uint32_t token, uint8_t *data, uint32_t capacity,
    uint32_t *received)
{
    serial_slot *slot;
    ssize_t result;
    int status = 0;
    if (received) *received = 0;
    if (!received || !data || !capacity || capacity > MAX_BYTES) return -EINVAL;
    memset(data, 0, capacity);
    if (pthread_mutex_trylock(&lock)) return -EAGAIN;
    slot = find_slot(token);
    if (!slot) { status = -EBADF; goto done; }
    result = read(slot->fd, data, capacity);
    if (result < 0) { if (errno != EAGAIN && errno != EWOULDBLOCK) status = -errno; }
    else *received = (uint32_t)result;
done:
    pthread_mutex_unlock(&lock);
    return status;
}

void simrt_serial_close(uint32_t token)
{
    serial_slot *slot;
    pthread_mutex_lock(&lock);
    slot = find_slot(token);
    if (slot) { ioctl(slot->fd, TIOCNXCL); close(slot->fd); memset(slot, 0, sizeof(*slot)); }
    pthread_mutex_unlock(&lock);
}
