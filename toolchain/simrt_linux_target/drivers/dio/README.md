# Linux Digital I/O

ARK onboard GPIO/DIO adaptation and hardware testing were discontinued by user
decision on 2026-10-07. Existing blocks, examples and notes are retained for
reference only; onboard DIO is not a supported project feature.

`DIO Setup`, `DIO Read`, and `DIO Write` use Linux GPIO character-device v2
(Linux 5.10 or later), with explicit chip paths and line offsets. They are also
linked from `SimRT / Digital IO` in the Library Browser. See the [ARK guide](../../../../docs/ARK_IO.md)
for installation, parameters, status codes and the actual target driver status.

The bench example is `models/simrt_dio_loopback/simrt_dio_loopback.slx`.
It defaults to holding manual DIO0..3 output values for multimeter measurements;
loopback checking is disabled. Optional wired loopback uses DIO4..7 as inputs.
See the [test guide](../../../../docs/DIO_TEST.md) for measurement points and configuration.
Its default device is deliberately unconfigured until the ARK driver and line
mapping are available; the model is not evidence of working hardware.

The model backend does not provide an iManager kernel driver. The inspected
ARK currently has no GPIO character devices; its external DIO cannot yet be
accessed with these blocks. A chipset's unrelated GPIO must not be substituted.

The model owns the requested lines from Setup until termination. Initial
output levels are set atomically with the output request; close releases the
request without promising a final electrical level. Read/write reject stale
tokens, mismatched lengths and writes to input-only requests. A failed Read
returns zeroed values with a negative status. The caller must check Status.
Thread contention returns `-EAGAIN`; the kernel driver itself can still wait.

`src/simrt_gpio_v2.h` contains an ABI compatibility subset for the project's
older cross-toolchain headers. New headers use the installed Linux definitions.
The public API and layout are documented in the
[Linux GPIO v2 UAPI](https://docs.kernel.org/userspace-api/gpio/chardev.html).

`tests/run_offline_tests.ps1` exercises a mocked syscall backend and cross-links
the production Linux implementation. `tests/testDIO.m` covers MATLAB validation,
desktop unavailable status, port types/shapes and generated C calls. These
tests do not drive hardware pins. `buildSimRTDIOLibrary` regenerates the SLX.
