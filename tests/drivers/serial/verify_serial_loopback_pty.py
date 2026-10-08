"""Exercise the physical harness using Linux PTYs only, without real serial ports."""
import argparse
import errno
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time


def exercise(executable, mode='rs232', relay=True, corrupt=False, interrupt=False):
    import pty
    import termios

    first = pty.openpty()
    second = pty.openpty()
    masters = [first[0], second[0]]
    slaves = [first[1], second[1]]
    original = [termios.tcgetattr(fd) for fd in slaves]
    stop = threading.Event()
    failure = []
    process = None

    def bridge():
        pending = [bytearray(), bytearray()]
        changed = False
        try:
            while not stop.is_set():
                for source, fd in enumerate(masters):
                    try:
                        data = os.read(fd, 4096)
                    except BlockingIOError:
                        data = b''
                    if data:
                        if corrupt and not changed:
                            data = bytes([data[0] ^ 1]) + data[1:]
                            changed = True
                        pending[1 - source].extend(data)
                for destination, data in enumerate(pending):
                    if data:
                        try:
                            count = os.write(masters[destination], data)
                        except BlockingIOError:
                            continue
                        del data[:count]
                stop.wait(0.001)
        except BaseException as error:
            failure.append(error)

    thread = threading.Thread(target=bridge, daemon=True)
    try:
        for fd in masters:
            os.set_blocking(fd, False)
        if relay:
            thread.start()
        timeout = '2000' if relay or interrupt else '150'
        process = subprocess.Popen([str(executable), *(os.ttyname(fd) for fd in slaves),
                                    mode, '115200', '4', timeout],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if interrupt:
            time.sleep(0.1)
            process.send_signal(signal.SIGTERM)
        stdout, stderr = process.communicate(timeout=5)
        stop.set()
        if relay:
            thread.join(timeout=1)
        if failure:
            raise failure[0]
        result = json.loads(stdout)
        assert result['restore_ok'], (result, stderr)
        assert [termios.tcgetattr(fd) for fd in slaves] == original, 'Original termios not restored'
        if interrupt:
            assert result['signal'] == signal.SIGTERM and result['status'] == -errno.EINTR, result
        elif not relay:
            assert result['status'] == -errno.ETIMEDOUT and result['elapsed_ms'] < 1000, result
        elif corrupt:
            assert result['status'] == -errno.EBADMSG, (result, stderr)
        elif mode.startswith('rs485-rts'):
            assert not result['passed'] and result['status'] < 0, result
        else:
            assert process.returncode == 0 and result['passed'], (result, stderr)
            assert result['frames_verified'] == 8 and result['rounds_completed'] == 4, result
            assert result['tx_bytes'] == result['rx_bytes'] == 8 * 256, result
        return dict(mode=mode, relay=relay, corrupt=corrupt, interrupt=interrupt, result=result)
    finally:
        stop.set()
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        if relay and thread.is_alive():
            thread.join(timeout=1)
        for fd in masters + slaves:
            os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable', type=Path)
    args = parser.parse_args()
    if os.name != 'posix':
        parser.error('PTY integration tests require Linux; no physical port is opened')
    executable = args.executable.resolve(strict=True)
    results = [exercise(executable), exercise(executable, mode='rs485-auto'),
               exercise(executable, corrupt=True), exercise(executable, relay=False),
               exercise(executable, relay=False, interrupt=True),
               exercise(executable, mode='rs485-rts-high')]
    print(json.dumps(dict(passed=True, physical_test=False, tests=results), indent=2))


if __name__ == '__main__':
    main()
