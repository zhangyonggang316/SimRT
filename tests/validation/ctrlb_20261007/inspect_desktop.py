"""Read the running R2024b desktop's model and build configuration."""
import argparse
import json
from pathlib import Path
import matlab.engine

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument('--open-model', action='store_true')
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
engine = matlab.engine.connect_matlab('SimRTDesktop')
report = dict(release=engine.version('-release'), pwd=engine.pwd(),
              process_id=engine.feature('getpid'),
              current_system=engine.gcs(),
              initial_diagrams=engine.find_system('type', 'block_diagram'))
if args.open_model:
    model_path = ROOT / 'Demo_XCP_Qt/models/simrt_rt_single/simrt_rt_single.slx'
    engine.open_system(str(model_path), nargout=0)
report['diagrams'] = []
for name in engine.find_system('type', 'block_diagram'):
    item = dict(name=name)
    for key in ('BlockDiagramType', 'FileName', 'Dirty', 'SimulationStatus', 'SimulationMode',
                'HardwareBoard', 'SystemTargetFile', 'Toolchain', 'GenCodeOnly',
                'GenerateMakefile', 'RTWVerbose', 'RTWGenSettings', 'CoderTargetData',
                'PreLoadFcn', 'PostLoadFcn', 'InitFcn', 'PreSaveFcn', 'PostSaveFcn',
                'ExtMode'):
        try:
            item[key] = engine.get_param(name, key)
        except matlab.engine.MatlabExecutionError:
            item[key] = '<not available>'
    report['diagrams'].append(item)
report['registered_target'] = engine.feval('codertarget.target.isTargetRegistered', 'simrtlinux')
report['slbuild_paths'] = engine.which('slbuild', '-all')
report['setup_path'] = engine.which('setupSimRTLinuxTarget')
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(report, indent=2, default=str) + '\n', encoding='utf-8')
print(json.dumps(report, indent=2, default=str))
