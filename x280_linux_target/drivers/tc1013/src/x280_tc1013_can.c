#ifndef _POSIX_C_SOURCE
#define _POSIX_C_SOURCE 200809L
#endif
#include "x280_tc1013_can.h"
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <pthread.h>
#include <sched.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#if !defined(__linux__) && !defined(X280_CAN_TEST_HOST)
#error "TC1013 hardware runtime requires Linux; select explicit host simulation mode"
#endif

#define QUEUE_CAPACITY 256U
#define WORK_BATCH 32U
#define LIB_PATH_CAPACITY 4096U
#define SERIAL_CAPACITY 256U

#pragma pack(push, 1)
typedef struct {
    uint8_t channel, properties, dlc, reserved;
    int32_t identifier;
    uint64_t timestamp_us;
    uint8_t data[8];
} VendorCAN;
typedef struct {
    uint8_t channel, properties, dlc, fd_properties;
    int32_t identifier;
    uint64_t timestamp_us;
    uint8_t data[64];
} VendorCANFD;
#pragma pack(pop)
typedef char can_size_must_be_24[(sizeof(VendorCAN) == 24U) ? 1 : -1];
typedef char canfd_size_must_be_80[(sizeof(VendorCANFD) == 80U) ? 1 : -1];
typedef char can_data_offset_must_be_16[(offsetof(VendorCAN, data) == 16U) ? 1 : -1];
typedef char canfd_data_offset_must_be_16[(offsetof(VendorCANFD, data) == 16U) ? 1 : -1];
typedef char sdk_handle_must_be_64[(sizeof(size_t) == 8U) ? 1 : -1];

typedef struct {
    VendorCANFD frames[QUEUE_CAPACITY];
    unsigned int head, count;
} FrameQueue;
typedef struct {
    uint32_t token;
    uint8_t canfd;
    int32_t setup_status, pending_error;
    uint32_t last_tx_error, last_rx_error;
    FrameQueue tx, rx;
} Channel;
typedef struct {
    void *libraries[3];
    void (*initialize)(bool, bool, bool);
    void (*finalize)(void);
    uint32_t (*connect)(const char *, size_t *);
    uint32_t (*disconnect)(size_t);
    uint32_t (*configure)(size_t, int, double, uint32_t);
    uint32_t (*configure_fd)(size_t, int, double, double, int, int, uint32_t);
    uint32_t (*transmit)(size_t, const VendorCAN *);
    uint32_t (*transmit_fd)(size_t, const VendorCANFD *);
    uint32_t (*receive)(size_t, const VendorCAN *, int32_t *, uint8_t, uint8_t);
    uint32_t (*receive_fd)(size_t, const VendorCANFD *, int32_t *, uint8_t, uint8_t);
    uint32_t (*channel_count)(size_t, int32_t *);
    size_t handle;
    int initialized, connected, running, stop;
    pthread_t worker;
    char directory[LIB_PATH_CAPACITY], serial[SERIAL_CAPACITY];
    Channel channels[2];
} Driver;

static Driver driver;
static pthread_mutex_t queue_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_mutex_t lifecycle_lock = PTHREAD_MUTEX_INITIALIZER;
/* The SDK is not assumed thread-safe. Step APIs never acquire this mutex. */
static pthread_mutex_t sdk_lock = PTHREAD_MUTEX_INITIALIZER;
static uint32_t next_token;
static const uint8_t dlc_lengths[16] = {0,1,2,3,4,5,6,7,8,12,16,20,24,32,48,64};

typedef struct {
    int descriptor;
    int changed;
    char path[LIB_PATH_CAPACITY];
} DirectoryGuard;

/* Current vendor releases discover USB/configuration resources relative to cwd.
 * lifecycle_lock and sdk_lock serialize this initialization-only workaround. */
