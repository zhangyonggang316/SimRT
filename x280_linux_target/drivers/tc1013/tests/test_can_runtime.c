/* Offline harness: production queues, lifecycle and threads; vendor API mocked. */
#define X280_CAN_TEST_HOST 1
#include <fcntl.h>
#include <unistd.h>
#include <stddef.h>
#ifndef O_DIRECTORY
#define O_DIRECTORY 0
#endif
#ifndef O_CLOEXEC
#define O_CLOEXEC 0
#endif
static int mock_directory_open(const char *path, int flags);
static int mock_directory_chdir(const char *path);
static int mock_directory_fchdir(int descriptor);
static char *mock_directory_getcwd(char *path, size_t size);
static int mock_directory_close(int descriptor);
#define open mock_directory_open
#define chdir mock_directory_chdir
#define fchdir mock_directory_fchdir
#define getcwd mock_directory_getcwd
#define close mock_directory_close
#include "../src/x280_tc1013_can.c"
#undef open
#undef chdir
#undef fchdir
#undef getcwd
#undef close
#include <assert.h>
#include <stdlib.h>

static pthread_mutex_t mock_lock = PTHREAD_MUTEX_INITIALIZER;
static int load_failure, symbol_failure, connect_failure;
static int current_sdk_layout;
static int config_failure_channel = -1;
static int connected_status, initialized_count, finalized_count, disconnected_count;
static int libraries_closed, connect_count, config_calls;
static int allow_transmit = 1, transmit_entered, transmit_count;
static int configured_mode[2];
static double configured_nominal[2], configured_data[2];
static uint32_t configured_term[2];
static uint32_t transmit_error, receive_error;
static VendorCANFD delivered[2], last_sent;
static int deliver_count[2], invalid_receive_count;
static int last_send_fd;
static int mock_cwd, cwd_descriptors, cwd_changes;
static int cwd_open_failure, cwd_getcwd_failure, cwd_enter_failure;
static int cwd_restore_failure, cwd_restore_eintr, cwd_fallback_failure, cwd_close_failure;

static int mock_directory_open(const char *path, int flags)
{
    (void)flags;
    assert(strcmp(path, ".") == 0 && mock_cwd == 0 && cwd_descriptors == 0);
    if (cwd_open_failure) { errno = EMFILE; return -1; }
    ++cwd_descriptors;
    return 77;
}
static char *mock_directory_getcwd(char *path, size_t size)
{
    assert(mock_cwd == 0 && size > 10U);
    if (cwd_getcwd_failure) { errno = ENOENT; return NULL; }
    strcpy(path, "/original");
    return path;
}
static int mock_directory_chdir(const char *path)
{
    if (strcmp(path, "/mock") == 0) {
        assert(mock_cwd == 0);
        if (cwd_enter_failure) { errno = EACCES; return -1; }
        mock_cwd = 1;
    } else {
        assert(strcmp(path, "/original") == 0 && mock_cwd == 1);
        if (cwd_fallback_failure) { errno = EACCES; return -1; }
        mock_cwd = 0;
    }
    ++cwd_changes;
    return 0;
}
static int mock_directory_fchdir(int descriptor)
{
    assert(descriptor == 77 && cwd_descriptors == 1 && mock_cwd == 1);
    if (cwd_restore_failure) { errno = EACCES; return -1; }
    if (cwd_restore_eintr) { --cwd_restore_eintr; errno = EINTR; return -1; }
    mock_cwd = 0;
    ++cwd_changes;
    return 0;
}
static int mock_directory_close(int descriptor)
{
    assert(descriptor == 77 && cwd_descriptors == 1);
    --cwd_descriptors;
    if (cwd_close_failure) { errno = EIO; return -1; }
    return 0;
}

