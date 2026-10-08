"""Capture the actual Linux framebuffer over pinned SSH, without a GUI session."""

import argparse
import base64
import getpass
import json
from pathlib import Path
import shlex
import zlib

import numpy as np
from PIL import Image

from target_session import connect

SOURCE = r'''
import array, base64, fcntl, json, os, zlib
from pathlib import Path
fd = os.open('/dev/fb0', os.O_RDONLY)
try:
    info = array.array('I', [0] * 40)
    fcntl.ioctl(fd, 0x4600, info, True)
    width, height, _, _, xoffset, yoffset, bpp = info[:7]
    stride = int(Path('/sys/class/graphics/fb0/stride').read_text())
    if bpp not in (16, 24, 32) or width > 4096 or height > 4096:
        raise RuntimeError('Unsupported framebuffer format')
    size = stride * (height + yoffset)
    data = bytearray()
    while len(data) < size:
        block = os.read(fd, min(1048576, size - len(data)))
        if not block:
            raise RuntimeError('Truncated framebuffer')
        data.extend(block)
    print(json.dumps(dict(width=width, height=height, xoffset=xoffset, yoffset=yoffset,
                          bpp=bpp, stride=stride, red=list(info[8:11]),
                          green=list(info[11:14]), blue=list(info[14:17]),
                          data=base64.b64encode(zlib.compress(data)).decode())))
finally:
    os.close(fd)
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    password = getpass.getpass('SSH/sudo password: ')
    client = connect(password)
    try:
        stdin, stdout, stderr = client.exec_command("sudo -S -p '' python3 -c " + shlex.quote(SOURCE), timeout=30)
        stdin.write(password + '\n')
        stdin.flush()
        stdin.channel.shutdown_write()
        raw = stdout.read()
        error = stderr.read().decode()
        if stdout.channel.recv_exit_status() != 0:
            raise RuntimeError(error)
        data = json.loads(raw)
        packed = zlib.decompress(base64.b64decode(data.pop('data')))
        rows = np.frombuffer(packed, dtype=np.uint8).reshape(-1, data['stride'])
        size = data['bpp'] // 8
        rows = rows[data['yoffset']:data['yoffset'] + data['height'],
                    data['xoffset'] * size:(data['xoffset'] + data['width']) * size]
        pixels = rows.reshape(data['height'], data['width'], size).astype(np.uint32)
        values = np.zeros((data['height'], data['width']), dtype=np.uint32)
        for byte in range(size):
            values |= pixels[:, :, byte] << (byte * 8)
        channels = []
        for color in ('red', 'green', 'blue'):
            offset, length, reversed_bits = data[color]
            if reversed_bits or not 0 < length <= 8:
                raise RuntimeError('Unsupported framebuffer channel')
            mask = (1 << length) - 1
            channels.append((((values >> offset) & mask) * 255 // mask).astype(np.uint8))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(np.stack(channels, axis=-1)).save(args.output)
        args.output.with_suffix('.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
        print(args.output)
    finally:
        client.close()


if __name__ == '__main__':
    main()
