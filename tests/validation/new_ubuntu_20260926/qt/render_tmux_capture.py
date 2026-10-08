"""Render captured terminal text, explicitly not a physical-monitor screenshot."""

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index", type=int)
    args = parser.parse_args()
    output = Path(__file__).resolve().parent / "tmux_soak"
    report = json.loads((output / "tmux_validation.json").read_text())
    sample = report["samples"][args.index]
    columns, rows = sample["size"]
    top_file = output / "{:04d}_dashboard.txt".format(args.index)
    shell_file = output / "{:04d}_shell.txt".format(args.index)
    top = top_file.read_text(encoding="utf-8").splitlines()
    shell = shell_file.read_text(encoding="utf-8").splitlines()
    font = ImageFont.truetype("C:/Windows/Fonts/consola.ttf", 18)
    cell_width, cell_height = int(font.getlength("M") + 0.999), 24
    canvas = Image.new("RGB", (columns * cell_width, rows * cell_height), "black")
    draw = ImageDraw.Draw(canvas)
    top_height = sample["panes"]["0"]["height"]
    for row, text in enumerate(top[:top_height]):
        label, separator, value = text.partition(": ")
        draw.text((0, row * cell_height), label + separator, fill="#eeeeee", font=font)
        if separator:
            draw.text((int(font.getlength(label + separator)), row * cell_height), value,
                      fill="#00dddd", font=font)
    draw.line((0, top_height * cell_height, canvas.width, top_height * cell_height), fill="#777777")
    for row, text in enumerate(shell[:sample["panes"]["1"]["height"]]):
        draw.text((0, (top_height + 1 + row) * cell_height), text, fill="#eeeeee", font=font)
    image_path = output / "{:04d}_captured_terminal.png".format(args.index)
    canvas.save(image_path)
    metadata = {"kind": "rendered_target_tmux_text_capture", "synthetic_metrics": False,
                "physical_screenshot": False, "production_tty1_capture": False,
                "dashboard_colors": "white labels and cyan values, matching the renderer",
                "separator": "neutral line added between the two text captures",
                "source_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                  for path in (top_file, shell_file)},
                "image": image_path.name, "terminal_size": sample["size"],
                "sample_index": args.index, "elapsed_seconds": sample["elapsed_seconds"]}
    image_path.with_suffix(".json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata))


if __name__ == "__main__":
    main()