static void tick(void)
{
    const struct timespec pause = {0, 1000000L};
    nanosleep(&pause, NULL);
}
static void mock_initialize(bool fifo, bool errors, bool turbo)
{
    assert(mock_cwd == 1);
    assert(fifo && !errors && !turbo);
    ++initialized_count;
}
static void mock_finalize(void) { ++finalized_count; }
static uint32_t mock_connect(const char *serial, size_t *handle)
{
    assert(mock_cwd == 1);
    assert(serial == NULL || strcmp(serial, "test-serial") == 0);
    ++connect_count;
    *handle = connect_failure ? 0U : (size_t)0x1234567887654321ULL;
    return connect_failure ? 99U : (uint32_t)connected_status;
}
static uint32_t mock_disconnect(size_t handle)
{
    assert(handle == (size_t)0x1234567887654321ULL);
    ++disconnected_count;
    return 0U;
}
static uint32_t mock_configure(size_t handle, int channel, double rate, uint32_t termination)
{
    assert(mock_cwd == 1);
    assert(handle == (size_t)0x1234567887654321ULL && channel >= 0 && channel < 2);
    ++config_calls;
    configured_mode[channel] = 0;
    configured_nominal[channel] = rate;
    configured_term[channel] = termination;
    return config_failure_channel == channel ? 78U : 0U;
}
static uint32_t mock_configure_fd(size_t handle, int channel, double nominal,
                                 double data, int controller, int mode, uint32_t termination)
{
    uint32_t status = mock_configure(handle, channel, nominal, termination);
    assert(controller == 1 && mode == 0);
    configured_mode[channel] = 1;
    configured_data[channel] = data;
    return status;
}
static uint32_t mock_channel_count(size_t handle, int32_t *count)
{
    assert(handle != 0U);
    *count = 2;
    return 0U;
}
static uint32_t mock_send(size_t handle, const VendorCANFD *frame, int canfd)
{
    int allowed;
    uint32_t result;
    assert(mock_cwd == 0);
    assert(handle == (size_t)0x1234567887654321ULL);
    for (;;) {
        pthread_mutex_lock(&mock_lock);
        transmit_entered = 1;
        allowed = allow_transmit;
        pthread_mutex_unlock(&mock_lock);
        if (allowed) break;
        tick();
    }
    pthread_mutex_lock(&mock_lock);
    last_sent = *frame;
    last_send_fd = canfd;
    ++transmit_count;
    result = transmit_error;
    pthread_mutex_unlock(&mock_lock);
    return result;
}
static uint32_t mock_transmit(size_t handle, const VendorCAN *frame)
{
    VendorCANFD canonical;
    assert(frame->reserved == 0U && frame->dlc <= 8U);
    memset(&canonical, 0, sizeof(canonical));
    memcpy(&canonical, frame, sizeof(*frame));
    return mock_send(handle, &canonical, 0);
}
static uint32_t mock_transmit_fd(size_t handle, const VendorCANFD *frame)
{
    assert(frame->dlc <= 15U && (frame->fd_properties & 1U) == 1U);
    assert((frame->properties & 2U) == 0U);
    return mock_send(handle, frame, 1);
}
static uint32_t mock_read(size_t handle, void *buffer, int32_t *count,
                          uint8_t channel, uint8_t rx_tx, int canfd)
{
    int32_t i;
    uint32_t result;
    assert(mock_cwd == 0);
    assert(handle == (size_t)0x1234567887654321ULL && channel < 2U && rx_tx == 0U);
    assert(*count == (int32_t)WORK_BATCH);
    pthread_mutex_lock(&mock_lock);
    result = receive_error;
    if (invalid_receive_count) *count = (int32_t)WORK_BATCH + 1;
    else {
        int32_t amount = deliver_count[channel] < *count ? deliver_count[channel] : *count;
        for (i = 0; i < amount; ++i) {
            if (canfd) ((VendorCANFD *)buffer)[i] = delivered[channel];
            else memcpy(&((VendorCAN *)buffer)[i], &delivered[channel], sizeof(VendorCAN));
        }
        deliver_count[channel] -= amount;
        *count = amount;
    }
    pthread_mutex_unlock(&mock_lock);
    return result;
}
static uint32_t mock_receive(size_t handle, const VendorCAN *buffer, int32_t *count, uint8_t channel, uint8_t rx_tx)
{
    return mock_read(handle, (void *)buffer, count, channel, rx_tx, 0);
}
static uint32_t mock_receive_fd(size_t handle, const VendorCANFD *buffer, int32_t *count, uint8_t channel, uint8_t rx_tx)
{
    return mock_read(handle, (void *)buffer, count, channel, rx_tx, 1);
}

