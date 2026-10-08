"""Start a finite detached target timing monitor, or fetch its recorded results."""
import argparse
import getpass
import hashlib
import json
from pathlib import Path
import shlex
import sys
import uuid

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'shared/python'))
from pyxcp_host.services.ssh_deployment import SSHDeployment
sys.excepthook = sys.__excepthook__


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--elf')
    parser.add_argument('--fetch', type=Path)
    parser.add_argument('--seconds', type=int, default=54000)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if bool(args.elf) == bool(args.fetch) or args.output.exists():
        parser.error('Choose --elf or --fetch, and a new output directory')
    args.output.mkdir(parents=True)
    service = SSHDeployment()
    try:
        service.connect('192.168.193.195', 'zh', password=getpass.getpass('SSH password: '))
        if args.fetch:
            receipt = json.loads(args.fetch.read_text(encoding='utf-8'))
        else:
            status = service.status(args.elf)
            if not status['running'] or status['elf_path'] != args.elf:
                raise RuntimeError('The selected model must already be running')
            unit = 'simrt-jitter-soak-' + uuid.uuid4().hex[:8]
            remote = '/home/zh/MATLAB_ws/' + unit
            script = remote + '.py'
            expected = hashlib.sha256((ROOT / 'tests/tools/scripts' / 'monitor_rt_soak.py').read_bytes()).hexdigest()
            with service._client.open_sftp() as sftp:
                sftp.put(str(ROOT / 'tests/tools/scripts' / 'monitor_rt_soak.py'), script)
                with sftp.open(script, 'rb') as stream:
                    if hashlib.sha256(stream.read()).hexdigest() != expected:
                        raise RuntimeError('Monitor script upload hash mismatch')
            command = ['systemd-run', '--user', '--unit=' + unit, '--property=CPUWeight=10',
                '--', 'python3', script, '--elf', args.elf, '--pid', str(status['pid']),
                '--seconds', str(args.seconds), '--output', remote]
            service._execute(shlex.join(command))
            receipt = dict(unit=unit, remote_directory=remote, model=status, seconds=args.seconds,
                script_sha256=expected)
            # The first sample proves execution started before returning to the caller.
            probe = "import pathlib,time; p=pathlib.Path(%r); deadline=time.monotonic()+10\nwhile not p.exists() and time.monotonic()<deadline: time.sleep(.2)\nassert p.exists(), 'Monitor did not publish its initial sample'" % (remote + '/summary.json')
            service._execute('python3 -c ' + shlex.quote(probe), timeout=15)
        receipt['unit_state'] = service._execute('systemctl --user show ' + shlex.quote(receipt['unit']) + ' -p ActiveState -p SubState -p Result')
        with service._client.open_sftp() as sftp:
            for name in ('summary.json', 'samples.jsonl'):
                sftp.get(receipt['remote_directory'] + '/' + name, str(args.output / name))
        (args.output / 'receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        summary = json.loads((args.output / 'summary.json').read_text(encoding='utf-8'))
        print(json.dumps(dict(receipt=receipt, state=summary['state'], passed=summary['passed'],
            observed_seconds=summary['observed_seconds'], first_failure=summary['first_failure']), indent=2))
    finally:
        service.close()


if __name__ == '__main__':
    main()
