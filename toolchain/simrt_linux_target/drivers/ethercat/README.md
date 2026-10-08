# EtherCAT model library

Run `installSimRTARKLibrary` and select `SimRT / EtherCAT` in the Library Browser.
`setupSimRTEtherCATLibrary` and `simrt_ethercat_library` remain available for direct
library access and existing model links. The `EtherCAT PDO Exchange` System block
embeds the official SOEM v1.4.0 Linux master in the
generated executable. The pinned source tree and upstream license are included
under `vendor/soem`; no separate target installation is required.

Set Interface to a dedicated EtherCAT NIC, ExpectedSlaves to the exact number
of slaves, and OutputBytes/InputBytes to the complete default PDO image lengths
reported by the slave configuration. The block checks all three before entering
OP. Slave order and byte offsets are the SOEM default mapping order. The input
is a fixed `uint8` vector of OutputBytes; the output is a fixed `uint8` vector
of InputBytes. A direction with zero bytes uses a one-byte dummy Simulink port.
Pack and unpack integer/floating-point fields in the slave-specified byte order.

One block/master is allowed per process. Setup opens the raw EtherCAT socket,
discovers and maps slaves, transitions through SAFE_OP, sends a zero output
image and requests OP. Each sample hit sends one process image and receives one
image. The receive timeout is in microseconds and must be less than the sample
period. Status zero indicates a working counter at least ExpectedWKC. On a low
counter or receive failure, Inputs is zeroed and Status is negative; a consumer
must gate control decisions on Status. There is no automatic slave recovery.
Stopping the model requests INIT and closes the socket.

The mapper rejects PDO groups requiring more than SOEM's 16 outstanding frame
buffers, any segment exceeding one EtherCAT frame, or inconsistent segment
lengths. Split or reduce the slave mapping when Setup reports `-90`.

Common Status values: `-19` missing/mismatched slave or unavailable NIC,
`-90` incorrect PDO image size, `-16` another master already owns the runtime,
`-110` OP transition timeout, `-5` process-data/working-counter failure,
`-11` overlapping calls, `-1`/`-13` insufficient permissions. Interpreted desktop
simulation returns `-38` and zero data because no physical master is running.

The runtime currently supports default PDO mappings. Device-specific startup
SDOs, custom PDO remapping, ESI/ENI import, CiA402 control and distributed-clock
servo synchronization are not configured by this block. The slave application
must accept its factory/startup mapping and zero startup output image. Validate
slave-specific behavior before connecting powered actuators. Select a dedicated
NIC, keep the host management connection on another port, and arrange raw socket
and NIC configuration permissions (`CAP_NET_RAW`, `CAP_NET_ADMIN`, or root).
SOEM sets the dedicated interface's promiscuous flag during initialization.

Sources:
- https://github.com/OpenEtherCATsociety/SOEM/tree/v1.4.0
- https://openethercatsociety.github.io/doc/soem/index.html

## Validation

From this directory on Linux:

```sh
inc='-Isrc -Ivendor/soem/soem -Ivendor/soem/osal -Ivendor/soem/osal/linux -Ivendor/soem/oshw/linux'
cc -std=gnu99 -Wall -Wextra -Werror $inc src/simrt_ethercat.c tests/test_ethercat_runtime.c -lpthread -o /tmp/simrt_ethercat_test
/tmp/simrt_ethercat_test
cc -std=gnu99 -Wall -Wextra -Werror $inc src/simrt_ethercat.c tests/test_soem_link.c vendor/soem/soem/*.c vendor/soem/osal/linux/*.c vendor/soem/oshw/linux/*.c -lpthread -lrt -o /tmp/simrt_soem_link_test
/tmp/simrt_soem_link_test
```

The first test substitutes the SOEM API to exercise lifecycle, PDO bytes,
counter errors, slave/size/state failures and stale ownership. The second
links every real SOEM Linux source and validates rejection before touching any
physical interface. Neither test proves communication with physical slaves.
