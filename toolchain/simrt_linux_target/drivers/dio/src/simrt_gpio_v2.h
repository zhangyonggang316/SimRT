#ifndef SIMRT_GPIO_V2_H
#define SIMRT_GPIO_V2_H
#include <stdint.h>

/* Linux GPIO v2 UAPI subset for toolchains with pre-5.10 kernel headers.
 * Layout and ioctl numbers: include/uapi/linux/gpio.h in Linux v6.12.
 * https://docs.kernel.org/userspace-api/gpio/chardev.html
 * Use the installed UAPI whenever it already provides v2. */
#ifndef GPIO_V2_GET_LINE_IOCTL
#define GPIO_V2_LINES_MAX 64
#define GPIO_V2_LINE_NUM_ATTRS_MAX 10
#define GPIO_V2_LINE_FLAG_ACTIVE_LOW (UINT64_C(1) << 1)
#define GPIO_V2_LINE_FLAG_INPUT (UINT64_C(1) << 2)
#define GPIO_V2_LINE_FLAG_OUTPUT (UINT64_C(1) << 3)
#define GPIO_V2_LINE_ATTR_ID_OUTPUT_VALUES 2
typedef uint64_t simrt_gpio_aligned_u64 __attribute__((aligned(8)));
struct gpio_v2_line_values {
    simrt_gpio_aligned_u64 bits, mask;
};
struct gpio_v2_line_attribute {
    uint32_t id, padding;
    union {
        simrt_gpio_aligned_u64 flags, values;
        uint32_t debounce_period_us;
    };
};
struct gpio_v2_line_config_attribute {
    struct gpio_v2_line_attribute attr;
    simrt_gpio_aligned_u64 mask;
};
struct gpio_v2_line_config {
    simrt_gpio_aligned_u64 flags;
    uint32_t num_attrs, padding[5];
    struct gpio_v2_line_config_attribute attrs[GPIO_V2_LINE_NUM_ATTRS_MAX];
};
struct gpio_v2_line_request {
    uint32_t offsets[GPIO_V2_LINES_MAX];
    char consumer[32];
    struct gpio_v2_line_config config;
    uint32_t num_lines, event_buffer_size, padding[5];
    int32_t fd;
};
#define GPIO_V2_GET_LINE_IOCTL _IOWR(0xB4, 0x07, struct gpio_v2_line_request)
#define GPIO_V2_LINE_GET_VALUES_IOCTL _IOWR(0xB4, 0x0E, struct gpio_v2_line_values)
#define GPIO_V2_LINE_SET_VALUES_IOCTL _IOWR(0xB4, 0x0F, struct gpio_v2_line_values)
#endif

typedef char simrt_gpio_request_abi_check[(sizeof(struct gpio_v2_line_request) == 592) ? 1 : -1];
typedef char simrt_gpio_values_abi_check[(sizeof(struct gpio_v2_line_values) == 16) ? 1 : -1];
#endif
