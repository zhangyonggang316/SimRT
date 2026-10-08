/* R2024b rtIOStream keeps a UDP server connected to its first peer even after
 * XCP DISCONNECT. Include the unmodified driver so its framing, buffering and
 * TCP behavior remain intact, then release the peer after the final response.
 * The private ConnectionData contract is covered by the transport regression.
 */
#define rtIOStreamSend simrt_vendor_rtIOStreamSend
#include "rtiostream_tcpip.c"
#undef rtIOStreamSend

/* rtIOStream uses tmwtypes.h while XCP uses generated rtwtypes.h. Keep those
 * incompatible complex type declarations in separate translation units. */
extern int simrt_xcp_is_disconnected(void);

int rtIOStreamSend(int streamID, const void *src, size_t size, size_t *sizeSent)
{
    const unsigned char *frame = (const unsigned char *)src;
    int result;
    ConnectionData *connection = getConnectionData(streamID);
    SOCKET next_listener;

    /* XCP-on-Ethernet: four header bytes followed by the one-byte positive
     * DISCONNECT response. Send it before dropping the kernel's peer filter.
     * Other one-byte responses must retain the active connection.
     */
    if (size != 5 ||
        frame[0] != 1 || frame[1] != 0 || frame[4] != 0xff ||
        !simrt_xcp_is_disconnected() ||
        connection == NULL || !connection->isServer ||
        connection->protocol != UDP_PROTOCOL ||
        connection->sock == INVALID_SOCKET) {
        return simrt_vendor_rtIOStreamSend(streamID, src, size, sizeSent);
    }

    /* Bind before replying so an immediate new peer cannot hit an unbound
     * port. Both sockets use the vendor's SO_REUSEADDR setting. */
    next_listener = serverOpenSocket(
        connection->serverData->port, connection->serverData->serverInfoFile,
        connection->protocol, connection->udpSendBufSize,
        connection->udpRecvBufSize);
    if (next_listener == INVALID_SOCKET) {
        *sizeSent = 0;
        return RTIOSTREAM_ERROR;
    }
    result = simrt_vendor_rtIOStreamSend(streamID, src, size, sizeSent);
    if (result != RTIOSTREAM_NO_ERROR || *sizeSent != size) {
        close(next_listener);
        return result;
    }
    close(connection->sock);
    connection->sock = INVALID_SOCKET;
    connection->serverData->listenSock = next_listener;
    resetUDPPacketBuffer(connection->udpData->recvBuffer);
    if (connection->udpData->sendBuffer != NULL) {
        resetUDPPacketBuffer(connection->udpData->sendBuffer);
    }
    connection->udpData->sendSeqNum = 0;
    connection->udpData->resetExpectedRecvSeqNum = 1;
    return result;
}
