/* Linux-only SDK fixture: a vendor-owned pthread destructor outlives finalize. */
#include <assert.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>

#ifdef TC1013_TEST_PLACEHOLDER
int tc1013_test_placeholder;
#else
static pthread_key_t key;
static pthread_once_t key_once = PTHREAD_ONCE_INIT;
static unsigned int destructor_count;
static void destroy_value(void *value)
{
    free(value);
    ++destructor_count;
}
static void create_key(void) { assert(pthread_key_create(&key, destroy_value) == 0); }
void initialize_lib_tscan(bool a, bool b, bool c)
{
    (void)a; (void)b; (void)c;
    assert(pthread_once(&key_once, create_key) == 0);
}
void finalize_lib_tscan(void) { }
uint32_t tscan_connect(const char *serial, size_t *handle)
{
    void *value = malloc(1);
    (void)serial;
    assert(value != NULL && pthread_setspecific(key, value) == 0);
    *handle = 1;
    return 0;
}
uint32_t tscan_disconnect_by_handle(size_t handle) { (void)handle; return 0; }
uint32_t tscan_config_can_by_baudrate(size_t h, int c, double n, uint32_t t)
{
    (void)h; (void)c; (void)n; (void)t; return 0;
}
uint32_t tscan_config_canfd_by_baudrate(size_t h, int c, double n, double d,
                                      int f, int m, uint32_t t)
{
    (void)d; (void)f; (void)m;
    return tscan_config_can_by_baudrate(h, c, n, t);
}
uint32_t tscan_transmit_can_async(size_t h, const void *frame)
{
    (void)h; (void)frame; return 0;
}
uint32_t tscan_transmit_canfd_async(size_t h, const void *frame)
{
    return tscan_transmit_can_async(h, frame);
}
uint32_t tsfifo_receive_can_msgs(size_t h, const void *frames, int32_t *count,
                                uint8_t channel, uint8_t mode)
{
    (void)h; (void)frames; (void)channel; (void)mode;
    *count = 0; return 0;
}
uint32_t tsfifo_receive_canfd_msgs(size_t h, const void *frames, int32_t *count,
                                  uint8_t channel, uint8_t mode)
{
    return tsfifo_receive_can_msgs(h, frames, count, channel, mode);
}
uint32_t tscan_get_can_channel_count(size_t h, int32_t *count)
{
    (void)h; *count = 2; return 0;
}
unsigned int tc1013_test_destructors(void) { return destructor_count; }
#endif