void *dlopen(const char *path, int mode)
{
    assert(mock_cwd == 1);
    assert(strncmp(path, "/mock/", 6U) == 0 && (mode & RTLD_NOW) != 0);
    return (load_failure || (current_sdk_layout && strstr(path, "/blf.so") != NULL))
        ? NULL : (void *)(size_t)1U;
}
char *dlerror(void) { return NULL; }
int dlclose(void *library) { assert(library != NULL); ++libraries_closed; return 0; }
void *dlsym(void *library, const char *name)
{
    assert(library != NULL);
    if (symbol_failure) return NULL;
    if (current_sdk_layout && strcmp(name, "tscan_get_can_channel_count") == 0) return NULL;
#define SYMBOL(text, function) if (strcmp(name, text) == 0) return (void *)(function)
    SYMBOL("initialize_lib_tscan", mock_initialize);
    SYMBOL("finalize_lib_tscan", mock_finalize);
    SYMBOL("tscan_connect", mock_connect);
    SYMBOL("tscan_disconnect_by_handle", mock_disconnect);
    SYMBOL("tscan_config_can_by_baudrate", mock_configure);
    SYMBOL("tscan_config_canfd_by_baudrate", mock_configure_fd);
    SYMBOL("tscan_get_can_channel_count", mock_channel_count);
    SYMBOL("tscan_transmit_can_async", mock_transmit);
    SYMBOL("tscan_transmit_canfd_async", mock_transmit_fd);
    SYMBOL("tsfifo_receive_can_msgs", mock_receive);
    SYMBOL("tsfifo_receive_canfd_msgs", mock_receive_fd);
#undef SYMBOL
    return NULL;
}

static int32_t setup(uint8_t channel, uint8_t canfd, uint32_t *token)
{
    int32_t status = x280_can_configure_channel("/mock", "", channel, canfd, 500.0, 2000.0,
                                               (uint8_t)(channel == 1U), token);
    assert(mock_cwd == 0 && cwd_descriptors == 0);
    return status;
}
static int32_t send_classic(uint8_t channel)
{
    const uint8_t data[8] = {0xA5U, 0x5AU};
    return x280_can_send(channel, 0x123U, 0U, 0U, 2U, data);
}
static int32_t receive_classic(uint8_t channel, uint8_t *received)
{
    uint32_t id = 99U;
    uint8_t extended = 9U, remote = 9U, error = 9U, length = 9U, data[8];
    double timestamp = -1.0;
    int32_t status;
    memset(data, 9, sizeof(data));
    status = x280_can_receive(channel, &id, &extended, &remote, &error, &length, &timestamp, data, received);
    if (!*received) {
        unsigned int i;
        assert(id == 0U && extended == 0U && remote == 0U && error == 0U && length == 0U && timestamp == 0.0);
        for (i = 0U; i < 8U; ++i) assert(data[i] == 0U);
    } else {
        assert(id == 0x123U && !extended && !remote && !error && length == 2U);
        assert(timestamp == 1.25 && data[0] == 0xA5U && data[1] == 0x5AU);
    }
    return status;
}
static int32_t receive_fd(uint8_t channel, uint8_t *received, uint8_t expected_dlc)
{
    uint32_t id = 99U;
    uint8_t extended = 9U, brs = 9U, esi = 9U, error = 9U, length = 9U, data[64];
    double timestamp = -1.0;
    int32_t status;
    unsigned int i;
    memset(data, 9, sizeof(data));
    status = x280_can_receive_fd(channel, &id, &extended, &brs, &esi, &error, &length, &timestamp, data, received);
    if (!*received) {
        assert(id == 0U && extended == 0U && brs == 0U && esi == 0U && error == 0U && length == 0U && timestamp == 0.0);
        for (i = 0U; i < 64U; ++i) assert(data[i] == 0U);
    } else {
        assert(id == 0x1ABCDEU && extended == 1U && brs == 1U && esi == 1U && error == 0U);
        assert(length == dlc_lengths[expected_dlc] && timestamp == 1.25);
        for (i = 0U; i < length; ++i) assert(data[i] == (uint8_t)i);
        for (; i < 64U; ++i) assert(data[i] == 0U);
    }
    return status;
}
static void wait_for_error(uint8_t channel, int32_t expected, uint8_t canfd)
{
    unsigned int i;
    for (i = 0U; i < 1000U; ++i) {
        uint8_t received = 0U;
        int32_t status = canfd ? receive_fd(channel, &received, 0U) : receive_classic(channel, &received);
        if (status == expected) return;
        assert(status == 0 || status == X280_CAN_BUSY);
        tick();
    }
    assert(!"expected asynchronous error was not reported");
}
static void wait_for_tx(int target)
{
    unsigned int i;
    for (i = 0U; i < 1000U; ++i) {
        int done;
        pthread_mutex_lock(&mock_lock);
        done = transmit_count >= target;
        pthread_mutex_unlock(&mock_lock);
        if (done) return;
        tick();
    }
    assert(!"transmit worker did not run");
}
static void set_delivery(uint8_t channel, int canfd, uint8_t dlc, int count)
{
    unsigned int i, index = channel - 1U;
    pthread_mutex_lock(&mock_lock);
    memset(&delivered[index], 0, sizeof(delivered[index]));
    delivered[index].channel = (uint8_t)index;
    delivered[index].identifier = canfd ? 0x1ABCDE : 0x123;
    delivered[index].properties = canfd ? 4U : 0U;
    delivered[index].fd_properties = canfd ? 7U : 0U;
    delivered[index].dlc = dlc;
    delivered[index].timestamp_us = 1250000U;
    for (i = 0U; i < 64U; ++i) delivered[index].data[i] = (uint8_t)i;
    if (!canfd) { delivered[index].data[0] = 0xA5U; delivered[index].data[1] = 0x5AU; }
    deliver_count[index] = count;
    pthread_mutex_unlock(&mock_lock);
}

