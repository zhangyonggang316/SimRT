#ifndef SIMRT_ETHERCAT_H
#define SIMRT_ETHERCAT_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
int32_t simrt_ethercat_open(const char *interface_name, uint32_t outputs,
    uint32_t inputs, uint32_t expected_slaves, uint32_t timeout_us,
    uint32_t *token, int32_t *expected_wkc);
int32_t simrt_ethercat_exchange(uint32_t token, const uint8_t *outputs,
    uint32_t output_capacity, uint8_t *inputs, uint32_t input_capacity,
    int32_t *actual_wkc);
void simrt_ethercat_close(uint32_t token);
#ifdef __cplusplus
}
#endif
#endif
