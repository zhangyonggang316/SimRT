#ifndef SERIAL_LOOPBACK_PROTOCOL_H
#define SERIAL_LOOPBACK_PROTOCOL_H
#include <stdint.h>
#include <string.h>

#define SERIAL_FRAME_SIZE 256u
#define SERIAL_PAYLOAD_OFFSET 24u
#define SERIAL_CRC_OFFSET 252u

static uint32_t serial_crc32(const uint8_t *data, uint32_t length)
{
    uint32_t crc=UINT32_MAX, i, j;
    for (i=0;i<length;++i) {
        crc^=data[i];
        for (j=0;j<8;++j) crc=(crc>>1)^((crc&1) ? UINT32_C(0xEDB88320) : 0);
    }
    return ~crc;
}

static void serial_put_u32(uint8_t *data, uint32_t value)
{
    data[0]=(uint8_t)(value>>24); data[1]=(uint8_t)(value>>16);
    data[2]=(uint8_t)(value>>8); data[3]=(uint8_t)value;
}

static void serial_make_frame(uint8_t *frame, const uint8_t nonce[8], uint32_t sequence, uint8_t direction)
{
    uint32_t i, state=sequence^UINT32_C(0xA53971C3)^direction;
    memcpy(frame,"SIMRTSER",8);
    frame[8]=1; frame[9]=direction;
    frame[10]=0; frame[11]=SERIAL_CRC_OFFSET-SERIAL_PAYLOAD_OFFSET;
    memcpy(frame+12,nonce,8);
    serial_put_u32(frame+20,sequence);
    for (i=0;i<8;++i) state=(state^nonce[i])*UINT32_C(16777619);
    for (i=SERIAL_PAYLOAD_OFFSET;i<SERIAL_CRC_OFFSET;++i) {
        state=state*UINT32_C(1664525)+UINT32_C(1013904223);
        frame[i]=(uint8_t)(state>>24);
    }
    /* Always exercise NUL, line endings, high bits and terminal-control bytes. */
    frame[24]=0; frame[25]=10; frame[26]=13; frame[27]=127;
    frame[28]=128; frame[29]=255; frame[30]=17; frame[31]=19;
    serial_put_u32(frame+SERIAL_CRC_OFFSET,serial_crc32(frame,SERIAL_CRC_OFFSET));
}

static const char *serial_validate_frame(const uint8_t *actual, const uint8_t *expected)
{
    uint8_t crc[4];
    if (memcmp(actual,expected,9) || memcmp(actual+10,expected+10,2)) return "header";
    if (actual[9]!=expected[9]) return "direction/echo";
    if (memcmp(actual+12,expected+12,8)) return "nonce/stale frame";
    if (memcmp(actual+20,expected+20,4)) return "sequence";
    serial_put_u32(crc,serial_crc32(actual,SERIAL_CRC_OFFSET));
    if (memcmp(actual+SERIAL_CRC_OFFSET,crc,4)) return "CRC";
    if (memcmp(actual+SERIAL_PAYLOAD_OFFSET,expected+SERIAL_PAYLOAD_OFFSET,
               SERIAL_CRC_OFFSET-SERIAL_PAYLOAD_OFFSET)) return "payload";
    return NULL;
}
#endif
