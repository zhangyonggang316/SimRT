#include "serial_loopback_protocol.h"
#include <assert.h>
#include <stdio.h>

int main(void)
{
    uint8_t nonce[8]={0,1,2,3,252,253,254,255};
    uint8_t expected[SERIAL_FRAME_SIZE], actual[SERIAL_FRAME_SIZE];
    uint32_t sequence, byte;
    unsigned direction;
    assert(serial_crc32((const uint8_t *)"123456789",9)==UINT32_C(0xCBF43926));
    for (sequence=0;sequence<64;++sequence) {
        for (direction=0;direction<2;++direction) {
            serial_make_frame(expected,nonce,sequence,(uint8_t)direction);
            assert(serial_validate_frame(expected,expected)==NULL);
            assert(expected[24]==0 && expected[25]==10 && expected[26]==13);
            assert(expected[28]==128 && expected[29]==255);
            for (byte=0;byte<SERIAL_FRAME_SIZE;++byte) {
                memcpy(actual,expected,sizeof(actual));
                actual[byte]^=1;
                assert(serial_validate_frame(actual,expected)!=NULL);
            }
            serial_make_frame(actual,nonce,sequence+1,(uint8_t)direction);
            assert(!strcmp(serial_validate_frame(actual,expected),"sequence"));
            serial_make_frame(actual,nonce,sequence,(uint8_t)(1-direction));
            assert(!strcmp(serial_validate_frame(actual,expected),"direction/echo"));
            memcpy(actual,expected,sizeof(actual));
            actual[12]^=1;
            assert(!strcmp(serial_validate_frame(actual,expected),"nonce/stale frame"));
            memcpy(actual,expected,sizeof(actual));
            actual[40]^=1;
            serial_put_u32(actual+SERIAL_CRC_OFFSET,serial_crc32(actual,SERIAL_CRC_OFFSET));
            assert(!strcmp(serial_validate_frame(actual,expected),"payload"));
        }
    }
    puts("Serial protocol: reference CRC, 128 frames, every-byte corruption, nonce, sequence, direction, payload passed");
    return 0;
}
