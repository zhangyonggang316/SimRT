#pragma once

#include <stdint.h>

#if defined(_WIN32)
#define XCP_API __declspec(dllexport)
#else
#define XCP_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef struct xcp_point { double elapsed_seconds; double value; } xcp_point;
typedef struct xcp_stats {
    double latest;
    double minimum;
    double maximum;
    uint64_t count;
} xcp_stats;

/* All functions return 0 on success, -1 on error; error text is thread-local.
 * Handles and signal ids are opaque. Destruction may overlap an in-flight call.
 * Snapshot memory belongs to the caller; no allocator crosses the DLL boundary. */
XCP_API uint32_t xcp_core_abi_version(void);
XCP_API const char* xcp_core_last_error(void);
XCP_API int xcp_core_create(uint64_t capacity, uint64_t* handle);
XCP_API int xcp_core_destroy(uint64_t handle);
XCP_API int xcp_core_ensure_signal(uint64_t handle, const char* name, uint64_t* signal);
XCP_API int xcp_core_append(uint64_t handle, const uint64_t* signals,
                            const double* times, const double* values, uint64_t count);
XCP_API int xcp_core_clear(uint64_t handle);
XCP_API int xcp_core_total(uint64_t handle, uint64_t* count);
XCP_API int xcp_core_stats(uint64_t handle, uint64_t signal, xcp_stats* stats);
XCP_API int xcp_core_snapshot(uint64_t handle, uint64_t signal,
                              xcp_point* output, uint64_t capacity, uint64_t* written);
XCP_API int xcp_core_plot(uint64_t handle, uint64_t signal, uint64_t max_points,
                          xcp_point* output, uint64_t capacity, uint64_t* written);
/* Visible range includes adjacent raw samples so lines cross viewport edges. */
XCP_API int xcp_core_plot_range(uint64_t handle, uint64_t signal, double first, double last,
                                uint64_t max_points, xcp_point* output,
                                uint64_t capacity, uint64_t* written);
XCP_API int xcp_core_value_at(uint64_t handle, uint64_t signal, double time,
                              double* value, int* found, int* interpolated);

#ifdef __cplusplus
}
#endif
