#ifndef _DEFAULT_SOURCE
#define _DEFAULT_SOURCE
#endif
#include "simrt_serial.h"
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <pty.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

int main(void)
{
    int master, slave, attempt;
    char device[128];
    uint32_t token = 99, duplicate = 99, sent, received, stale;
    uint8_t payload[] = {0, 1, 10, 13, 127, 128, 255}, actual[32];
    assert(simrt_serial_open("/invalid",115200,8,0,1,0,1,0,0,&token)==-EINVAL);
    assert(token==0);
    assert(openpty(&master,&slave,device,NULL,NULL)==0);
    close(slave);
    assert(simrt_serial_open(device,115200,8,0,1,0,1,0,0,&token)==0 && token!=0);
    assert(simrt_serial_open(device,115200,8,0,1,0,1,0,0,&duplicate)==-EBUSY);
    assert(duplicate==0);
    assert(simrt_serial_receive(token,actual,sizeof(actual),&received)==0 && received==0);
    assert(simrt_serial_send(token,payload,8,7,&sent)==-EINVAL && sent==0);
    assert(simrt_serial_send(token,payload,7,7,&sent)==0 && sent==7);
    assert(read(master,actual,sizeof(actual))==7);
    assert(memcmp(payload,actual,7)==0);
    assert(write(master,payload,7)==7);
    for (attempt=0;attempt<100;attempt++) {
        assert(simrt_serial_receive(token,actual,sizeof(actual),&received)==0);
        if (received) break;
        usleep(1000);
    }
    assert(received==7 && !memcmp(payload,actual,7));
    for (attempt=7;attempt<32;attempt++) assert(actual[attempt]==0);
    stale=token;
    simrt_serial_close(token);
    assert(simrt_serial_send(stale,payload,7,7,&sent)==-EBADF);
    assert(simrt_serial_open(device,115200,8,0,1,2,1,0,0,&token)<0 && token==0);
    assert(simrt_serial_open(device,115200,8,0,1,1,1,0,0,&token)==0);
    assert(token!=stale);
    simrt_serial_close(stale);
    assert(simrt_serial_send(token,payload,7,7,&sent)==0);
    simrt_serial_close(token);
    close(master);
    puts("serial PTY: validation, bidirectional binary transfer, empty receive, stale tokens, unsupported RS485 passed");
    return 0;
}
