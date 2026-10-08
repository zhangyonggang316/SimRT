# Serial model library

Run `installSimRTARKLibrary` and select `SimRT / Serial` in the Library Browser.
`setupSimRTSerialLibrary` and `simrt_serial_library` remain available for direct
library access and existing model links.
Connect the `Serial Setup` Connection output (`uint32`) to `Serial Sent` and
`Serial Receive`. One Setup owns each Linux device; duplicate opens return
`-EBUSY`. Setup releases the device when the model terminates. Tokens prevent an
old block instance from accessing a subsequently reopened device.

`Serial Sent` accepts a fixed-size `uint8` vector, `uint32` Length, and logical
Enable. It returns `uint32` Sent and `int32` Status. Writes are nonblocking;
`-EAGAIN` with a positive Sent means only that prefix was accepted. Resubmit the
remaining bytes on later sample hits. The block does not copy, retry, or frame
application messages. `Serial Receive` returns a zero-padded fixed-size vector,
Length and Status; Length zero with Status zero means no data is available.

Status zero is success; negative values are Linux errno values. Useful values
are `-11` (try again), `-9` (invalid/closed connection), `-16` (already owned),
`-22` (invalid parameter), `-25`/`-95` (unsupported RS485 ioctl), and `-13`
(device permission denied). Interpreted desktop simulation returns `-38`
(transport unavailable); it does not claim to access target hardware.

The Linux driver uses raw `termios`, 5-8 data bits, no/odd/even parity, one/two
stop bits and standard 1200-921600 baud rates. Hardware determines which of
these settings it accepts. Software and RTS/CTS flow control are disabled.
The serial process needs access to its device, usually through the `dialout`
group. Confirm the `/dev/ttyS*` to connector mapping on the specific machine.

## ARK-2120 capabilities

Advantech's official ARK-2120 user manual, printed pages 3 and 5, distinguishes:

| Variant | RS232 only | RS232/RS422/RS485 |
| --- | --- | --- |
| ARK-2120L | COM1, COM3, COM4 | COM2 |
| ARK-2120F | COM1, COM2 | COM3, COM4, COM5, COM6 |

ARK-2120L COM2 requires the RS422/485 internal cable (part 1700001967) and
jumper selection. ARK-2120F COM3-COM6 mode is selected under BIOS Advanced /
Super IO Configuration. The manual specifically documents automatic RS485
direction for L COM2 and F COM3-COM5; it does not make the same guarantee for
F COM6. Select the electrical mode in hardware before running a model.

For those automatic-direction ports use Mode `RS485`, RS485Direction
`Hardware auto`. This setting deliberately leaves hardware direction control
to the configured UART/board. For a Linux driver supporting `TIOCSRS485`, use
`Linux RTS`; unsupported direction ioctls fail Setup instead of silently
falling back. Choosing RS232 attempts to disable any Linux RS485 mode left by
an earlier application. Software selection cannot change a board jumper or
make an RS232-only connector support RS485.

Sources:
- https://advdownload.advantech.com/productfile/Downloadfile1/1-L5KJLX/ARK-2120_user_manual_ed.1_D5.pdf
- https://www.advantech.com/en-us/support/details/manual?id=1-14UUSDR
- https://docs.kernel.org/driver-api/serial/serial-rs485.html

## Validation

The [COM5/6 RS485 bench model](../../../../docs/RS485_COM56_TEST.md) uses two
Setup/Sent/Receive chains, alternating 12-byte CRC16 frames and exported XCP
counters. Open `models/simrt_serial_com56/simrt_serial_com56.slx` in R2024b.
`Serial_Enable` defaults to zero; setting it to one starts the traffic and
setting it to zero stops traffic and resets counters. Device candidates are
`/dev/ttyS6` and `/dev/ttyS7`; physical connector mapping and communication have
not passed validation. See the guide for the actual test results.

On Linux, from this directory:

```sh
cc -std=gnu99 -Wall -Wextra -Werror -Isrc src/simrt_serial.c tests/test_serial_runtime.c -lpthread -lutil -o /tmp/simrt_serial_test
/tmp/simrt_serial_test
```

The test uses a pseudoterminal and requires no serial hardware. It covers raw
binary transfer in both directions, an empty receive, bounds checks, exclusive
ownership, stale tokens and a rejected RS485 ioctl. Physical RS232/RS485 wiring,
UART mode and throughput still require an on-device loopback test.
