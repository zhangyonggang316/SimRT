#define ioctl mock_ioctl
#define main physical_loopback_main
#include "serial_physical_loopback.c"
#undef main
#undef ioctl
#include <assert.h>
#include <stdarg.h>

static struct serial_rs485 state;
static int scenario, read_count, write_count;

int mock_ioctl(int fd, unsigned long request, ...)
{
    struct serial_rs485 *value;
    va_list arguments;
    assert(fd==42);
    va_start(arguments,request);
    value=va_arg(arguments,struct serial_rs485 *);
    va_end(arguments);
    if (request==TIOCGRS485) {
        ++read_count;
        if (scenario==2 || (scenario==5 && read_count==2)) { errno=EIO; return -1; }
        *value=state;
        return 0;
    }
    assert(request==TIOCSRS485);
    ++write_count;
    if (scenario==0 || scenario==3) { errno=ENOTTY; return -1; }
    if (scenario!=4) state=*value;
    return 0;
}

int main(void)
{
    struct serial_rs485 original;
    const int expected[]={0,0,-EIO,-ENOTTY,-EIO,-EIO};
    memset(&original,0,sizeof(original));
    for (scenario=0;scenario<6;++scenario) {
        memset(&state,0,sizeof(state));
        read_count=write_count=0;
        if (scenario) state.flags=SER_RS485_ENABLED;
        assert(restore_rs485_state(42,&original)==expected[scenario]);
        assert(write_count==((scenario==0 || scenario==2) ? 0 : 1));
    }
    puts("{\"passed\":true,\"tests\":6,\"physical_test\":false}");
    return 0;
}
