#include "xcp.h"

int simrt_xcp_is_disconnected(void)
{
    return xcpGetStatus() == XCP_DISCONNECTED;
}
