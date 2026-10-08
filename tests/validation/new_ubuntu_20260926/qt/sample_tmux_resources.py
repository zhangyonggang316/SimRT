"""Read only the dashboard PID recorded by the isolated soak report."""

import argparse
import json
from pathlib import Path
import re
import shlex
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from target_session import connect, execute


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("label")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9_-]+", args.label):
        parser.error("label must contain lowercase letters, digits, underscores or hyphens")
    output = Path(__file__).resolve().parent / "tmux_soak"
    report = json.loads((output / "tmux_validation.json").read_text())
    latest = report["samples"][-1]
    pid = int(latest["panes"]["0"]["pid"])
    script = """import datetime,json,os,pathlib
p=pathlib.Path('/proc')/str(PID)
text=(p/'status').read_text()
status=dict(line.split(':',1) for line in text.splitlines() if ':' in line)
fields=(p/'stat').read_text().rsplit(')',1)[1].split()
print(json.dumps({'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'pid':PID,'exe':os.readlink(p/'exe'),'clock_ticks':os.sysconf('SC_CLK_TCK'),'utime_ticks':int(fields[11]),'stime_ticks':int(fields[12]),'status':{key:status.get(key,'').strip() for key in ['Name','State','VmRSS','VmHWM','Threads','voluntary_ctxt_switches','nonvoluntary_ctxt_switches']}}))""".replace("PID", str(pid))
    client = connect(sys.stdin.readline().rstrip("\r\n"))
    try:
        result = execute(client, "python3 -c " + shlex.quote(script), timeout=20)
        if result["exit_code"]:
            raise RuntimeError("Process resource read failed")
        data = json.loads(result["stdout"])
        data["latest_validation_elapsed_seconds"] = latest["elapsed_seconds"]
        (output / ("resources_" + args.label + ".json")).write_text(json.dumps(data, indent=2), encoding="utf-8")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
