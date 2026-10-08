#include "simrt_ethercat.h"
#include "ethercat.h"
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

ec_slavet ec_slave[EC_MAXSLAVE];
ec_groupt ec_group[EC_MAXGROUP];
static int found_slaves=1, receive_wkc=3, open_result=1, op_result=1, closed;
static uint8_t *image;
int ec_init(const char *interface_name) { (void)interface_name; return open_result; }
int ec_config_init(uint8 use_table) { (void)use_table; return found_slaves; }
int ec_config_map(void *map)
{
    image=map; ec_slave[0].outputs=image; ec_slave[0].inputs=image+2;
    ec_slave[0].Obytes=2; ec_slave[0].Ibytes=2;
    ec_group[0].outputsWKC=1; ec_group[0].inputsWKC=1;
    ec_group[0].nsegments=1; ec_group[0].IOsegment[0]=4;
    return 4;
}
uint16 ec_statecheck(uint16 slave, uint16 state, int timeout)
{
    (void)slave; (void)timeout;
    return state==EC_STATE_OPERATIONAL && !op_result ? EC_STATE_SAFE_OP : state;
}
int ec_writestate(uint16 slave) { (void)slave; return 1; }
int ec_send_processdata(void) { return 1; }
int ec_receive_processdata(int timeout)
{
    (void)timeout;
    if(image) { image[2]=(uint8_t)(image[0]+1); image[3]=(uint8_t)(image[1]+1); }
    return receive_wkc;
}
void ec_close(void) { ++closed; image=NULL; }

int main(void)
{
    uint32_t token=99, other=99, stale;
    int32_t expected, actual;
    uint8_t tx[2]={11,27}, rx[2];
    assert(simrt_ethercat_open("eth1",2,2,1,500,&token,&expected)==0);
    assert(token!=0 && expected==3);
    assert(simrt_ethercat_open("eth1",2,2,1,500,&other,&expected)==-EBUSY && other==0);
    assert(simrt_ethercat_exchange(token,tx,2,rx,2,&actual)==0 && actual==3);
    assert(rx[0]==12 && rx[1]==28);
    assert(simrt_ethercat_exchange(token,tx,1,rx,2,&actual)==-EMSGSIZE);
    receive_wkc=1;
    assert(simrt_ethercat_exchange(token,tx,2,rx,2,&actual)==-EIO && actual==1);
    assert(rx[0]==0 && rx[1]==0);
    stale=token; simrt_ethercat_close(token);
    assert(simrt_ethercat_exchange(stale,tx,2,rx,2,&actual)==-EBADF);
    receive_wkc=3;
    assert(simrt_ethercat_open("eth1",1,2,1,500,&token,&expected)==-EMSGSIZE && token==0);
    found_slaves=0;
    assert(simrt_ethercat_open("eth1",2,2,1,500,&token,&expected)==-ENODEV);
    found_slaves=1; op_result=0;
    assert(simrt_ethercat_open("eth1",2,2,1,500,&token,&expected)==-ETIMEDOUT);
    op_result=1; open_result=0;
    assert(simrt_ethercat_open("eth1",2,2,1,500,&token,&expected)==-ENODEV);
    open_result=1;
    assert(simrt_ethercat_open("eth1",2,2,1,500,&token,&expected)==0 && token!=stale);
    simrt_ethercat_close(stale);
    assert(simrt_ethercat_exchange(token,tx,2,rx,2,&actual)==0);
    simrt_ethercat_close(token);
    assert(closed==6);
    puts("EtherCAT SOEM adapter: PDO transfer, WKC failure, ownership, size/slave/state failures passed");
    return 0;
}