static int enter_sdk_directory(const char *directory, DirectoryGuard *guard)
{
    guard->descriptor = open(".", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    guard->changed = 0;
    if (guard->descriptor < 0) {
        fprintf(stderr, "TC1013: cannot save working directory: %s\n", strerror(errno));
        return 0;
    }
    if (getcwd(guard->path, sizeof(guard->path)) == NULL || chdir(directory) != 0) {
        fprintf(stderr, "TC1013: cannot enter SDK directory %s: %s\n", directory, strerror(errno));
        close(guard->descriptor);
        guard->descriptor = -1;
        return 0;
    }
    guard->changed = 1;
    return 1;
}

static int restore_directory(DirectoryGuard *guard)
{
    int result = 1;
    if (guard->changed) {
        int restored = fchdir(guard->descriptor);
        /* A signal interruption gets one bounded retry, never a step-time loop. */
        if (restored != 0 && errno == EINTR) restored = fchdir(guard->descriptor);
        if (restored != 0) {
            int code = errno;
            result = 0;
            if (chdir(guard->path) != 0) {
                fprintf(stderr, "TC1013: fatal working-directory restore failure: fchdir=%s, fallback=%s\n",
                        strerror(code), strerror(errno));
                fflush(stderr);
                /* Continuing would run unrelated model code in the SDK directory. */
                _Exit(EXIT_FAILURE);
            }
            fprintf(stderr, "TC1013: fchdir failed (%s); original directory restored by path; setup rejected\n",
                    strerror(code));
        }
        guard->changed = 0;
    }
    if (guard->descriptor >= 0) {
        if (close(guard->descriptor) != 0) {
            fprintf(stderr, "TC1013: cannot close saved-directory descriptor: %s\n", strerror(errno));
            result = 0;
        }
        guard->descriptor = -1;
    }
    return result;
}

static int length_to_dlc(uint8_t length)
{
    unsigned int i;
    for (i = 0U; i < 16U; ++i) if (dlc_lengths[i] == length) return (int)i;
    return -1;
}
static int push(FrameQueue *queue, const VendorCANFD *frame)
{
    if (queue->count == QUEUE_CAPACITY) return 0;
    queue->frames[(queue->head + queue->count) % QUEUE_CAPACITY] = *frame;
    ++queue->count;
    return 1;
}
static int pop(FrameQueue *queue, VendorCANFD *frame)
{
    if (queue->count == 0U) return 0;
    *frame = queue->frames[queue->head];
    queue->head = (queue->head + 1U) % QUEUE_CAPACITY;
    --queue->count;
    return 1;
}
static void sdk_log(const char *operation, uint32_t code)
{
    fprintf(stderr, "TC1013: %s failed, vendor status %u\n", operation, (unsigned int)code);
}
static int load_symbol(const char *name, void *destination, size_t size, int required)
{
    void *symbol;
    const char *error;
    dlerror();
    symbol = dlsym(driver.libraries[2], name);
    error = dlerror();
    if (error != NULL || symbol == NULL || size != sizeof(symbol)) {
        if (required) fprintf(stderr, "TC1013: SDK symbol %s unavailable: %s\n", name,
                              error != NULL ? error : "invalid function pointer");
        return 0;
    }
    memcpy(destination, &symbol, size);
    return 1;
}
static int load_sdk(const char *directory)
{
    const char *names[3] = {"libTSH.so", "blf.so", "libTSCANApiOnLinux.so"};
    char path[LIB_PATH_CAPACITY];
    unsigned int i;
    for (i = 0U; i < 3U; ++i) {
        int length = snprintf(path, sizeof(path), "%s/%s", directory, names[i]);
        if (length < 0 || (size_t)length >= sizeof(path)) return 0;
        driver.libraries[i] = dlopen(path, RTLD_NOW | (i < 2U ? RTLD_GLOBAL : RTLD_LOCAL));
        if (driver.libraries[i] == NULL) {
            const char *error = dlerror();
            /* Some vendor releases omit this optional logging library. */
            if (i == 1U) continue;
            fprintf(stderr, "TC1013: cannot load %s: %s\n", path,
                    error != NULL ? error : "unknown loader error");
            return 0;
        }
    }
#define LOAD(member, name) if (!load_symbol(name, &driver.member, sizeof(driver.member), 1)) return 0
    LOAD(initialize, "initialize_lib_tscan");
    LOAD(finalize, "finalize_lib_tscan");
    LOAD(connect, "tscan_connect");
    LOAD(disconnect, "tscan_disconnect_by_handle");
    LOAD(configure, "tscan_config_can_by_baudrate");
    LOAD(configure_fd, "tscan_config_canfd_by_baudrate");
    LOAD(transmit, "tscan_transmit_can_async");
    LOAD(transmit_fd, "tscan_transmit_canfd_async");
    LOAD(receive, "tsfifo_receive_can_msgs");
    LOAD(receive_fd, "tsfifo_receive_canfd_msgs");
    driver.channel_count = NULL;
    (void)load_symbol("tscan_get_can_channel_count", &driver.channel_count,
                      sizeof(driver.channel_count), 0);
#undef LOAD
    return 1;
}
static void release_sdk(void)
{
    int i;
    if (driver.connected) {
        uint32_t status = driver.disconnect(driver.handle);
        if (status != 0U) sdk_log("disconnect", status);
        driver.connected = 0;
    }
    if (driver.initialized) {
        driver.finalize();
        driver.initialized = 0;
    }
    for (i = 2; i >= 0; --i) {
        if (driver.libraries[i] != NULL) {
            dlclose(driver.libraries[i]);
            driver.libraries[i] = NULL;
        }
    }
    driver.handle = 0U;
    driver.directory[0] = '\0';
    driver.serial[0] = '\0';
}

static void report_async_error(unsigned int index, uint32_t token,
                               int32_t status, uint32_t code, int is_tx)
{
    int log_error = 0;
    pthread_mutex_lock(&queue_lock);
    if (driver.channels[index].token == token && token != 0U) {
        Channel *channel = &driver.channels[index];
        uint32_t *last = is_tx ? &channel->last_tx_error : &channel->last_rx_error;
        log_error = *last != code;
        *last = code;
        channel->pending_error = status;
    }
    pthread_mutex_unlock(&queue_lock);
    if (log_error) sdk_log(is_tx ? "async transmit" : "FIFO receive", code);
}
static int valid_rx(const VendorCANFD *frame, unsigned int index, uint8_t canfd)
{
    uint8_t error = (uint8_t)((frame->properties & 0x80U) != 0U || frame->identifier == -1);
    if (frame->channel != index || (frame->properties & 1U) != 0U || frame->dlc > (canfd ? 15U : 8U)) return 0;
    if (!error && (frame->identifier < 0 || (uint32_t)frame->identifier >
        ((frame->properties & 4U) ? 0x1FFFFFFFU : 0x7FFU))) return 0;
    if (canfd && ((frame->fd_properties & 1U) == 0U || (frame->properties & 2U) != 0U)) return 0;
    return 1;
}

static void *io_worker(void *unused)
{
    const struct timespec pause = {0, 1000000L};
    VendorCANFD tx[WORK_BATCH], rx[WORK_BATCH];
    VendorCAN classic_rx[WORK_BATCH];
    (void)unused;
    for (;;) {
        unsigned int index;
        int stop;
        pthread_mutex_lock(&queue_lock);
        stop = driver.stop;
        pthread_mutex_unlock(&queue_lock);
        if (stop) break;
        for (index = 0U; index < 2U; ++index) {
            unsigned int i, count = 0U;
            uint32_t token, status;
            uint8_t canfd;
            int32_t received = (int32_t)WORK_BATCH;
            pthread_mutex_lock(&queue_lock);
            token = driver.channels[index].token;
            canfd = driver.channels[index].canfd;
            if (token != 0U) {
                while (count < WORK_BATCH && pop(&driver.channels[index].tx, &tx[count])) ++count;
            }
            pthread_mutex_unlock(&queue_lock);
            if (token == 0U) continue;
            pthread_mutex_lock(&sdk_lock);
            /* A release/configure may have occurred before the SDK lock was acquired. */
            pthread_mutex_lock(&queue_lock);
            stop = driver.channels[index].token != token || driver.stop;
            pthread_mutex_unlock(&queue_lock);
            if (stop) {
                pthread_mutex_unlock(&sdk_lock);
                continue;
            }
            for (i = 0U; i < count; ++i) {
                if (canfd) {
                    status = driver.transmit_fd(driver.handle, &tx[i]);
                } else {
                    VendorCAN frame;
                    memcpy(&frame, &tx[i], sizeof(frame));
                    frame.reserved = 0U;
                    status = driver.transmit(driver.handle, &frame);
                }
                if (status != 0U) report_async_error(index, token, X280_CAN_TX_ERROR, status, 1);
            }
            if (canfd) {
                status = driver.receive_fd(driver.handle, rx, &received, (uint8_t)index, 0U);
            } else {
                status = driver.receive(driver.handle, classic_rx, &received, (uint8_t)index, 0U);
                if (status == 0U && received >= 0 && received <= (int32_t)WORK_BATCH) {
                    for (i = 0U; i < (unsigned int)received; ++i) {
                        memset(&rx[i], 0, sizeof(rx[i]));
                        memcpy(&rx[i], &classic_rx[i], sizeof(classic_rx[i]));
                        rx[i].fd_properties = 0U;
                    }
                }
            }
            pthread_mutex_unlock(&sdk_lock);
            if (status != 0U || received < 0 || received > (int32_t)WORK_BATCH) {
                report_async_error(index, token, X280_CAN_RX_ERROR, status != 0U ? status : UINT32_MAX, 0);
                continue;
            }
            pthread_mutex_lock(&queue_lock);
            if (driver.channels[index].token == token) {
                for (i = 0U; i < (unsigned int)received; ++i) {
                    if (!valid_rx(&rx[i], index, canfd)) {
                        driver.channels[index].pending_error = X280_CAN_RX_ERROR;
                    } else if (!push(&driver.channels[index].rx, &rx[i])) {
                        driver.channels[index].pending_error = X280_CAN_RX_OVERFLOW;
                    }
                }
            }
            pthread_mutex_unlock(&queue_lock);
        }
        nanosleep(&pause, NULL);
    }
    return NULL;
}
static int start_worker(void)
{
    pthread_attr_t attributes;
    struct sched_param scheduling;
    int status;
    memset(&scheduling, 0, sizeof(scheduling));
    status = pthread_attr_init(&attributes);
    if (status == 0) {
        status = pthread_attr_setinheritsched(&attributes, PTHREAD_EXPLICIT_SCHED);
        if (status == 0) status = pthread_attr_setschedpolicy(&attributes, SCHED_OTHER);
        if (status == 0) status = pthread_attr_setschedparam(&attributes, &scheduling);
        if (status == 0) status = pthread_create(&driver.worker, &attributes, io_worker, NULL);
        pthread_attr_destroy(&attributes);
    }
    if (status != 0) fprintf(stderr, "TC1013: cannot start SCHED_OTHER I/O worker: %s (%d)\n", strerror(status), status);
    return status;
}
static void setup_failure(unsigned int index, int32_t status)
{
    pthread_mutex_lock(&queue_lock);
    if (driver.channels[index].token == 0U) driver.channels[index].setup_status = status;
    else driver.channels[index].pending_error = status;
    pthread_mutex_unlock(&queue_lock);
    fprintf(stderr, "TC1013 CAN%u setup: %s (%d)\n", index + 1U, x280_can_status_string(status), (int)status);
}

int32_t x280_can_configure_channel(const char *library_dir, const char *serial,
                                  uint8_t channel, uint8_t canfd,
                                  double nominal_kbps, double data_kbps,
                                  uint8_t termination, uint32_t *ownership_token)
{
    unsigned int index;
    int32_t result = X280_CAN_SDK_ERROR, channel_count = 0;
    uint32_t status;
    int first;
    DirectoryGuard directory_guard = {-1, 0, {0}};
    if (ownership_token != NULL) *ownership_token = 0U;
    if (channel < 1U || channel > 2U) return X280_CAN_INVALID_ARGUMENT;
    index = channel - 1U;
    if (ownership_token == NULL || library_dir == NULL || library_dir[0] != '/' ||
        serial == NULL || strlen(library_dir) >= LIB_PATH_CAPACITY - 32U || strlen(serial) >= SERIAL_CAPACITY ||
        canfd > 1U || termination > 1U || !isfinite(nominal_kbps) || nominal_kbps < 5.0 || nominal_kbps > 1000.0 ||
        !isfinite(data_kbps) || (canfd && (data_kbps < nominal_kbps || data_kbps > 8000.0))) {
        setup_failure(index, X280_CAN_INVALID_ARGUMENT);
        return X280_CAN_INVALID_ARGUMENT;
    }
    pthread_mutex_lock(&lifecycle_lock);
    pthread_mutex_lock(&queue_lock);
    first = !driver.running;
    if (driver.channels[index].token != 0U) {
        pthread_mutex_unlock(&queue_lock);
        result = X280_CAN_ALREADY_OPEN;
        goto failed;
    }
    pthread_mutex_unlock(&queue_lock);
    if (!first && (strcmp(library_dir, driver.directory) != 0 || strcmp(serial, driver.serial) != 0)) {
        result = X280_CAN_DEVICE_CONFLICT;
        goto failed;
    }
    pthread_mutex_lock(&sdk_lock);
    if (!enter_sdk_directory(library_dir, &directory_guard)) {
        result = X280_CAN_DIRECTORY_ERROR;
        goto sdk_failed;
    }
    if (first) {
        if (!load_sdk(library_dir)) {
            result = X280_CAN_LIBRARY_ERROR;
            goto sdk_failed;
        }
        driver.initialize(true, false, false);
        driver.initialized = 1;
        status = driver.connect(serial[0] == '\0' ? NULL : serial, &driver.handle);
        if ((status != 0U && status != 5U) || driver.handle == 0U) {
            sdk_log("connect", status);
            goto sdk_failed;
        }
        driver.connected = 1;
    }
    if (driver.channel_count != NULL) {
        status = driver.channel_count(driver.handle, &channel_count);
        if (status != 0U || channel_count < (int32_t)channel) {
            fprintf(stderr, "TC1013: requested CAN%u, available %d (vendor status %u)\n", channel, (int)channel_count, (unsigned int)status);
            goto sdk_failed;
        }
    }
    status = canfd ? driver.configure_fd(driver.handle, (int)index, nominal_kbps, data_kbps, 1, 0, termination)
                   : driver.configure(driver.handle, (int)index, nominal_kbps, termination);
    if (status != 0U) {
        sdk_log(canfd ? "configure ISO CAN FD" : "configure CAN", status);
        goto sdk_failed;
    }
    if (!restore_directory(&directory_guard)) {
        result = X280_CAN_DIRECTORY_ERROR;
        goto sdk_failed;
    }
    if (first) {
        pthread_mutex_lock(&queue_lock);
        driver.stop = 0;
        pthread_mutex_unlock(&queue_lock);
        if (start_worker() != 0) {
            result = X280_CAN_THREAD_ERROR;
            goto sdk_failed;
        }
        strcpy(driver.directory, library_dir);
        strcpy(driver.serial, serial);
    }
    pthread_mutex_lock(&queue_lock);
    memset(&driver.channels[index], 0, sizeof(driver.channels[index]));
    ++next_token;
    if (next_token == 0U) ++next_token;
    driver.channels[index].token = next_token;
    driver.channels[index].canfd = canfd;
    driver.running = 1;
    *ownership_token = next_token;
    pthread_mutex_unlock(&queue_lock);
    pthread_mutex_unlock(&sdk_lock);
    pthread_mutex_unlock(&lifecycle_lock);
    return X280_CAN_OK;

sdk_failed:
    if (first) release_sdk();
    if (!restore_directory(&directory_guard)) result = X280_CAN_DIRECTORY_ERROR;
    pthread_mutex_unlock(&sdk_lock);
failed:
    setup_failure(index, result);
    pthread_mutex_unlock(&lifecycle_lock);
    return result;
}

void x280_can_release(uint32_t ownership_token)
{
    unsigned int index;
    int last = 0, found = 0;
    if (ownership_token == 0U) return;
    pthread_mutex_lock(&lifecycle_lock);
    /* Wait for any outstanding SDK call before invalidating this owner's token. */
    pthread_mutex_lock(&sdk_lock);
    pthread_mutex_lock(&queue_lock);
    for (index = 0U; index < 2U; ++index) {
        if (driver.channels[index].token == ownership_token) {
            memset(&driver.channels[index], 0, sizeof(driver.channels[index]));
            found = 1;
            break;
        }
    }
    if (found && driver.channels[0].token == 0U && driver.channels[1].token == 0U) {
        driver.stop = 1;
        last = 1;
    }
    pthread_mutex_unlock(&queue_lock);
    pthread_mutex_unlock(&sdk_lock);
    if (last) {
        pthread_join(driver.worker, NULL);
        release_sdk();
        pthread_mutex_lock(&queue_lock);
        driver.running = 0;
        pthread_mutex_unlock(&queue_lock);
    }
    pthread_mutex_unlock(&lifecycle_lock);
}

/* Caller holds queue_lock. Configuration errors persist until corrected. */
static int32_t channel_status(unsigned int index, uint8_t canfd)
{
    Channel *channel = &driver.channels[index];
    int32_t status;
    if (channel->token == 0U) return channel->setup_status != 0 ? channel->setup_status : X280_CAN_INVALID_DEVICE;
    if (channel->canfd != canfd) return X280_CAN_MODE_MISMATCH;
    status = channel->pending_error;
    channel->pending_error = 0;
    return status;
}
static int32_t queue_send(uint8_t channel, uint8_t canfd, const VendorCANFD *frame)
{
    int32_t status;
    if (pthread_mutex_trylock(&queue_lock) != 0) return X280_CAN_BUSY;
    status = channel_status(channel - 1U, canfd);
    if (status == 0 && !push(&driver.channels[channel - 1U].tx, frame)) status = X280_CAN_TX_FULL;
    pthread_mutex_unlock(&queue_lock);
    return status;
}
int32_t x280_can_send(uint8_t channel, uint32_t id, uint8_t extended, uint8_t remote,
                     uint8_t length, const uint8_t data[8])
{
    VendorCANFD frame;
    if (channel < 1U || channel > 2U || extended > 1U || remote > 1U || length > 8U ||
        data == NULL || id > (extended ? 0x1FFFFFFFU : 0x7FFU)) return X280_CAN_INVALID_ARGUMENT;
    memset(&frame, 0, sizeof(frame));
    frame.channel = (uint8_t)(channel - 1U);
    frame.identifier = (int32_t)id;
    frame.properties = (uint8_t)(1U | (extended << 2U) | (remote << 1U));
    frame.dlc = length;
    if (!remote) memcpy(frame.data, data, length);
    return queue_send(channel, 0U, &frame);
}
int32_t x280_can_send_fd(uint8_t channel, uint32_t id, uint8_t extended, uint8_t brs,
                        uint8_t esi, uint8_t length, const uint8_t data[64])
{
    VendorCANFD frame;
    int dlc = length_to_dlc(length);
    if (channel < 1U || channel > 2U || extended > 1U || brs > 1U || esi > 1U || dlc < 0 ||
        data == NULL || id > (extended ? 0x1FFFFFFFU : 0x7FFU)) return X280_CAN_INVALID_ARGUMENT;
    memset(&frame, 0, sizeof(frame));
    frame.channel = (uint8_t)(channel - 1U);
    frame.identifier = (int32_t)id;
    frame.properties = (uint8_t)(1U | (extended << 2U));
    frame.fd_properties = (uint8_t)(1U | (brs << 1U) | (esi << 2U));
    frame.dlc = (uint8_t)dlc;
    memcpy(frame.data, data, length);
    return queue_send(channel, 1U, &frame);
}
static int32_t queue_receive(uint8_t channel, uint8_t canfd, VendorCANFD *frame, uint8_t *received)
{
    int32_t status;
    if (pthread_mutex_trylock(&queue_lock) != 0) return X280_CAN_BUSY;
    status = channel_status(channel - 1U, canfd);
    if (status == 0 && pop(&driver.channels[channel - 1U].rx, frame)) *received = 1U;
    pthread_mutex_unlock(&queue_lock);
    return status;
}
int32_t x280_can_receive(uint8_t channel, uint32_t *id, uint8_t *extended, uint8_t *remote,
                        uint8_t *error, uint8_t *length, double *timestamp,
                        uint8_t data[8], uint8_t *received)
{
    VendorCANFD frame;
    int32_t status;
    if (id != NULL) *id = 0U;
    if (extended != NULL) *extended = 0U;
    if (remote != NULL) *remote = 0U;
    if (error != NULL) *error = 0U;
    if (length != NULL) *length = 0U;
    if (timestamp != NULL) *timestamp = 0.0;
    if (data != NULL) memset(data, 0, 8U);
    if (received != NULL) *received = 0U;
    if (channel < 1U || channel > 2U || id == NULL || extended == NULL || remote == NULL ||
        error == NULL || length == NULL || timestamp == NULL || data == NULL || received == NULL) return X280_CAN_INVALID_ARGUMENT;
    status = queue_receive(channel, 0U, &frame, received);
    if (*received) {
        *id = (uint32_t)frame.identifier;
        *extended = (uint8_t)((frame.properties >> 2U) & 1U);
        *remote = (uint8_t)((frame.properties >> 1U) & 1U);
        *error = (uint8_t)((frame.properties & 0x80U) != 0U || frame.identifier == -1);
        *length = frame.dlc;
        *timestamp = (double)frame.timestamp_us * 0.000001;
        if (!*remote) memcpy(data, frame.data, frame.dlc);
    }
    return status;
}
int32_t x280_can_receive_fd(uint8_t channel, uint32_t *id, uint8_t *extended,
                           uint8_t *brs, uint8_t *esi, uint8_t *error, uint8_t *length,
                           double *timestamp, uint8_t data[64], uint8_t *received)
{
    VendorCANFD frame;
    int32_t status;
    if (id != NULL) *id = 0U;
    if (extended != NULL) *extended = 0U;
    if (brs != NULL) *brs = 0U;
    if (esi != NULL) *esi = 0U;
    if (error != NULL) *error = 0U;
    if (length != NULL) *length = 0U;
    if (timestamp != NULL) *timestamp = 0.0;
    if (data != NULL) memset(data, 0, 64U);
    if (received != NULL) *received = 0U;
    if (channel < 1U || channel > 2U || id == NULL || extended == NULL || brs == NULL || esi == NULL ||
        error == NULL || length == NULL || timestamp == NULL || data == NULL || received == NULL) return X280_CAN_INVALID_ARGUMENT;
    status = queue_receive(channel, 1U, &frame, received);
    if (*received) {
        *id = (uint32_t)frame.identifier;
        *extended = (uint8_t)((frame.properties >> 2U) & 1U);
        *brs = (uint8_t)((frame.fd_properties >> 1U) & 1U);
        *esi = (uint8_t)((frame.fd_properties >> 2U) & 1U);
        *error = (uint8_t)((frame.properties & 0x80U) != 0U || frame.identifier == -1);
        *length = dlc_lengths[frame.dlc];
        *timestamp = (double)frame.timestamp_us * 0.000001;
        memcpy(data, frame.data, *length);
    }
    return status;
}
const char *x280_can_status_string(int32_t status)
{
    switch (status) {
    case X280_CAN_OK: return "success";
    case X280_CAN_INVALID_ARGUMENT: return "invalid CAN parameter";
    case X280_CAN_ALREADY_OPEN: return "duplicate CANSetup for channel";
    case X280_CAN_LIBRARY_ERROR: return "Linux vendor SDK or required symbol unavailable";
    case X280_CAN_SDK_ERROR: return "vendor SDK setup failed";
    case X280_CAN_INVALID_DEVICE: return "CAN channel has no active CANSetup";
    case X280_CAN_BUSY: return "CAN queue busy; retry next sample";
    case X280_CAN_TX_FULL: return "CAN transmit queue full; frame not queued";
    case X280_CAN_THREAD_ERROR: return "CAN I/O worker could not start";
    case X280_CAN_RX_OVERFLOW: return "CAN receive queue overflow; frames dropped";
    case X280_CAN_TX_ERROR: return "vendor async transmit failed; inspect target log";
    case X280_CAN_RX_ERROR: return "vendor receive failed or returned invalid frames";
    case X280_CAN_DEVICE_CONFLICT: return "CANSetup directory/serial must match the shared adapter";
    case X280_CAN_MODE_MISMATCH: return "CAN/CAN FD block type does not match CANSetup";
    case X280_CAN_DIRECTORY_ERROR: return "SDK working-directory initialization failed";
    default: return "unknown CAN status";
    }
}
