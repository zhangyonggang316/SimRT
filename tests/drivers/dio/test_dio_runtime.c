#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

/* Replace only OS calls. The production resource and bitmap logic runs unchanged. */
#define SIMRT_DIO_PLATFORM_H
#define _IOWR(type, nr, data) (0xC0000000UL | ((unsigned long)sizeof(data) << 16) | ((type) << 8) | (nr))
#define O_RDONLY 0
#define O_CLOEXEC 02000000
#include "../../../toolchain/simrt_linux_target/drivers/dio/src/simrt_gpio_v2.h"
static int fake_open(const char *device, int flags);
static int fake_ioctl(int fd, unsigned long command, void *data);
static int fake_close(int fd);
#define open fake_open
#define ioctl fake_ioctl
#define close fake_close
#include "../../../toolchain/simrt_linux_target/drivers/dio/src/simrt_dio.c"
#undef open
#undef ioctl
#undef close

static int opened, closed, requests, reads, writes, fail_open, fail_request, fail_read, fail_write;
static int active[128], next_fd=10;
static uint64_t bits[128];
static struct gpio_v2_line_request last_request;
static uint64_t last_mask;

static int fake_open(const char *device, int flags)
{
    assert(!strcmp(device,"/dev/gpiochip0"));
    assert(flags==(O_RDONLY|O_CLOEXEC));
    ++opened;
    if (fail_open) { errno=fail_open; return -1; }
    return 3;
}
static int fake_ioctl(int fd, unsigned long command, void *data)
{
    if (command==GPIO_V2_GET_LINE_IOCTL) {
        struct gpio_v2_line_request *request=data;
        assert(fd==3);
        ++requests;
        last_request=*request;
        if (fail_request) { errno=fail_request; return -1; }
        request->fd=next_fd++;
        assert(request->fd<128);
        active[request->fd]=1;
        bits[request->fd]=request->config.num_attrs ? request->config.attrs[0].attr.values : 0;
    } else {
        struct gpio_v2_line_values *values=data;
        assert(active[fd]);
        last_mask=values->mask;
        if (command==GPIO_V2_LINE_GET_VALUES_IOCTL) {
            ++reads;
            if (fail_read) { errno=fail_read; return -1; }
            values->bits=bits[fd];
        } else {
            assert(command==GPIO_V2_LINE_SET_VALUES_IOCTL);
            ++writes;
            if (fail_write) { errno=fail_write; return -1; }
            bits[fd]=values->bits;
        }
    }
    return 0;
}
static int fake_close(int fd)
{
    assert(fd==3 || active[fd]);
    if (fd!=3) active[fd]=0;
    ++closed;
    return 0;
}

static void validation_and_failures(void)
{
    uint32_t token=99, offsets[2]={7,2};
    uint8_t initial[2]={0,1}, values[2]={1,1};
    int before=opened, closes;
    assert(simrt_dio_open("bad",offsets,2,0,0,initial,&token)==-EINVAL && token==0);
    assert(simrt_dio_open("/dev/gpiochip0",offsets,0,0,0,initial,&token)==-EINVAL);
    assert(simrt_dio_open("/dev/gpiochip0",offsets,65,0,0,initial,&token)==-EINVAL);
    assert(simrt_dio_open("/dev/gpiochip0",offsets,2,2,0,initial,&token)==-EINVAL);
    assert(simrt_dio_open("/dev/gpiochip0",offsets,2,0,2,initial,&token)==-EINVAL);
    offsets[1]=7;
    assert(simrt_dio_open("/dev/gpiochip0",offsets,2,0,0,initial,&token)==-EINVAL);
    offsets[1]=2;
    initial[1]=2;
    assert(simrt_dio_open("/dev/gpiochip0",offsets,2,1,0,initial,&token)==-EINVAL);
    initial[1]=1;
    assert(opened==before);
    assert(simrt_dio_read(0,values,2)==-EBADF && values[0]==0 && values[1]==0);
    fail_open=EACCES;
    assert(simrt_dio_open("/dev/gpiochip0",offsets,2,0,0,initial,&token)==-EACCES && token==0);
    fail_open=0;
    closes=closed;
    fail_request=ENOTTY;
    assert(simrt_dio_open("/dev/gpiochip0",offsets,2,0,0,initial,&token)==-ENOTTY && token==0);
    assert(closed==closes+1);
    fail_request=EBUSY;
    assert(simrt_dio_open("/dev/gpiochip0",offsets,2,0,0,initial,&token)==-EBUSY && token==0);
    fail_request=0;
}

