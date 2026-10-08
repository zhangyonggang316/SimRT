"""Three-hour read-only target health sampling, including console/model resources."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import time


def processes():
    records = []
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            if path.stat().st_uid != os.getuid():
                continue
            name = (path / 'comm').read_text().strip()
            arguments = (path / 'cmdline').read_bytes().split(b'\0')
            executable = os.readlink(path / 'exe')
            console = any(arg == b'simrt_console.py' or arg.endswith(b'/simrt_console.py')
                          for arg in arguments)
            if not (executable.endswith('.elf') or console
                    or name.startswith('tmux')):
                continue
            fields = (path / 'stat').read_text().rsplit(')', 1)[1].split()
            status = dict(line.split(':', 1) for line in (path / 'status').read_text().splitlines())
            record = dict(pid=int(path.name), name=name, start_ticks=fields[19],
                          cpu_ticks=int(fields[11]) + int(fields[12]), state=fields[0],
                          rss=status.get('VmRSS', '').strip(), hwm=status.get('VmHWM', '').strip(),
                          locked=status.get('VmLck', '').strip(), threads=status.get('Threads', '').strip())
            if executable.endswith('.elf'):
                telemetry = Path(executable + '.simrt-status.json')
                if telemetry.is_file() and telemetry.stat().st_size <= 65536:
                    snapshot = json.loads(telemetry.read_text())
                    record['runtime'] = {key: snapshot.get(key) for key in (
                        'state', 'pid', 'sample_monotonic_ns', 'elapsed_ns', 'model_step_calls',
                        'model_step_completed_calls', 'deadline_misses', 'skipped_releases',
                        'model_step_execution_current_ns', 'model_step_execution_max_ns')}
            records.append(record)
        except (OSError, ValueError, IndexError, KeyError):
            continue
    return records


started = time.monotonic()
deadline = started + 10800
sample = 0
while True:
    current = time.monotonic()
    memory = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
    record = dict(event='simrt_health_sample', sample=sample,
                  timestamp_utc=datetime.now(timezone.utc).isoformat(),
                  elapsed_seconds=current - started, load=os.getloadavg(),
                  memory_available=memory['MemAvailable'].strip(),
                  swap_free=memory['SwapFree'].strip(), disk_free_bytes=shutil.disk_usage('/').free,
                  processes=processes())
    print(json.dumps(record), flush=True)
    sample += 1
    if current >= deadline:
        break
    time.sleep(min(10, deadline - current))
print(json.dumps(dict(event='simrt_health_complete', samples=sample,
                      elapsed_seconds=time.monotonic() - started)), flush=True)
