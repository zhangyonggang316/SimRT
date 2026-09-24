"""Export sampled data for the native Simulation Data Inspector, without Engine."""

import json
import math
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from numbers import Real
from pathlib import Path
from typing import Mapping, Optional, Protocol, Sequence


class Sample(Protocol):
    elapsed_seconds: float
    value: float


_IMPORT_SCRIPT = """% Import this capture without clearing existing SDI runs or preferences.
pyxcpImportCapture();

function pyxcpImportCapture()
    captureFolder = fileparts(mfilename('fullpath'));
    capture = jsondecode(fileread(fullfile(captureFolder, 'capture.json')));
    assert(strcmp(capture.format, 'pyxcp-host-sdi') && capture.version == 1, ...
        'pyXCP:InvalidCapture', 'Unsupported pyXCP capture format.');
    assert(~isempty(capture.signals), 'pyXCP:EmptyCapture', ...
        'The capture contains no signals.');
    sourceNames = cell(1, numel(capture.signals));
    signalValues = cell(1, numel(capture.signals));
    for signalIndex = 1:numel(capture.signals)
        source = capture.signals(signalIndex);
        sampleTimes = source.time(:);
        sampleValues = source.values(:);
        assert(isnumeric(sampleTimes) && isnumeric(sampleValues) && ...
            ~isempty(sampleTimes) && numel(sampleTimes) == numel(sampleValues) && ...
            all(isfinite(sampleTimes)) && all(isfinite(sampleValues)) && ...
            all(sampleTimes >= 0) && all(diff(sampleTimes) > 0), ...
            'pyXCP:InvalidSamples', 'Invalid or unordered sample data.');
        sourceNames{signalIndex} = char(source.name);
        signalValues{signalIndex} = timeseries(sampleValues, sampleTimes, ...
            'Name', sourceNames{signalIndex});
    end
    runID = Simulink.sdi.createRun(char(capture.run_name), 'namevalue', ...
        sourceNames, signalValues);
    captureRun = Simulink.sdi.getRun(runID);
    for signalIndex = 1:captureRun.SignalCount
        captureSignal = captureRun.getSignalByIndex(signalIndex);
        captureSignal.plotOnSubPlot(1, 1, true);
    end
    Simulink.sdi.view;
end
"""


def _number(value, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError('{} must be a real number'.format(field))
    try:
        number = float(value)
    except OverflowError as exc:
        raise ValueError('{} must fit in a finite double'.format(field)) from exc
    if not math.isfinite(number):
        raise ValueError('{} must be finite'.format(field))
    return number


def export_sdi_session(snapshot: Mapping[str, Sequence[Sample]], destination: Path) -> Path:
    """Create a unique capture folder under destination and return its .m script.

    The JSON preserves each series' own time axis. Empty series are omitted;
    invalid values and non-increasing times are rejected before writing files.
    No MATLAB process is launched and no existing file is overwritten.
    """
    if not isinstance(snapshot, Mapping):
        raise ValueError('SDI capture must be a mapping of signal names to samples')
    signals = []
    for name, points in snapshot.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError('Signal names must be nonempty strings')
        times, values = [], []
        try:
            for point in points:
                stamp = _number(point.elapsed_seconds, 'Sample time')
                value = _number(point.value, 'Sample value')
                if stamp < 0 or (times and stamp <= times[-1]):
                    raise ValueError('Sample times must be nonnegative and strictly increasing')
                times.append(stamp)
                values.append(value)
        except (AttributeError, TypeError) as exc:
            raise ValueError('Each sample must provide elapsed_seconds and value') from exc
        if times:
            signals.append({'name': name, 'time': times, 'values': values})
    if not signals:
        raise ValueError('No sampled data is available for SDI')

    created = datetime.now(timezone.utc)
    capture = {
        'format': 'pyxcp-host-sdi',
        'version': 1,
        'run_name': 'pyXCP capture {}'.format(created.strftime('%Y-%m-%d %H:%M:%S UTC')),
        'created_utc': created.isoformat(),
        'signals': signals,
    }
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix='pyxcp_sdi_{}_'.format(
        created.strftime('%Y%m%d_%H%M%S')), dir=str(destination)))
    with (folder / 'capture.json').open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(capture, stream, ensure_ascii=True, allow_nan=False, indent=2)
        stream.write('\n')
    script_path = folder / 'open_in_sdi.m'
    with script_path.open('x', encoding='ascii', newline='\n') as stream:
        stream.write(_IMPORT_SCRIPT)
    return script_path


def find_matlab_executable() -> Optional[Path]:
    """Find the installed MATLAB CLI without changing PATH or user preferences."""
    command = shutil.which('matlab')
    if command:
        candidate = Path(command).resolve()
        if candidate.is_file():
            return candidate
    program_files = Path(os.environ.get('ProgramFiles', 'C:/Program Files'))
    known = program_files / 'MATLAB' / 'R2024b' / 'bin' / 'matlab.exe'
    return known.resolve() if known.is_file() else None


def launch_sdi(script_path: Path, executable: Optional[Path] = None) -> subprocess.Popen:
    """Start native MATLAB in a new desktop process and return its process handle.

    The importer is also directly runnable from MATLAB if discovery fails.
    Signal data is read only from JSON, never interpolated into executable code.
    """
    script_path = Path(script_path).resolve()
    if script_path.suffix.lower() != '.m' or not script_path.is_file():
        raise ValueError('The SDI importer must be an existing .m file')
    executable = Path(executable).resolve() if executable is not None else find_matlab_executable()
    if executable is None or not executable.is_file():
        raise FileNotFoundError('MATLAB was not found; select matlab.exe or run the exported .m file in MATLAB')
    # MATLAB single-quoted character vectors escape apostrophes by doubling them.
    quoted_path = str(script_path).replace("'", "''")
    command = "try, run('{}'); catch exception, disp(getReport(exception, 'extended')); end".format(quoted_path)
    options = {'cwd': str(script_path.parent), 'shell': False}
    if os.name == 'nt':
        options['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    return subprocess.Popen([str(executable), '-desktop', '-nosplash', '-r', command], **options)