static void input_output_and_ownership(void)
{
    uint32_t token, fresh, offsets[3]={7,2,19};
    uint8_t initial[3]={1,0,1}, values[3]={0,1,0};
    int fd, previous, closes;
    assert(simrt_dio_open("/dev/gpiochip0",offsets,3,1,1,initial,&token)==0);
    assert(token!=0 && last_request.num_lines==3);
    assert(!memcmp(last_request.offsets,offsets,sizeof(offsets)));
    assert(last_request.config.flags==(GPIO_V2_LINE_FLAG_OUTPUT|GPIO_V2_LINE_FLAG_ACTIVE_LOW));
    assert(last_request.config.num_attrs==1);
    assert(last_request.config.attrs[0].attr.id==GPIO_V2_LINE_ATTR_ID_OUTPUT_VALUES);
    assert(last_request.config.attrs[0].mask==7 && last_request.config.attrs[0].attr.values==5);
    assert(last_request.event_buffer_size==0 && last_request.padding[0]==0);
    fd=find_slot(token)->fd;
    assert(simrt_dio_read(token,values,3)==0 && !memcmp(values,initial,3));
    values[0]=0; values[1]=1; values[2]=0;
    assert(simrt_dio_write(token,values,3)==0 && bits[fd]==2 && last_mask==7);
    assert(simrt_dio_read(token,values,3)==0 && values[1]==1);
    previous=writes;
    values[1]=2;
    assert(simrt_dio_write(token,values,3)==-EINVAL && writes==previous);
    values[1]=1;
    assert(simrt_dio_write(token,values,2)==-EINVAL && writes==previous);
    fail_read=EIO;
    assert(simrt_dio_read(token,values,3)==-EIO && values[0]==0 && values[1]==0 && values[2]==0);
    fail_read=0;
    fail_write=ENODEV;
    assert(simrt_dio_write(token,initial,3)==-ENODEV);
    fail_write=0;
    pthread_mutex_lock(&lock);
    previous=reads;
    assert(simrt_dio_read(token,values,3)==-EAGAIN && reads==previous);
    previous=writes;
    assert(simrt_dio_write(token,values,3)==-EAGAIN && writes==previous);
    pthread_mutex_unlock(&lock);
    simrt_dio_close(token);
    assert(!active[fd]);
    assert(simrt_dio_read(token,values,3)==-EBADF);
    assert(simrt_dio_open("/dev/gpiochip0",offsets,3,0,0,initial,&fresh)==0 && fresh!=token);
    assert(last_request.config.flags==GPIO_V2_LINE_FLAG_INPUT && last_request.config.num_attrs==0);
    closes=closed;
    simrt_dio_close(token);
    assert(closed==closes && find_slot(fresh));
    previous=writes;
    assert(simrt_dio_write(fresh,initial,3)==-EPERM && writes==previous);
    assert(simrt_dio_read(fresh,values,3)==0);
    simrt_dio_close(fresh);
}

static void full_width_and_slot_capacity(void)
{
    uint32_t offsets[64], tokens[16], overflow=99, i;
    uint8_t initial[64], actual[64];
    int before;
    for (i=0;i<64;++i) { offsets[i]=63-i; initial[i]=(uint8_t)(i==0 || i==63); }
    assert(simrt_dio_open("/dev/gpiochip0",offsets,64,1,0,initial,&tokens[0])==0);
    assert(last_request.config.attrs[0].mask==UINT64_MAX);
    assert(last_request.config.attrs[0].attr.values==(UINT64_C(1)|(UINT64_C(1)<<63)));
    assert(simrt_dio_read(tokens[0],actual,64)==0 && !memcmp(actual,initial,64));
    memset(initial,1,64);
    assert(simrt_dio_write(tokens[0],initial,64)==0 && last_mask==UINT64_MAX);
    assert(simrt_dio_read(tokens[0],actual,64)==0 && !memcmp(actual,initial,64));
    for (i=1;i<16;++i)
        assert(simrt_dio_open("/dev/gpiochip0",offsets,1,0,0,initial,&tokens[i])==0);
    before=opened;
    assert(simrt_dio_open("/dev/gpiochip0",offsets,1,0,0,initial,&overflow)==-ENOSPC && overflow==0);
    assert(opened==before);
    for (i=0;i<16;++i) simrt_dio_close(tokens[i]);
}

int main(void)
{
    assert(GPIO_V2_GET_LINE_IOCTL==0xC250B407UL);
    assert(GPIO_V2_LINE_GET_VALUES_IOCTL==0xC010B40EUL);
    assert(GPIO_V2_LINE_SET_VALUES_IOCTL==0xC010B40FUL);
    validation_and_failures();
    input_output_and_ownership();
    full_width_and_slot_capacity();
    puts("GPIO v2 mock: ABI, parameters, atomic initial output, offsets, 64-bit masks, errno, ownership, contention, resource cleanup passed");
    return 0;
}
