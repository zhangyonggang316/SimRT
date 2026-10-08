# Live Runtime Status

The runtime writes `<absolute ELF path>.simrt-status.json`, for example
`/home/zh/MATLAB_ws/project_run/simrt_rt_single.elf.simrt-status.json`.
The SCHED_OTHER writer atomically replaces this file once per second. The FIFO
model thread attempts a fixed-size snapshot at most 10 times per second using
`atomic_flag`; contention drops an update instead of waiting. It never performs
file I/O. The writer's condition variable and timeout both use CLOCK_MONOTONIC,
so wall-clock synchronization cannot delay status refreshes. On normal completion
or a handled termination signal, the main thread
joins the model and writer, then publishes the final `STOPPED` snapshot.

All timing fields ending in `_ns` are nanoseconds. Step statistics use the
existing `simrt_rt_step_begin/end` measurements, including generated DAQ upload.
Consumers must verify PID/executable identity and sample freshness before
displaying RUNNING; a crashed process cannot publish STOPPED.

| Field | Type / meaning |
| --- | --- |
| schema_version | Integer, currently 1 |
| event | `simrt_status` |
| model | Generated model identifier |
| pid | Linux process ID |
| state | `RUNNING` or `STOPPED` |
| updated_unix_ns | UTC Unix timestamp when the writer serialized the snapshot |
| sample_monotonic_ns | CLOCK_MONOTONIC time when the statistics were sampled |
| elapsed_ns | Time since first scheduled model release; final value excludes writer shutdown |
| period_ns | Actual configured model period |
| cpu | Model thread's pinned logical CPU |
| priority | Model SCHED_FIFO priority |
| realtime_kernel | Boolean, detected PREEMPT_RT state |
| memory_locked | Boolean, true after successful mlockall |
| stop_time_seconds | Generated model's finite stop time, otherwise null |
| model_step_calls | Actual model step entry count |
| model_step_completed_calls | Actual model step completion count |
| model_step_interval_min_ns | Minimum step entry-to-entry interval |
| model_step_interval_mean_ns | Mean step entry-to-entry interval |
| model_step_interval_max_ns | Maximum step entry-to-entry interval |
| model_step_execution_current_ns | Most recently completed step duration |
| model_step_execution_max_ns | Maximum completed step duration |
| deadline_misses | Existing base-rate loop deadline-miss counter |
| skipped_releases | Existing absolute scheduler skipped-release counter |

Initialization or writing failures produce one stderr warning and do not stop
the model. The existing `simrt_rt_summary` output and its statistics are retained.
The status file is runtime output and is not part of the three-file deployment ZIP.

`rt_runtime_harness.elf` was cross-compiled on Windows with GCC 7.5.0 and
`-std=c11 -O2 -Wall -Wextra -Werror -pthread -fno-pie -no-pie`. The Linux-only
`verify_live_status.py` exercises live updates, atomic JSON reads, final-summary
consistency, deliberate overruns, and SIGTERM without compiling on the target.
Use its `--allow-non-rt-diagnostic` switch only for explicitly labeled functional
diagnostics; that report sets `strict_realtime_validation` to false.
