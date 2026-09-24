"""Targeted reboot evidence and restoration helpers; no implicit reboot."""

import json
from pathlib import Path
import shlex
import time

RT_KERNEL = '5.15.129-rt67-intel-ese-standard-lts-rt'
RT_ENTRY = 'Advanced options for Ubuntu>Ubuntu, with Linux ' + RT_KERNEL
FALLBACK_ENTRY = 'Advanced options for Ubuntu>Ubuntu, with Linux 6.8.0-90-generic'
BOOT_ELF = 'MATLAB_ws/rt_b45afdff23ba/x280_rt_single.elf'
BOOT_PORT = 17727

SNAPSHOT = r'''
import json, os, resource, stat, subprocess
from pathlib import Path

def command(args):
    r = subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20)
    return dict(code=r.returncode, output=r.stdout)

home = Path.home()
paths = [home/'.config/systemd/user/pyxcp-host-model.service',
         home/'.local/share/pyxcp-host/autostart.json',
         home/'.local/share/pyxcp-host/model_runner.py']
files = {}
for path in paths:
    if path.is_symlink():
        raise RuntimeError('Refusing symlink: ' + str(path))
    files[str(path)] = dict(text=path.read_text(), mode=stat.S_IMODE(path.stat().st_mode)) if path.exists() else None
processes = []
for entry in Path('/proc').iterdir():
    if not entry.name.isdigit():
        continue
    try:
        exe = os.readlink(entry/'exe')
        if exe.endswith('.elf') and entry.stat().st_uid == os.getuid():
            processes.append(dict(pid=int(entry.name), exe=exe,
                cmdline=(entry/'cmdline').read_bytes().replace(b'\0', b' ').decode(),
                status=(entry/'status').read_text(), limits=(entry/'limits').read_text(),
                stat=(entry/'stat').read_text(),
                threads=command(['ps','-L','-p',entry.name,'-o','pid,tid,cls,rtprio,psr,comm'])))
    except (OSError, ValueError):
        pass
print(json.dumps(dict(
    boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
    kernel=os.uname().release, cmdline=Path('/proc/cmdline').read_text().strip(),
    realtime=Path('/sys/kernel/realtime').read_text().strip() if Path('/sys/kernel/realtime').exists() else None,
    rtprio=resource.getrlimit(resource.RLIMIT_RTPRIO), memlock=resource.getrlimit(resource.RLIMIT_MEMLOCK),
    files=files, processes=processes,
    unit=command(['systemctl','--user','show','pyxcp-host-model.service','-p','ActiveState','-p','SubState','-p','MainPID','-p','ExecMainStartTimestamp','-p','Result','-p','NRestarts']),
    journal=command(['journalctl','--user','-b','-u','pyxcp-host-model.service','--no-pager','-n','60']),
    user_limits=command(['systemctl','show','user@1000.service','-p','LimitRTPRIO','-p','LimitMEMLOCK']),
    network=command(['ip','-brief','address']),
    inhibitors=command(['systemd-inhibit','--list','--no-pager'])
)))
'''


def snapshot(service, destination):
    result = json.loads(service._execute('python3 -c ' + shlex.quote(SNAPSHOT), timeout=40))
    result['autostart'] = service.autostart_status()
    for key, command in {
        'grub': 'sudo -n cat /boot/grub/grub.cfg',
        'grubenv': 'sudo -n grub-editenv /boot/grub/grubenv list',
        'kernel_config': 'cat /boot/config-' + RT_KERNEL,
    }.items():
        result[key] = service._execute(command)
    Path(destination).parent.mkdir(parents=True, exist_ok=True)
    with Path(destination).open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    return result


def arm_one_time_boot(service, before):
    config = before['grub']
    for title in (RT_ENTRY, FALLBACK_ENTRY):
        submenu, entry = title.split('>')
        if config.count("submenu '" + submenu + "'") != 1 or config.count("menuentry '" + entry + "'") != 1:
            raise RuntimeError('Ambiguous or missing boot title: ' + title)
    if 'CONFIG_PREEMPT_RT=y' not in before['kernel_config']:
        raise RuntimeError('Selected kernel is not PREEMPT_RT')
    if any(item['exe'].endswith('/x280_rt_single.elf') for item in before['processes']):
        raise RuntimeError('Boot test model is already running')
    service._execute('sudo -n grub-script-check /boot/grub/grub.cfg')
    service._execute('test -s /boot/vmlinuz-' + RT_KERNEL + ' -a -s /boot/initrd.img-' + RT_KERNEL)
    service.set_autostart(BOOT_ELF, '-port ' + str(BOOT_PORT))
    # Duplicate IDs exist in the installed ECI menu; use unique full titles.
    service._execute('sudo -n grub-set-default ' + shlex.quote(FALLBACK_ENTRY))
    service._execute('sudo -n grub-reboot ' + shlex.quote(RT_ENTRY))
    environment = service._execute('sudo -n grub-editenv /boot/grub/grubenv list')
    if 'next_entry=' + RT_ENTRY not in environment or 'saved_entry=' + FALLBACK_ENTRY not in environment:
        raise RuntimeError('GRUB next/default selection was not stored')
    return environment


