"""Publish the measured result without replacing the failed DAQ verdict."""
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
folder = Path(__file__).parent


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


report = read(folder / 'model_validation.json')
display = read(folder / 'display_validation.json')
before, after = read(folder / 'before.json'), read(folder / 'after.json')
assert len(after['processes']) == len(before['processes']) == 1
restored = all(before['processes'][0][key] == after['processes'][0][key]
               for key in ('elf', 'sha256', 'arguments'))
assert restored and before['autostart'] == after['autostart']
assert before['boot_id'] == after['boot_id']
model = report['model']
timing = model['model_passed'] and all(value for key, value in report['checks'].items() if key != 'workflow')
summary = dict(validated_on='2026-10-07', passed=report['passed'],
    requested_daq_seconds=120, model='simrt_rt_single',
    archive='20261006_180720_528.zip',
    elf_sha256=report['deployment']['files']['simrt_rt_single.elf'],
    timing_50us_passed=timing, display_passed=display['passed'],
    autonomous_passed=report['checks']['autonomous'],
    daq_lossless_passed=model['daq_passed'],
    failed_daq_checks=[key for key, value in model['daq_checks'].items() if not value],
    interval_min_ns=model['runtime']['model_step_interval_min_ns'],
    interval_max_ns=model['runtime']['model_step_interval_max_ns'],
    received_samples=model['sample_count'],
    transport_counter_gaps=model['daq']['transport_counter_gaps'],
    timestamp_gap_samples=model['daq']['timestamp_gap_samples'],
    previous_model_restored=restored, active_model=after['processes'][0]['elf'],
    active_pid=after['processes'][0]['pid'], autostart_unchanged=True,
    target_rebooted=False, long_duration_validation='not_requested',
    can_hardware_validation='not_run_device_not_present',
    serial_dio_electrical_validation='not_repeated')
write(folder / 'summary.json', summary)
delivery = ROOT / 'Demo_XCP_Qt'
selection_path = delivery / 'validation/current_selection.json'
selection = read(selection_path)
assert selection['elf_sha256'] == summary['elf_sha256']
selection.update(target_validation_repeated=True, target_validation='failed_daq_integrity',
    target_validation_passed=False, timing_validation_passed=bool(timing),
    timing_validation_seconds=120, daq_lossless_validation_passed=False,
    target_model_activated=False, validation_report='target_20261007/README.md')
write(selection_path, selection)
package_path = delivery / 'package_report.json'
package = read(package_path)
package.update(target_validation='failed_daq_integrity', model_timing_passed=bool(timing),
    daq_lossless_passed=False, target_validation_report='validation/target_20261007/README.md')
write(package_path, package)
delivery_report_path = delivery / 'validation/delivery_report.json'
delivery_report = read(delivery_report_path)
delivery_report['target_validation'] = summary
write(delivery_report_path, delivery_report)
copy = delivery / 'validation/target_20261007'
copy.mkdir(parents=True, exist_ok=True)
for name in ('summary.json', 'before.json', 'after.json', 'model_build.json',
             'model_validation.json', 'display_validation.json',
             'renamed_model_console.txt', 'physical_session_capture.txt'):
    shutil.copy2(folder / name, copy / name)
print(json.dumps(summary, indent=2))
