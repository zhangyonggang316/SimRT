"""Real driver regression: a new client source port after XCP DISCONNECT."""
from __future__ import annotations

import argparse
import json
import socket
import struct
import subprocess
import time
from pathlib import Path


def exchange(client: socket.socket, port: int, payload: bytes) -> bytes:
    client.sendto(struct.pack("<HH", len(payload), 0) + payload, ("127.0.0.1", port))
    response, peer = client.recvfrom(512)
    assert peer == ("127.0.0.1", port)
    length, _ = struct.unpack("<HH", response[:4])
    assert len(response) == length + 4 and response[4] == 0xFF, response.hex()
    return response[4:]


def run(executable: Path, cycles: int, expect_pinned_peer: bool) -> dict:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    process = subprocess.Popen(
        [str(executable.resolve()), str(port)], stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True,
    )
    clients = []
    result = {"executable": str(executable), "requested_cycles": cycles,
              "ports": [], "connect_attempts": []}
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "READY"
        for index in range(cycles):
            client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            clients.append(client)  # Keep ports reserved so none can be reused.
            client.bind(("127.0.0.1", 0))
            client.settimeout(0.75)
            result["ports"].append(client.getsockname()[1])
            # XCP CONNECT, like the application's UDP client, retries lost packets.
            for attempt in range(1, 4):
                try:
                    assert exchange(client, port, b"\xff\x00") == b"\xff\x01"
                    result["connect_attempts"].append(attempt)
                    break
                except socket.timeout:
                    if attempt != 3:
                        continue
                    if expect_pinned_peer and index == 1:
                        result.update(baseline_bug_reproduced=True, successful_cycles=1)
                        return result
                    raise AssertionError(f"Cycle {index}: CONNECT failed after 3 attempts")
            # A generic positive response while CONNECTED must not release peer.
            assert exchange(client, port, b"\xf0") == b"\xff"
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as intruder:
                intruder.bind(("127.0.0.1", 0))
                intruder.settimeout(0.03)
                try:
                    exchange(intruder, port, b"\xff\x00")
                except socket.timeout:
                    pass
                else:
                    raise AssertionError("Another port took over an active XCP session")
            # The original peer still works after a competing packet.
            assert exchange(client, port, b"\xf0") == b"\xff"
            assert exchange(client, port, b"\xfe") == b"\xff"
        assert not expect_pinned_peer, "Vendor baseline unexpectedly supports reconnect"
        assert len(set(result["ports"])) == cycles
        result.update(successful_cycles=cycles, active_peer_exclusivity=True)
        return result
    finally:
        for client in clients:
            client.close()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    parser.add_argument("--cycles", type=int, default=50)
    parser.add_argument("--expect-pinned-peer", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    started = time.monotonic()
    result = run(args.executable, args.cycles, args.expect_pinned_peer)
    result["elapsed_seconds"] = time.monotonic() - started
    result["passed"] = True
    encoded = json.dumps(result, indent=2)
    print(encoded)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