def restore_autostart(service, before):
    original = before['autostart']
    if original['enabled']:
        service.set_autostart(original['elf_path'], shlex.join(original.get('arguments', [])))
    else:
        service.set_autostart(None)
    # Restore the inactive selection as well as the enabled flag.
    script = r'''
import json, os, sys, tempfile
from pathlib import Path
request = json.loads(sys.argv[1])
home = Path.home()
allowed = {home/'.config/systemd/user/pyxcp-host-model.service', home/'.local/share/pyxcp-host/autostart.json', home/'.local/share/pyxcp-host/model_runner.py'}
for name, saved in request.items():
    path = Path(name)
    if path not in allowed or path.is_symlink():
        raise RuntimeError('Unexpected restore path')
    if saved is None:
        continue
    fd, temporary = tempfile.mkstemp(prefix='.restore-', dir=path.parent)
    with os.fdopen(fd, 'w') as stream:
        stream.write(saved['text'])
    os.chmod(temporary, saved['mode'])
    os.replace(temporary, path)
'''
    service._execute('python3 -c ' + shlex.quote(script) + ' ' + shlex.quote(json.dumps(before['files'])))
    service._execute('systemctl --user daemon-reload')
    return service.autostart_status()


def validate_boot_daq(service, before, after, destination):
    from pyxcp_host.viewmodel import HostViewModel
    expected = '/home/zh/' + BOOT_ELF
    matches = [item for item in after['processes'] if item['exe'] == expected]
    assert len(matches) == 1, 'Expected exactly one boot-started model'
    process = matches[0]
    fields = dict(line.split('=', 1) for line in after['unit']['output'].splitlines() if '=' in line)
    marker = json.loads(service._execute('cat ' + shlex.quote(expected + '.pyxcp-host.json')))
    start_time = process['stat'].rsplit(')', 1)[1].split()[19]
    checks = dict(boot_changed=before['boot_id'] != after['boot_id'],
                  realtime=after['realtime'] == '1' and after['kernel'] == RT_KERNEL,
                  unit_running=fields.get('ActiveState') == 'active' and int(fields['MainPID']) == process['pid'],
                  identity_matches=marker['pid'] == process['pid'] and str(marker['start_time']) == start_time and marker['elf_path'] == expected,
                  boot_arguments='-port 17727' in process['cmdline'])
    vm = HostViewModel()
    report = dict(checks=checks, process=process, marker=marker, sample_count=0)
    try:
        payload = Path(__file__).resolve().parents[1] / 'validation/requirements_update_20260913/single_payload/x280_rt_single.a2l'
        vm.load_a2l(payload)
        vm.connect('UDP', '192.168.219.86', BOOT_PORT)
        names = [x.name for x in vm.measurements if x.name.endswith('_B.MeasuredOutput')]
        assert len(names) == 1
        report['metadata'] = vm.start_daq(names)
        end = time.monotonic() + 5
        while time.monotonic() < end:
            report['sample_count'] += len(vm.drain_daq())
            time.sleep(.02)
        vm.stop_daq()
        report['sample_count'] += len(vm.drain_daq())
        report['daq'] = vm.daq_diagnostics
        checks['daq_1ms'] = report['metadata']['period_seconds'] == .001
        checks['daq_samples'] = report['sample_count'] > 1000
        report['passed'] = all(checks.values())
    finally:
        vm.close()
        with Path(destination).open('x', encoding='utf-8') as stream:
            json.dump(report, stream, indent=2)
    assert report['passed'], 'Boot DAQ validation failed'
    return report


def collect_run_log_diagnostics(service, validation_report, destination):
    script = r'''
import json, sys
from pathlib import Path
path, offset = sys.argv[1], int(sys.argv[2])
counts = dict(extmode_event_errors=0, legacy_upload_errors=0, no_memory_errors=0)
summaries = []
with open(path, 'rb') as stream:
    stream.seek(offset)
    for raw in stream:
        line = raw.decode('utf-8', errors='replace').strip()
        if line.startswith('extmodeEvent error:'):
            counts['extmode_event_errors'] += 1
        if line.startswith('rtExtModeUpload error:'):
            counts['legacy_upload_errors'] += 1
        if 'error: code -10' in line:
            counts['no_memory_errors'] += 1
        if line.startswith('{'):
            try:
                value = json.loads(line)
                if value.get('event') == 'x280_rt_summary':
                    summaries.append(value)
            except (ValueError, AttributeError):
                pass
print(json.dumps(dict(counts=counts, summaries=summaries, end_bytes=Path(path).stat().st_size)))
'''
    paths = {
        'x280_rt_single': '/home/zh/MATLAB_ws/rt_b45afdff23ba/x280_rt_single.elf.pyxcp-host.log',
        'x280_rt_multirate': '/home/zh/MATLAB_ws/rt_33dc411b62a7/x280_rt_multirate.elf.pyxcp-host.log',
    }
    result = {}
    for record in validation_report['models']:
        command = 'python3 -c {} {} {}'.format(shlex.quote(script), shlex.quote(paths[record['model']]), record['log_start_bytes'])
        result[record['model']] = json.loads(service._execute(command))
    with Path(destination).open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2)
    return result
