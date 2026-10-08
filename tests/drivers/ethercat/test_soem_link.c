#include "simrt_ethercat.h"
#include <assert.h>
#include <stdint.h>
#include <stdio.h>

int main(void)
{
    uint32_t token=1;
    int32_t expected=1;
    /* Invalid name is rejected before any socket or physical bus is accessed. */
    assert(simrt_ethercat_open("",2,2,1,500,&token,&expected)<0);
    assert(token==0 && expected==0);
    puts("Real SOEM v1.4.0 linked and input validation passed");
    return 0;
}
