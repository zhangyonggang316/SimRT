"""Parse maintained Python entrypoints after relocation without executing them."""

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
folders = ['app/qt_xcp_host', 'shared/python', 'linux', 'tests/tools',
           'tests/maintenance', 'toolchain/simrt_linux_target/tools', 'toolchain/tools']
files = []
errors = []
for folder in folders:
    for source in (ROOT / folder).rglob('*.py'):
        if any(part in {'build', 'dist', 'vendor', '__pycache__'} or part.startswith('staging_')
               for part in source.relative_to(ROOT).parts):
            continue
        files.append(source.relative_to(ROOT).as_posix())
        try:
            ast.parse(source.read_text(encoding='utf-8-sig'), filename=str(source))
        except (SyntaxError, UnicodeError) as error:
            errors.append({'file': files[-1], 'error': str(error)})
report = {'files': len(files), 'errors': errors, 'passed': not errors}
(ROOT / 'tests/layout/source_syntax.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report, indent=2))
raise SystemExit(bool(errors))
