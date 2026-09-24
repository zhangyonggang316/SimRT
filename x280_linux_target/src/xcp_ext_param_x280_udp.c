/* X280 XCP transport defaults: standard XCP on UDP/IP, port 17725. */

#include <string.h>

#include "rtwtypes.h"
#include "rtw_extmode.h"
#include "xcp_common.h"
#include "xcp_ext_param.h"

#ifndef EXTMODE_DISABLE_ARGS_PROCESSING

typedef enum {
    XCP_PARAM_PORT_ID,
    XCP_PARAM_PORT_VALUE_ID,
    XCP_PARAM_BLOCKING_ID,
    XCP_PARAM_BLOCKING_VALUE_ID,
    XCP_PARAM_PROTOCOL_ID,
    XCP_PARAM_PROTOCOL_VALUE_ID,
    XCP_PARAM_CLIENT_ID,
    XCP_PARAM_CLIENT_VALUE_ID,
    XCP_PARAM_VERBOSE_ID,
    XCP_PARAM_VERBOSE_VALUE_ID
} XcpTransportLayerParams;

static const void *xcpTransportLayerParams[] = {
    "-port", "17725",
    "-blocking", "0",
    "-protocol", "UDP",
    "-client", "0",
    "-verbose", "0"
};

#endif

void xcpExtModeParseArgs(int_T argc, const char_T *argv[])
{
#ifdef EXTMODE_DISABLE_ARGS_PROCESSING
    UNUSED_PARAMETER(argc);
    UNUSED_PARAMETER(argv);
#else
    if ((argv != NULL) && (argc > 0)) {
        int_T optionId = 1;

        while (optionId < argc) {
            const char_T *option = argv[optionId++];
            boolean_T isXcpOption = false;

            if ((option == NULL) || (optionId == argc)) {
                continue;
            }
            if (strcmp(option, xcpTransportLayerParams[XCP_PARAM_PORT_ID]) == 0) {
                xcpTransportLayerParams[XCP_PARAM_PORT_VALUE_ID] = argv[optionId];
                isXcpOption = true;
            } else if (strcmp(option, xcpTransportLayerParams[XCP_PARAM_BLOCKING_ID]) == 0) {
                xcpTransportLayerParams[XCP_PARAM_BLOCKING_VALUE_ID] = argv[optionId];
                isXcpOption = true;
            } else if (strcmp(option, xcpTransportLayerParams[XCP_PARAM_PROTOCOL_ID]) == 0) {
                /* Consume the option but keep UDP mandatory for this target. */
                isXcpOption = true;
            } else if (strcmp(option, xcpTransportLayerParams[XCP_PARAM_VERBOSE_ID]) == 0) {
                xcpTransportLayerParams[XCP_PARAM_VERBOSE_VALUE_ID] = argv[optionId];
                isXcpOption = true;
            }

            if (isXcpOption) {
                argv[optionId - 1] = NULL;
                argv[optionId] = NULL;
            }
            optionId++;
        }
    }
#endif
}

void xcpTransportGetInitParameters(int_T *parNumber, void **parList[])
{
#ifdef EXTMODE_DISABLE_ARGS_PROCESSING
    if ((parNumber != NULL) && (parList != NULL)) {
        *parNumber = 0;
        *parList = NULL;
    }
#else
    if ((parNumber != NULL) && (parList != NULL)) {
        *parNumber = XCP_ELEMENTS_NUMBER(xcpTransportLayerParams);
        *parList = (void **)&xcpTransportLayerParams;
    }
#endif
}

void xcpGetInitParameters(int_T *parNumber, void **parList[])
{
    if ((parNumber != NULL) && (parList != NULL)) {
        *parNumber = 0;
        *parList = NULL;
    }
}
