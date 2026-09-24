"""Deploy the locally built 1 ms model and verify it on the SSH target."""

import argparse
from contextlib import closing
from datetime import datetime, timezone
import getpass
import json
import math
from pathlib import Path, PurePosixPath
import shlex
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'qt_xcp_host'))
from pyxcp_host.services.model_payload import file_hash
from pyxcp_host.services.payload_archive import PayloadArchive
from pyxcp_host.services.ssh_deployment import SSHDeployment
from validate_model_periods import run_model


def select_builds(paths, archives):
    expected = {'x280_rt_single': .001}
    records = []
    for path in paths:
        build = json.loads(path.read_text(encoding='utf-8-sig'))
        if (build.get('success') is not True or build.get('build_mode') != 'local'
                or build.get('remote_operations_performed') is not False):
            raise ValueError('Expected a successful local build receipt: ' + str(path))
        model = build.get('model')
        if model not in expected or build.get('period_seconds') != expected[model]:
            raise ValueError('Unexpected model or period in ' + str(path))
        source = Path(build.get('archive') or build['payload'])
        if source.suffix.lower() == '.zip' and build.get('archive_sha256'):
            if file_hash(source) != build['archive_sha256']:
                raise ValueError('Build receipt and payload ZIP do not match')
        payload = archives.load(source)
        if payload['model'] != model:
            raise ValueError('Build receipt and payload model do not match')
        if file_hash(payload['elf']) != build.get('elf_sha256'):
            raise ValueError('Build receipt and payload ELF do not match')
        if payload['protocol'] != 'UDP' or payload['port'] != 17725:
            raise ValueError('Current target validation requires UDP 17725')
        records.append(dict(build=build, payload=payload, receipt=str(path.resolve())))
    if len(records) != 1 or {item['build']['model'] for item in records} != set(expected):
        raise ValueError('Supply exactly one local build receipt for x280_rt_single (1 ms)')
    return records


def main(argv=None):
    with closing(PayloadArchive()) as archives:
        return _run(argv, archives)


def _run(argv, archives):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipts', nargs='+', type=Path, required=True)
    parser.add_argument('--host', default='192.168.219.86')
    parser.add_argument('--user', default='zh')
    parser.add_argument('--seconds', type=float, default=30)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if not math.isfinite(args.seconds) or args.seconds < 3:
        parser.error('--seconds must be at least 3')
    builds = select_builds(args.receipts, archives)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = dict(passed=False, host=args.host, username=args.user,
                  created_utc=datetime.now(timezone.utc).isoformat(),
                  build_mode='local', remote_compilation_performed=False, models=[], cleanup_errors=[])
    remote_root = 'MATLAB_ws/local_validation_' + uuid.uuid4().hex
    service = SSHDeployment()
    with args.output.open('x', encoding='utf-8') as report_file:
        json.dump(report, report_file, indent=2)
        report_file.flush()
        password = getpass.getpass('SSH password: ')

        def reconnect():
            service.connect(args.host, args.user, password=password)

        try:
            reconnect()
            report['kernel'] = service._execute('uname -r').strip()
            # Refuse to compete with any pre-existing target on the fixed XCP port.
            port_probe = "import socket; s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.bind(('0.0.0.0',17725)); s.close()"
            service._execute('python3 -c ' + shlex.quote(port_probe))
            for index, item in enumerate(builds):
                build, payload = item['build'], item['payload']
                record = dict(build_receipt=item['receipt'], elf_sha256=build['elf_sha256'])
                report['models'].append(record)
                remote = str(PurePosixPath(remote_root, build['model']))
                deployment = service.deploy_payload(payload['directory'], remote)
                record['deployment'] = deployment
                model = dict(model=build['model'], period_seconds=build['period_seconds'],
                             remote_directory=deployment['remote_directory'],
                             payload=Path(payload['directory']).name, host=args.host,
                             xcp_port=payload['port'], build_mode='local')
                run_model(service, Path(payload['directory']).parent, model, index, args.seconds,
                          record, ssh_reconnect=reconnect)
                record['passed'] = bool(record.get('passed') and record.get('ssh_disconnected_autonomous'))
                print(json.dumps(dict(model=build['model'], passed=record['passed'],
                                      model_checks=record.get('model_checks'), daq_checks=record.get('daq_checks'),
                                      error=record.get('error'), cleanup_errors=record.get('cleanup_errors'))), flush=True)
                report_file.seek(0)
                json.dump(report, report_file, indent=2)
                report_file.truncate()
                report_file.flush()
                if record.get('cleanup_errors'):
                    raise RuntimeError('Cleanup or runtime evidence failed; no further model will start')
        except Exception as error:
            report['error'] = '{}: {}'.format(type(error).__name__, error)
            print(report['error'], file=sys.stderr)
        finally:
            try:
                if not service.connected:
                    reconnect()
                if service.status().get('running'):
                    service.stop()
            except Exception as error:
                report['cleanup_errors'].append(str(error))
            service.close()
            password = None
            report['passed'] = (len(report['models']) == 1 and all(item.get('passed') for item in report['models'])
                                and not report.get('error') and not report['cleanup_errors'])
            report['finished_utc'] = datetime.now(timezone.utc).isoformat()
            report_file.seek(0)
            json.dump(report, report_file, indent=2)
            report_file.truncate()
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
