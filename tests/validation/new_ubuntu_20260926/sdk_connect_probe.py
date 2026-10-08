"""Bounded TSCAN discovery/connect diagnostic; never configures or sends CAN."""

import argparse
import ctypes as c
import json
import os
from pathlib import Path
import resource


def emit(stage, **values):
    print(json.dumps(dict(stage=stage, **values)), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--driver-dir", default="/home/zh/.local/lib/tscan", type=Path)
    parser.add_argument("--serial", default="37AFCA2612ADBF35")
    parser.add_argument("--scan-only", action="store_true")
    args = parser.parse_args()
    root = args.driver_dir.resolve(strict=True)
    os.chdir(root)
    emit("begin", driver_directory=str(root), can_frames_transmitted=0,
         realtime_priority_limit=resource.getrlimit(resource.RLIMIT_RTPRIO))
    c.CDLL(str(root / "libTSH.so"), mode=c.RTLD_GLOBAL)
    sdk = c.CDLL(str(root / "libTSCANApiOnLinux.so"), mode=c.RTLD_LOCAL)
    emit("loaded")
    sdk.initialize_lib_tscan.argtypes = [c.c_bool, c.c_bool, c.c_bool]
    sdk.initialize_lib_tscan.restype = None
    sdk.finalize_lib_tscan.argtypes = []
    sdk.finalize_lib_tscan.restype = None
    sdk.tscan_scan_devices.argtypes = [c.POINTER(c.c_uint32)]
    sdk.tscan_scan_devices.restype = c.c_uint32
    sdk.tscan_get_device_info.argtypes = [c.c_uint32, c.POINTER(c.c_char_p),
                                        c.POINTER(c.c_char_p), c.POINTER(c.c_char_p)]
    sdk.tscan_get_device_info.restype = c.c_uint32
    sdk.tscan_connect.argtypes = [c.c_char_p, c.POINTER(c.c_uint64)]
    sdk.tscan_connect.restype = c.c_uint32
    sdk.tscan_disconnect_by_handle.argtypes = [c.c_size_t]
    sdk.tscan_disconnect_by_handle.restype = c.c_uint32
    handle = c.c_uint64()
    initialized = False
    try:
        sdk.initialize_lib_tscan(True, False, False)
        initialized = True
        emit("initialized")
        count = c.c_uint32()
        status = int(sdk.tscan_scan_devices(c.byref(count)))
        emit("scan", status=status, count=count.value)
        matches = []
        for index in range(min(count.value, 16)):
            manufacturer, product, serial = c.c_char_p(), c.c_char_p(), c.c_char_p()
            status = int(sdk.tscan_get_device_info(index, c.byref(manufacturer),
                                                  c.byref(product), c.byref(serial)))
            values = [p.value.decode("utf-8", "replace") if p.value else ""
                      for p in (manufacturer, product, serial)]
            emit("device", index=index, status=status, manufacturer=values[0], product=values[1], serial=values[2])
            if status == 0 and values[2].upper() == args.serial.upper():
                matches.append(values[2])
        if len(matches) != 1:
            raise RuntimeError("Expected exactly one SDK device with the selected serial")
        if not args.scan_only:
            emit("connecting", serial=args.serial)
            status = int(sdk.tscan_connect(args.serial.encode("ascii"), c.byref(handle)))
            emit("connected", status=status, handle_nonzero=bool(handle.value))
            if status not in (0, 5) or not handle.value:
                raise RuntimeError("SDK connect did not return a valid device handle")
            threads = []
            for entry in Path("/proc/self/task").iterdir():
                tid = int(entry.name)
                threads.append(dict(tid=tid, policy=os.sched_getscheduler(tid),
                                    priority=os.sched_getparam(tid).sched_priority))
            emit("threads", tasks=threads)
    finally:
        if handle.value:
            emit("disconnecting")
            emit("disconnected", status=int(sdk.tscan_disconnect_by_handle(handle.value)))
        if initialized:
            emit("finalizing")
            sdk.finalize_lib_tscan()
            emit("finalized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
