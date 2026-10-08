"""Pinned SSH access for this machine's reproducible deployment evidence."""

import argparse
import base64
import getpass
import hashlib
import json
from pathlib import Path
import shlex
import sys
import time

import paramiko

HOST = '192.168.219.195'
USER = 'zh'
FINGERPRINT = 'eeTIikDlYn5po2uiSNGEJTglh6lQ+IUFYJS6s2hciv0='


class PinnedHostKey(paramiko.MissingHostKeyPolicy):
    def missing_host_key(self, client, hostname, key):
        actual = base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode()
        if actual != FINGERPRINT:
            raise paramiko.SSHException('Target SSH host key changed')


def connect(password):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(PinnedHostKey())
    client.connect(HOST, username=USER, password=password, timeout=10,
                   auth_timeout=15, look_for_keys=False, allow_agent=False)
    return client


def execute(client, command, password=None, timeout=1800):
    if password is not None:
        command = "sudo -S -p '' -- sh -c " + shlex.quote(command)
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    if password is not None:
        stdin.write(password + '\n')
        stdin.flush()
    stdin.channel.shutdown_write()
    channel = stdout.channel
    output, errors = [], []
    deadline = time.monotonic() + timeout
    while True:
        for ready, receive, chunks in ((channel.recv_ready, channel.recv, output),
                                      (channel.recv_stderr_ready, channel.recv_stderr, errors)):
            while ready():
                data = receive(65536).decode('utf-8', errors='replace')
                chunks.append(data)
                print(data, end='', flush=True)
        if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
            break
        if time.monotonic() > deadline:
            channel.close()
            raise TimeoutError('Remote command timed out')
        time.sleep(.1)
    return dict(command=command, exit_code=channel.recv_exit_status(),
                stdout=''.join(output), stderr=''.join(errors))


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--command')
    source.add_argument('--script', type=Path)
    parser.add_argument('--sudo', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=1800)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Evidence file already exists')
    command = args.command
    if args.script:
        command = 'python3 -c ' + shlex.quote(args.script.read_text(encoding='utf-8'))
    password = getpass.getpass('SSH/sudo password: ')
    client = connect(password)
    try:
        result = execute(client, command, password if args.sudo else None, args.timeout)
        result.update(host=HOST, user=USER, host_key_sha256=FINGERPRINT)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
        return result['exit_code']
    finally:
        client.close()


if __name__ == '__main__':
    raise SystemExit(main())
