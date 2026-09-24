# TC1013 SDK source review

Reviewed the user-provided `C:/DataSave/06同星二次开发库/libTSCAN_SDK_CPP_Linux_cn.pdf`
(Linux C++ V1.2) and the adjacent `TSCAN.API.Demo_C++` source and ZIP.
The text extraction is `sdk_manual.txt`; extraction used the standalone PDFBox
Java tool bundled with MATLAB, without launching MATLAB.

## Required target libraries

The Linux manual, pages 7-9 (`sdk_manual.txt:170`), names
`libTSCANApiOnLinux.so`, with dependencies `libTSH.so` and `blf.so`.
It also discusses `libusb`, dynamic-library search paths, and USB permissions.
Its occasional `libTSCANOnLinux.so` spelling omits `Api`; the explicitly named
link library is `libTSCANApiOnLinux.so`.

Neither the extracted demo directory nor its ZIP contains Linux `.so` files.
The supplied executable libraries are Windows x86/x64 `libTSCAN.dll` and
`libTSH.dll`, with additional x86 `binlog.dll` and `libLog.dll`.
The demo header includes `windows.h` and `__stdcall`; it cannot be included
unchanged in Linux generated code. The vendor Linux binary ABI cannot be
confirmed against actual Linux headers/binaries with this source delivery.

## Classic CAN contract

The manual pages 10-11 (`sdk_manual.txt:211`) and `TSCANDef.h:113` define:

```c
/* The supplied Windows header uses #pragma pack(1). */
struct TLibCAN {
    uint8_t  FIdxChn;       /* offset 0, channel starts at 0 */
    uint8_t  FProperties;   /* offset 1 */
    uint8_t  FDLC;          /* offset 2, 0..8 */
    uint8_t  FReserved;     /* offset 3 */
    int32_t  FIdentifier;   /* offset 4 */
    uint64_t FTimeUS;       /* offset 8, microseconds */
    uint8_t  FData[8];      /* offset 16 */
};                         /* 24 bytes */
```

Property masks: `0x01` TX direction, `0x02` remote frame, `0x04` extended
identifier. The supplied header defines `0x80` as error-frame flag; the PDF
lists bit 7 as reserved and separately identifies `FIdentifier == -1` as
an error frame. Rejecting error frames should check both when receiving.
Standard IDs are 11 bits, extended IDs 29 bits. All fields must be initialized.

## Functions and sequencing

The manual pages 24-28 (`sdk_manual.txt:683`) documents:

```c
void initialize_lib_tscan(bool enable_fifo, bool enable_error_frame,
                          bool turbo_or_hw_time);
void finalize_lib_tscan(void);
uint32_t tscan_scan_devices(uint32_t *count);
uint32_t tscan_connect(const char *serial, size_t *handle);
uint32_t tscan_disconnect_by_handle(size_t handle);
uint32_t tscan_config_can_by_baudrate(size_t handle, int channel,
                                    double rate_kbps, uint32_t termination);
uint32_t tscan_transmit_can_async(size_t handle, const TLibCAN *frame);
uint32_t tscan_transmit_can_sync(size_t handle, const TLibCAN *frame,
                                uint32_t timeout_ms);
uint32_t tsfifo_receive_can_msgs(size_t handle, const TLibCAN *buffer,
                                int32_t *capacity_and_count,
                                int channel, int rx_tx);
```

- Initialize once with `(true, false, false)` before other SDK calls; finalize
  after the last device is disconnected. The PDF repeats init/finalize with
  `u32` return types on page 40, contradicting page 24 and the supplied header.
  Use the corroborated `void` signature and do not inspect a return value.
- The supplied header calls init's third argument `AUseHWTime`; the Linux PDF
  calls it `AEnableTurbo` in the first definition. Both recommend `false`.
- `tscan_connect(NULL, &handle)` selects a default device; a nonempty serial
  selects a specific one. The PDF also demonstrates an empty string as default.
  Connect returns `0` on success and `5` when already connected. The demo treats
  both as usable and uses the returned handle.
- The SDK does not connect directly by numerical index. Page 38 defines
  `tscan_get_device_info(int32_t index, char **manufacturer, char **product,
  char **serial)`; obtain a serial before connecting by a selected index.
- Bitrate units are **kbit/s**, e.g. `500.0`; termination is `0`/`1`.
  `CHN1 == 0`, `CHN2 == 1`. Configure each channel before transmitting.
- Receive's count argument is IN/OUT: reset it to buffer capacity before each
  call; the returned count is actual frames written. RX/TX selector `0` excludes
  local TX echoes, `1` includes TX and RX. Empty FIFO is successful with count 0.
  The documented `const` buffer is nevertheless an output buffer.
- The Windows typedef uses `uint8_t` for receive's channel and RX/TX selector,
  while the Linux PDF writes enum types. Valid small nonnegative values use the
  same integer argument registers in x86_64, but actual Linux headers remain
  the authority when available.
- Other operations return `0` on success and nonzero on failure. Async transmit
  avoids the explicit multi-millisecond wait of sync transmit, but the supplied
  SDK documentation does not provide a worst-case execution-time guarantee.
- `tscan_get_can_channel_count(size_t handle, int32_t *count)` is documented on
  page 38 for validating available physical channels after connection.

For a 1 ms model, USB/SDK I/O should run outside the model's timing thread with
bounded queues and explicit overflow/error reporting. Actual hardware and Linux
library validation remain necessary; Windows DLLs and stub tests cannot prove
Linux device communication.
