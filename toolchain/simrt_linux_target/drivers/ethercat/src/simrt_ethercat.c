#include "simrt_ethercat.h"
#include "ethercat.h"
#include <errno.h>
#include <net/if.h>
#include <pthread.h>
#include <string.h>

/* Each slave exposes at most 65535 input and output bits in SOEM 1.4. */
static uint8_t io_map[EC_MAXSLAVE * 16384u];
static uint32_t active_token, next_token, input_bytes, output_bytes, receive_timeout;
static int expected_counter;
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;

static void shutdown_master(void)
{
    ec_slave[0].state = EC_STATE_INIT;
    ec_writestate(0);
    ec_close();
    active_token = 0;
    input_bytes = output_bytes = 0;
    expected_counter = 0;
}

int32_t simrt_ethercat_open(const char *interface_name, uint32_t outputs,
    uint32_t inputs, uint32_t expected_slaves, uint32_t timeout_us,
    uint32_t *token, int32_t *expected_wkc)
{
    int status = 0, mapped, attempt, working_counter, segment;
    uint32_t segment_bytes = 0;
    if (token) *token = 0;
    if (expected_wkc) *expected_wkc = 0;
    if (!token || !expected_wkc || !interface_name || !*interface_name ||
        strlen(interface_name) >= IFNAMSIZ || outputs > 65536 || inputs > 65536 ||
        (!outputs && !inputs) || !expected_slaves || expected_slaves >= EC_MAXSLAVE ||
        !timeout_us || timeout_us > 1000000) return -EINVAL;
    pthread_mutex_lock(&lock);
    if (active_token) { status = -EBUSY; goto done; }
    errno = 0;
    if (!ec_init(interface_name)) {
        status = errno ? -errno : -ENODEV;
        ec_close();
        goto done;
    }
    if (ec_config_init(FALSE) != (int)expected_slaves) { status = -ENODEV; goto fail; }
    memset(io_map, 0, sizeof(io_map));
    mapped = ec_config_map(io_map);
    if (mapped <= 0 || (uint32_t)mapped > sizeof(io_map) ||
        ec_slave[0].Obytes != outputs || ec_slave[0].Ibytes != inputs) {
        status = -EMSGSIZE; goto fail;
    }
    if (!ec_group[0].nsegments || ec_group[0].nsegments > EC_MAXBUF) {
        status = -EMSGSIZE; goto fail;
    }
    for (segment = 0; segment < ec_group[0].nsegments; ++segment) {
        if (ec_group[0].IOsegment[segment] > EC_MAXLRWDATA - EC_FIRSTDCDATAGRAM) {
            status = -EMSGSIZE; goto fail;
        }
        segment_bytes += ec_group[0].IOsegment[segment];
    }
    if (segment_bytes != (uint32_t)mapped) { status = -EMSGSIZE; goto fail; }
    if (ec_statecheck(0, EC_STATE_SAFE_OP, EC_TIMEOUTSTATE * 4) != EC_STATE_SAFE_OP) {
        status = -EIO; goto fail;
    }
    expected_counter = ec_group[0].outputsWKC * 2 + ec_group[0].inputsWKC;
    if (expected_counter <= 0) { status = -EIO; goto fail; }
    /* EtherCAT requires a valid process image before requesting OP. */
    ec_send_processdata();
    ec_receive_processdata((int)timeout_us);
    ec_slave[0].state = EC_STATE_OPERATIONAL;
    ec_writestate(0);
    for (attempt = 0; attempt < 100; ++attempt) {
        ec_send_processdata();
        working_counter = ec_receive_processdata((int)timeout_us);
        if (ec_statecheck(0, EC_STATE_OPERATIONAL, EC_TIMEOUTRET) == EC_STATE_OPERATIONAL &&
            working_counter >= expected_counter) break;
    }
    if (attempt == 100) { status = -ETIMEDOUT; goto fail; }
    input_bytes = inputs; output_bytes = outputs; receive_timeout = timeout_us;
    if (++next_token == 0) ++next_token;
    active_token = next_token;
    *token = active_token; *expected_wkc = expected_counter;
    goto done;
fail:
    shutdown_master();
done:
    pthread_mutex_unlock(&lock);
    return status;
}

int32_t simrt_ethercat_exchange(uint32_t token, const uint8_t *outputs,
    uint32_t output_capacity, uint8_t *inputs, uint32_t input_capacity,
    int32_t *actual_wkc)
{
    int status = 0, count;
    if (actual_wkc) *actual_wkc = 0;
    if (!outputs || !inputs || !actual_wkc || input_capacity > 65536 ||
        output_capacity > 65536) return -EINVAL;
    memset(inputs, 0, input_capacity);
    if (pthread_mutex_trylock(&lock)) return -EAGAIN;
    if (!token || token != active_token) { status = -EBADF; goto done; }
    if (output_capacity < output_bytes || input_capacity < input_bytes) {
        status = -EMSGSIZE; goto done;
    }
    if (output_bytes) memcpy(ec_slave[0].outputs, outputs, output_bytes);
    if (ec_send_processdata() <= 0) { status = -EIO; goto done; }
    count = ec_receive_processdata((int)receive_timeout);
    *actual_wkc = count;
    if (count < expected_counter) { status = -EIO; goto done; }
    if (input_bytes) memcpy(inputs, ec_slave[0].inputs, input_bytes);
done:
    pthread_mutex_unlock(&lock);
    return status;
}

void simrt_ethercat_close(uint32_t token)
{
    pthread_mutex_lock(&lock);
    if (token && token == active_token) shutdown_master();
    pthread_mutex_unlock(&lock);
}
