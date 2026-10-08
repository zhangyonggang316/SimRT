#ifndef _DEFAULT_SOURCE
#define _DEFAULT_SOURCE
#endif
#include "simrt_dio.h"
#include "simrt_dio_platform.h"
#include <errno.h>
#include <pthread.h>
#include <string.h>

#define SLOT_COUNT 16
typedef struct {
    int fd;
    uint32_t token, count;
    uint8_t output;
} dio_slot;
static dio_slot slots[SLOT_COUNT];
static uint32_t next_token;
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;

static dio_slot *find_slot(uint32_t token)
{
    int i;
    for (i = 0; i < SLOT_COUNT; ++i)
        if (token && slots[i].token == token) return &slots[i];
    return NULL;
}

static uint64_t line_mask(uint32_t count)
{
    return count == 64 ? UINT64_MAX : (UINT64_C(1) << count) - 1;
}

int32_t simrt_dio_open(const char *device, const uint32_t *offsets, uint32_t count,
    uint8_t output, uint8_t active_low, const uint8_t *initial, uint32_t *token)
{
    struct gpio_v2_line_request request;
    int fd, i, free_slot = -1, status = 0;
    uint32_t j, k;
    if (token) *token = 0;
    if (!token || !device || strncmp(device, "/dev/", 5) || strlen(device) >= 256 ||
        !offsets || !initial || !count || count > SIMRT_DIO_MAX_LINES || output > 1 || active_low > 1)
        return -EINVAL;
    for (j = 0; j < count; ++j) {
        if (initial[j] > 1) return -EINVAL;
        for (k = 0; k < j; ++k)
            if (offsets[j] == offsets[k]) return -EINVAL;
    }
    memset(&request, 0, sizeof(request));
    request.fd = -1;
    request.num_lines = count;
    memcpy(request.offsets, offsets, count * sizeof(*offsets));
    strcpy(request.consumer, "SimRT DIO");
    request.config.flags = output ? GPIO_V2_LINE_FLAG_OUTPUT : GPIO_V2_LINE_FLAG_INPUT;
    if (active_low) request.config.flags |= GPIO_V2_LINE_FLAG_ACTIVE_LOW;
    if (output) {
        /* Initial levels are part of the request, avoiding a separate post-open write. */
        request.config.num_attrs = 1;
        request.config.attrs[0].attr.id = GPIO_V2_LINE_ATTR_ID_OUTPUT_VALUES;
        request.config.attrs[0].mask = line_mask(count);
        for (j = 0; j < count; ++j)
            request.config.attrs[0].attr.values |= (uint64_t)initial[j] << j;
    }
    pthread_mutex_lock(&lock);
    for (i = 0; i < SLOT_COUNT; ++i)
        if (!slots[i].token) { free_slot = i; break; }
    if (free_slot < 0) { status = -ENOSPC; goto done; }
    fd = open(device, O_RDONLY | O_CLOEXEC);
    if (fd < 0) { status = -errno; goto done; }
    if (ioctl(fd, GPIO_V2_GET_LINE_IOCTL, &request) < 0) {
        status = -errno;
        close(fd);
        goto done;
    }
    close(fd);
    if (request.fd < 0) { status = -EIO; goto done; }
    do { ++next_token; } while (!next_token || find_slot(next_token));
    slots[free_slot].fd = request.fd;
    slots[free_slot].count = count;
    slots[free_slot].output = output;
    slots[free_slot].token = next_token;
    *token = next_token;
done:
    pthread_mutex_unlock(&lock);
    return status;
}

int32_t simrt_dio_read(uint32_t token, uint8_t *values, uint32_t count)
{
    struct gpio_v2_line_values request;
    dio_slot *slot;
    uint32_t i;
    int status = 0;
    if (!values || !count || count > SIMRT_DIO_MAX_LINES) return -EINVAL;
    memset(values, 0, count);
    if (pthread_mutex_trylock(&lock)) return -EAGAIN;
    slot = find_slot(token);
    if (!slot) { status = -EBADF; goto done; }
    if (count != slot->count) { status = -EINVAL; goto done; }
    memset(&request, 0, sizeof(request));
    request.mask = line_mask(count);
    if (ioctl(slot->fd, GPIO_V2_LINE_GET_VALUES_IOCTL, &request) < 0) {
        status = -errno; goto done;
    }
    for (i = 0; i < count; ++i) values[i] = (uint8_t)((request.bits >> i) & 1);
done:
    pthread_mutex_unlock(&lock);
    return status;
}

int32_t simrt_dio_write(uint32_t token, const uint8_t *values, uint32_t count)
{
    struct gpio_v2_line_values request;
    dio_slot *slot;
    uint32_t i;
    int status = 0;
    if (!values || !count || count > SIMRT_DIO_MAX_LINES) return -EINVAL;
    memset(&request, 0, sizeof(request));
    request.mask = line_mask(count);
    for (i = 0; i < count; ++i) {
        if (values[i] > 1) return -EINVAL;
        request.bits |= (uint64_t)values[i] << i;
    }
    if (pthread_mutex_trylock(&lock)) return -EAGAIN;
    slot = find_slot(token);
    if (!slot) { status = -EBADF; goto done; }
    if (count != slot->count) { status = -EINVAL; goto done; }
    if (!slot->output) { status = -EPERM; goto done; }
    if (ioctl(slot->fd, GPIO_V2_LINE_SET_VALUES_IOCTL, &request) < 0) status = -errno;
done:
    pthread_mutex_unlock(&lock);
    return status;
}

void simrt_dio_close(uint32_t token)
{
    dio_slot *slot;
    pthread_mutex_lock(&lock);
    slot = find_slot(token);
    if (slot) { close(slot->fd); memset(slot, 0, sizeof(*slot)); }
    pthread_mutex_unlock(&lock);
}
