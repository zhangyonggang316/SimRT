"""Local layout illustration only; this is not a target console capture."""

import json
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "simrt_linux_target/console"))
from simrt_console import render_lines


def main():
    output = Path(__file__).parent
    snapshot = {
        "hostname": "fixture-simrt", "kernel": "6.x-fixture", "realtime": "YES",
        "time": "12:00:00", "network": "wlan0 192.0.2.10 / 255.255.255.0",
        "cpu_percent": 12.3, "memory": {"percent": 24.5}, "disk": {"percent": 8.9},
        "events": [], "models": [{"name": "simrt_rt_single", "pid": 1234,
            "elapsed": 120, "telemetry_state": "live (0.2s old)",
            "telemetry": {"elapsed_ns": 120000000000, "stop_time_seconds": None,
                "period_ns": 1000000, "model_step_calls": 120001,
                "model_step_completed_calls": 120001, "deadline_misses": 2,
                "skipped_releases": 1, "model_step_execution_current_ns": 9600,
                "model_step_execution_max_ns": 54800,
                "model_step_interval_min_ns": 930000,
                "model_step_interval_mean_ns": 1000000.0,
                "model_step_interval_max_ns": 1140000},
            "logs": ["12:00:00 layout fixture; synthetic values, no target connection"]}],
    }
    font = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", 18)
    cell_width = int(font.getlength("M") + 0.999)
    cell_height = 24
    evidence = {"kind": "synthetic_console_layout", "remote_hardware": False, "images": []}
    for columns, rows in [(80, 25), (120, 40)]:
        lines = render_lines(snapshot, columns - 1, rows - 7)
        canvas = Image.new("RGB", (columns * cell_width, rows * cell_height), "black")
        draw = ImageDraw.Draw(canvas)
        for y, line in enumerate(lines):
            label, separator, value = line.partition(": ")
            draw.text((0, y * cell_height), label + separator, fill="#eeeeee", font=font)
            if separator:
                draw.text((int(font.getlength(label + separator)), y * cell_height), value,
                          fill="#00dddd", font=font)
        divider_y = (rows - 7) * cell_height
        draw.line((0, divider_y, canvas.width, divider_y), fill="#00aaaa")
        draw.text((0, (rows - 6) * cell_height), "zh@fixture-simrt:~$", fill="#eeeeee", font=font)
        path = output / "console_fixture_{}x{}.png".format(columns, rows)
        canvas.save(path)
        evidence["images"].append({"path": path.name, "columns": columns, "rows": rows,
                                   "pixels": list(canvas.size), "dashboard_rows": rows - 7})
    (output / "console_fixture_report.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence))


if __name__ == "__main__":
    main()