int main(int argc, char **argv)
{
    uint32_t first, second, rejected, old;
    uint8_t received = 1U, data[64];
    unsigned int i, code;
    int32_t status;
    int baseline, before;
    if (argc == 2 && strcmp(argv[1], "--fatal-cwd-restore") == 0) {
        cwd_restore_failure = 1;
        cwd_fallback_failure = 1;
        (void)setup(1U, 0U, &rejected);
        return 99;
    }
    for (i = 0U; i < 64U; ++i) data[i] = (uint8_t)i;
    assert(sizeof(VendorCAN) == 24U && sizeof(VendorCANFD) == 80U);
    assert(offsetof(VendorCANFD, timestamp_us) == 8U && offsetof(VendorCANFD, data) == 16U);
    assert(receive_classic(1U, &received) == X280_CAN_INVALID_DEVICE && !received);
    assert(x280_can_configure_channel("relative", "", 1U, 0U, 500.0, 2000.0, 1U, &rejected) == X280_CAN_INVALID_ARGUMENT);
    assert(receive_classic(1U, &received) == X280_CAN_INVALID_ARGUMENT && !received);
    assert(x280_can_configure_channel("/mock", "", 1U, 1U, 500.0, 250.0, 1U, &rejected) == X280_CAN_INVALID_ARGUMENT);
    load_failure = 1;
    assert(setup(1U, 0U, &rejected) == X280_CAN_LIBRARY_ERROR && rejected == 0U);
    assert(send_classic(1U) == X280_CAN_LIBRARY_ERROR);
    load_failure = 0;
    symbol_failure = 1;
    assert(setup(1U, 0U, &rejected) == X280_CAN_LIBRARY_ERROR);
    assert(libraries_closed == 3 && initialized_count == 0);
    symbol_failure = 0;
    connect_failure = 1;
    assert(setup(1U, 0U, &rejected) == X280_CAN_SDK_ERROR);
    assert(finalized_count == 1 && disconnected_count == 0);
    connect_failure = 0;
    config_failure_channel = 0;
    assert(setup(1U, 0U, &rejected) == X280_CAN_SDK_ERROR);
    assert(finalized_count == 2 && disconnected_count == 1);
    config_failure_channel = -1;

    connected_status = 5;
    assert(setup(1U, 0U, &first) == 0 && first != 0U);
    before = connect_count;
    assert(setup(1U, 0U, &rejected) == X280_CAN_ALREADY_OPEN && rejected == 0U);
    x280_can_release(rejected);
    assert(send_classic(1U) == X280_CAN_ALREADY_OPEN);
    assert(x280_can_configure_channel("/other", "", 2U, 0U, 500.0, 2000.0, 1U, &rejected) == X280_CAN_DEVICE_CONFLICT);
    assert(receive_classic(2U, &received) == X280_CAN_DEVICE_CONFLICT && !received);
    assert(x280_can_configure_channel("/mock", "test-serial", 2U, 0U, 500.0, 2000.0, 1U, &rejected) == X280_CAN_DEVICE_CONFLICT);
    config_failure_channel = 1;
    assert(setup(2U, 0U, &rejected) == X280_CAN_SDK_ERROR && rejected == 0U);
    assert(finalized_count == 2);
    config_failure_channel = -1;
    assert(setup(2U, 0U, &second) == 0 && second != first);
    assert(connect_count == before && configured_term[0] == 1U && configured_term[1] == 0U);
    assert(configured_nominal[0] == 500.0 && configured_nominal[1] == 500.0);
    assert(x280_can_send(0U, 0U, 0U, 0U, 8U, data) == X280_CAN_INVALID_ARGUMENT);
    assert(x280_can_send(1U, 0x800U, 0U, 0U, 8U, data) == X280_CAN_INVALID_ARGUMENT);
    assert(x280_can_send(1U, 0U, 0U, 0U, 9U, data) == X280_CAN_INVALID_ARGUMENT);
    pthread_mutex_lock(&queue_lock);
    assert(send_classic(1U) == X280_CAN_BUSY);
    assert(receive_classic(1U, &received) == X280_CAN_BUSY && !received);
    pthread_mutex_unlock(&queue_lock);
    pthread_mutex_lock(&mock_lock);
    allow_transmit = 0;
    transmit_entered = 0;
    pthread_mutex_unlock(&mock_lock);
    do { status = send_classic(1U); } while (status == X280_CAN_BUSY);
    assert(status == 0);
    for (i = 0U; i < 1000U; ++i) {
        int entered;
        pthread_mutex_lock(&mock_lock); entered = transmit_entered; pthread_mutex_unlock(&mock_lock);
        if (entered) break;
        tick();
    }
    assert(i < 1000U);
    for (i = 0U; i < QUEUE_CAPACITY; ++i) assert(send_classic(1U) == 0);
    assert(send_classic(1U) == X280_CAN_TX_FULL);
    assert(receive_classic(2U, &received) == 0 && !received);
    pthread_mutex_lock(&mock_lock); allow_transmit = 1; pthread_mutex_unlock(&mock_lock);
    x280_can_release(first);
    assert(send_classic(1U) == X280_CAN_INVALID_DEVICE);
    assert(driver.running && finalized_count == 2);
    old = first;
    assert(setup(1U, 0U, &first) == 0 && first != old);
    x280_can_release(old);
    assert(driver.channels[0].token == first && driver.channels[1].token == second);

    set_delivery(1U, 0, 2U, 1);
    for (i = 0U; i < 1000U; ++i) {
        status = receive_classic(1U, &received);
        assert(status == 0 || status == X280_CAN_BUSY);
        if (received) break;
        tick();
    }
    assert(received);
    pthread_mutex_lock(&mock_lock); receive_error = 54U; pthread_mutex_unlock(&mock_lock);
    wait_for_error(1U, X280_CAN_RX_ERROR, 0U);
    pthread_mutex_lock(&mock_lock); receive_error = 0U; invalid_receive_count = 1; pthread_mutex_unlock(&mock_lock);
    wait_for_error(1U, X280_CAN_RX_ERROR, 0U);
    pthread_mutex_lock(&mock_lock); invalid_receive_count = 0; transmit_error = 87U; pthread_mutex_unlock(&mock_lock);
    do { status = send_classic(1U); } while (status == X280_CAN_BUSY || status == X280_CAN_RX_ERROR);
    assert(status == 0);
    wait_for_error(1U, X280_CAN_TX_ERROR, 0U);
    pthread_mutex_lock(&mock_lock); transmit_error = 0U; pthread_mutex_unlock(&mock_lock);
    set_delivery(1U, 0, 2U, (int)QUEUE_CAPACITY + (int)WORK_BATCH);
    for (i = 0U; i < 40U; ++i) tick();
    wait_for_error(1U, X280_CAN_RX_OVERFLOW, 0U);
    x280_can_release(first);
    x280_can_release(second);
    assert(finalized_count == 3 && !driver.running);

    assert(setup(1U, 1U, &first) == 0);
    assert(setup(2U, 1U, &second) == 0);
    assert(configured_mode[0] == 1 && configured_mode[1] == 1 && configured_data[0] == 2000.0);
    assert(send_classic(1U) == X280_CAN_MODE_MISMATCH);
    assert(receive_classic(1U, &received) == X280_CAN_MODE_MISMATCH && !received);
    assert(x280_can_send_fd(1U, 0x123U, 0U, 1U, 0U, 9U, data) == X280_CAN_INVALID_ARGUMENT);
    assert(x280_can_send_fd(1U, 0x123U, 0U, 2U, 0U, 12U, data) == X280_CAN_INVALID_ARGUMENT);
    for (code = 0U; code < 16U; ++code) {
        pthread_mutex_lock(&mock_lock); baseline = transmit_count; pthread_mutex_unlock(&mock_lock);
        do { status = x280_can_send_fd(1U, 0x1ABCDEU, 1U, 1U, 1U, dlc_lengths[code], data); } while (status == X280_CAN_BUSY);
        assert(status == 0);
        wait_for_tx(baseline + 1);
        pthread_mutex_lock(&mock_lock);
        assert(last_send_fd == 1 && last_sent.dlc == code && last_sent.fd_properties == 7U && last_sent.properties == 5U);
        assert(last_sent.channel == 0U && last_sent.identifier == 0x1ABCDE);
        for (i = 0U; i < dlc_lengths[code]; ++i) assert(last_sent.data[i] == (uint8_t)i);
        for (; i < 64U; ++i) assert(last_sent.data[i] == 0U);
        pthread_mutex_unlock(&mock_lock);
        set_delivery(2U, 1, (uint8_t)code, 1);
        for (i = 0U; i < 1000U; ++i) {
            status = receive_fd(2U, &received, (uint8_t)code);
            assert(status == 0 || status == X280_CAN_BUSY);
            if (received) break;
            tick();
        }
        assert(received);
    }
    set_delivery(1U, 1, 16U, 1);
    wait_for_error(1U, X280_CAN_RX_ERROR, 1U);
    x280_can_release(first);
    assert(driver.running);
    x280_can_release(second);
    x280_can_release(second);
    assert(finalized_count == initialized_count && !driver.running);
    assert(receive_fd(1U, &received, 0U) == X280_CAN_INVALID_DEVICE && !received);
    current_sdk_layout = 1;
    before = libraries_closed;
    assert(setup(1U, 0U, &first) == 0);
    assert(setup(2U, 1U, &second) == 0);
    assert(driver.channel_count == NULL);
    x280_can_release(first);
    x280_can_release(second);
    assert(libraries_closed == before + 2);
    assert(finalized_count == initialized_count && !driver.running);
    before = initialized_count;
    cwd_open_failure = 1;
    assert(setup(1U, 0U, &rejected) == X280_CAN_DIRECTORY_ERROR && rejected == 0U);
    cwd_open_failure = 0;
    cwd_getcwd_failure = 1;
    assert(setup(1U, 0U, &rejected) == X280_CAN_DIRECTORY_ERROR && rejected == 0U);
    cwd_getcwd_failure = 0;
    cwd_enter_failure = 1;
    assert(setup(1U, 0U, &rejected) == X280_CAN_DIRECTORY_ERROR && rejected == 0U);
    cwd_enter_failure = 0;
    assert(initialized_count == before && !driver.running);
    cwd_restore_failure = 1;
    assert(setup(1U, 0U, &rejected) == X280_CAN_DIRECTORY_ERROR && rejected == 0U);
    cwd_restore_failure = 0;
    assert(finalized_count == initialized_count && !driver.running);
    cwd_close_failure = 1;
    assert(setup(1U, 0U, &rejected) == X280_CAN_DIRECTORY_ERROR && rejected == 0U);
    cwd_close_failure = 0;
    assert(finalized_count == initialized_count && !driver.running);
    cwd_restore_eintr = 1;
    assert(setup(1U, 0U, &first) == 0 && cwd_restore_eintr == 0);
    before = cwd_changes;
    for (i = 0U; i < 10U; ++i) {
        status = receive_classic(1U, &received);
        assert(status == 0 || status == X280_CAN_BUSY);
    }
    assert(cwd_changes == before && mock_cwd == 0);
    x280_can_release(first);
    assert(finalized_count == initialized_count && !driver.running && mock_cwd == 0 && cwd_descriptors == 0);
    printf("TC1013 CAN/CAN FD runtime: ABI, per-channel ownership, setup errors, queues, DLC0..15, BRS/ESI and lifecycle tests passed\n");
    return 0;
}
