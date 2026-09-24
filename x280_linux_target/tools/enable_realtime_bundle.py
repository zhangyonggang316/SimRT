"""Create a separate RT bundle with model-rate scheduling and background XCP."""

import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import zipfile


TARGET_ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def enable_realtime_bundle(source, destination):
    source = Path(source).resolve(strict=True)
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError('Choose a new realtime bundle directory; existing deliveries are preserved')
    if source == destination.resolve() or source in destination.resolve().parents:
        raise ValueError('Realtime output must not be nested in the source bundle')
    spec = json.loads((source / 'build_spec.json').read_text(encoding='utf-8'))
    if spec.get('runtime') is not None:
        raise ValueError('Source bundle already specifies an alternate runtime')
    if spec.get('matlab_release') != '2024b' or spec.get('target') != 'x86-64 Linux':
        raise ValueError('Only the R2024b x86-64 Linux generated-main contract is supported')
    sources, defines = spec.get('sources', []), spec.get('defines', [])
    if sources.count('linuxinitialize.c') != 1 or sources.count('ert_main.c') != 1 or '-DMT=0' not in defines:
        raise ValueError('Expected one generated Linux main and single-task runtime source')
    files = list((source / 'src').iterdir())
    if any(path.is_symlink() or not path.is_file() for path in files):
        raise ValueError('Expected a flat source bundle without symlinks')
    if any(Path(name).name != name or not (source / 'src' / name).is_file() for name in sources):
        raise ValueError('Bundle source list is invalid')
    main = (source / 'src' / 'ert_main.c').read_text(encoding='utf-8')
    calls = re.findall(r'\bmyRTOSInit\s*\(\s*([0-9.eE+-]+)\s*,\s*([0-9]+)\s*\)\s*;', main)
    if (len(calls) != 1 or Decimal(calls[0][0]) not in (Decimal('0.001'), Decimal('0.01'), Decimal('0.1'))
            or int(calls[0][1]) != 0):
        raise ValueError('Generated main must call myRTOSInit with 1/10/100 ms and zero subrate threads')
    period_ns = int(Decimal(calls[0][0]) * 1000000000)
    if not re.search(r'\bsem_wait\s*\(\s*&baserateTaskSem\s*\)', main):
        raise ValueError('Generated base-rate semaphore contract is missing')
    model = spec.get('model', '')
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', model):
        raise ValueError('Invalid generated model identifier')
    model_source = source / 'src' / (model + '.c')
    if not model_source.is_file() or not re.search(r'\brtExtModeUpload\s*\(\s*0\s*,', model_source.read_text(encoding='utf-8')):
        raise ValueError('Expected generated in-step base-rate XCP upload')
    if not re.search(r'\b' + re.escape(model) + r'_step\s*\(\s*\)\s*;', main):
        raise ValueError('Expected one single-task model step entry point')
    numst = [value.split('=', 1)[1] for value in defines if value.startswith('-DNUMST=')]
    if len(numst) != 1 or not numst[0].isdigit() or int(numst[0]) < 1:
        raise ValueError('Expected positive NUMST definition')
    original_hashes = {path.name: digest(path) for path in files}
    replacements = {'linuxinitialize.c': 'x280_rt_runtime.c', 'ert_main.c': 'x280_rt_main.c'}
    spec['sources'] = [replacements.get(name, name) for name in sources]
    pool_defines = ('-DXCP_MEM_DAQ_RESERVED_POOL_BLOCKS_NUMBER=', '-DXCP_MEM_RESERVED_POOLS_TOTAL_SIZE=')
    spec['defines'] = [value for value in defines if value != '-DMW_SCHED_OTHER'
                       and not value.startswith(pool_defines)] + [
                           '-DX280_SINGLE_TASK_RT=1', '-DXCP_MEM_DAQ_RESERVED_POOL_BLOCKS_NUMBER=64',
                           '-DXCP_MEM_RESERVED_POOLS_TOTAL_SIZE=1048576']
    spec['runtime'] = dict(name='x280_single_task_rt', period_ns=period_ns, tasking='single',
                           kernel_required_default=True, optimization='O2',
                           main='x280_rt_main.c', xcp_background=True,
                           xcp_event_source='generated_model_step', daq_reserved_blocks=64)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.' + destination.name + '.', dir=str(destination.parent)))
    try:
        shutil.copytree(str(source / 'src'), str(staging / 'src'))
        shutil.copy2(str(TARGET_ROOT / 'src' / 'x280_rt_runtime.c'), str(staging / 'src' / 'x280_rt_runtime.c'))
        template = (TARGET_ROOT / 'src' / 'x280_rt_main.c.in').read_text(encoding='utf-8')
        for token, value in (('@MODEL@', model), ('@PERIOD_SECONDS@', calls[0][0]), ('@NUM_SAMPLE_TIMES@', numst[0])):
            template = template.replace(token, value)
        (staging / 'src' / 'x280_rt_main.c').write_text(template, encoding='utf-8')
        shutil.copy2(str(TARGET_ROOT / 'tools' / 'build_model.py'), str(staging / 'build_model.py'))
        (staging / 'build_spec.json').write_text(json.dumps(spec, indent=2) + '\n', encoding='utf-8')
        manifest = dict(original_bundle=str(source), original_source_sha256=original_hashes,
                        original_build_spec=json.loads((source / 'build_spec.json').read_text(encoding='utf-8')),
                        runtime_sha256=digest(staging / 'src' / 'x280_rt_runtime.c'),
                        main_sha256=digest(staging / 'src' / 'x280_rt_main.c'),
                        generated_main_preserved_but_not_compiled=True,
                        model_sources_unchanged=True)
        (staging / 'realtime_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        if (source / 'sources.zip').is_file():
            shutil.copy2(str(source / 'sources.zip'), str(staging / 'original_sources.zip'))
        with zipfile.ZipFile(staging / 'sources.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted((staging / 'src').iterdir()):
                archive.write(path, 'src/' + path.name)
        if any(digest(staging / 'src' / name) != expected for name, expected in original_hashes.items()):
            raise RuntimeError('Generated sources changed while creating realtime bundle')
        staging.rename(destination)
    except BaseException:
        # Only this freshly-created, verified staging directory is removed on failure.
        shutil.rmtree(str(staging))
        raise
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(enable_realtime_bundle(args.source, args.output))


if __name__ == '__main__':
    main()
