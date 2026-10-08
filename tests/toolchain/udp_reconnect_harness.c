/* Exercise the real rtIOStream driver with only the XCP protocol state stubbed.
 * Requests and responses use the same framing and split receive calls as XCP.
 */
#ifndef _WIN32
#define _POSIX_C_SOURCE 200809L
#endif
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#ifdef _WIN32
#include <windows.h>
#endif
#include "rtiostream.h"
#include "xcp.h"

static XcpStatus protocol_status = XCP_DISCONNECTED;

XcpStatus xcpGetStatus(void)
{
    return protocol_status;
}

static void idle(void)
{
#ifdef _WIN32
    Sleep(1);
#else
    const struct timespec delay = {0, 1000000L};
    nanosleep(&delay, NULL);
#endif
}

static int read_exact(int stream, unsigned char *dst, size_t size)
{
    size_t offset = 0;
    while (offset < size) {
        size_t received = 0;
        if (rtIOStreamRecv(stream, dst + offset, size - offset, &received) !=
            RTIOSTREAM_NO_ERROR) {
            return -1;
        }
        offset += received;
        if (received == 0) {
            idle();
        }
    }
    return 0;
}

int main(int argc, char **argv)
{
    void *options[] = {"-protocol", "UDP", "-client", "0", "-blocking",
                       "0", "-port", NULL, "-verbose", "0"};
    unsigned int counter = 0;
    int stream;
    if (argc != 2) {
        return 2;
    }
    options[7] = argv[1];
    stream = rtIOStreamOpen(10, options);
    if (stream == RTIOSTREAM_ERROR) {
        return 3;
    }
    puts("READY");
    fflush(stdout);
    for (;;) {
        unsigned char request[512];
        unsigned char response[6] = {1, 0, 0, 0, 0xff, 0};
        size_t payload_size;
        size_t response_size = 5;
        size_t sent = 0;
        if (read_exact(stream, request, 5) != 0) {
            return 4;
        }
        payload_size = request[0] | ((size_t)request[1] << 8);
        if (payload_size < 1 || payload_size > sizeof(request) - 4) {
            return 5;
        }
        if (read_exact(stream, request + 5, payload_size - 1) != 0) {
            return 6;
        }
        switch (request[4]) {
        case 0xff: /* CONNECT */
            protocol_status = XCP_CONNECTED;
            response[0] = 2;
            response[5] = 1;
            response_size = 6;
            break;
        case 0xfe: /* DISCONNECT */
            protocol_status = XCP_DISCONNECTED;
            break;
        case 0xf0: /* A command with a one-byte positive response. */
            break;
        default:
            return 7;
        }
        response[2] = (unsigned char)counter;
        response[3] = (unsigned char)(counter >> 8);
        ++counter;
        if (rtIOStreamSend(stream, response, response_size, &sent) !=
                RTIOSTREAM_NO_ERROR || sent != response_size) {
            return 8;
        }
    }
}
