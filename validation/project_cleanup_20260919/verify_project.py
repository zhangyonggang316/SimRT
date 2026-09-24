"""Check documentation links, retained ZIPs and receipt loading without SSH/MATLAB."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'qt_xcp_host')]
from markdown_it import MarkdownIt
from pyxcp_host.services.payload_archive import PayloadArchive
from validate_local_workflow import select_builds


def main():
    documents = ['README.md', 'docs/README.md', 'docs/ARCHITECTURE.md',
                 'docs/NEW_MACHINE_DEPLOYMENT.md', 'docs/TROUBLESHOOTING.md',
                 'docs/PROJECT_LAYOUT.md', 'docs/TOOLCHAIN.md', 'docs/REPRODUCE.md',
                 'docs/ENVIRONMENT.md', 'x280_linux_target/README.md', 'tools/README.md',
                 'validation/README.md', 'validation/project_cleanup_20260919/README.md']
    checked = []
    parser = MarkdownIt()
    for relative in documents:
        path = ROOT / relative
        for token in parser.parse(path.read_text(encoding='utf-8-sig')):
            for child in token.children or []:
                if child.type != 'link_open':
                    continue
                link = urlsplit(child.attrGet('href'))
                if link.scheme or link.netloc or not link.path:
                    continue
                target = (path.parent / unquote(link.path)).resolve()
                assert target.exists(), (relative, child.attrGet('href'))
                checked.append(dict(document=relative, link=child.attrGet('href')))
    cleanup = json.loads((OUTPUT / 'cleanup_result.json').read_text(encoding='utf-8-sig'))
    assert cleanup['apply'] and cleanup['passed'] and not cleanup['failed']
    archives = []
    for relative in ('Demo_XCP_Qt/models/x280_rt_single/x280_rt_single_local',
                     'x280_linux_target/drivers/tc1013/models/x280_can_loopback/x280_can_loopback_local'):
        for path in sorted((ROOT / relative).iterdir()):
            assert path.is_file() and path.suffix == '.zip', path
            with closing(PayloadArchive()) as loader:
                selected = loader.load(path)
                archives.append(dict(path=str(path.relative_to(ROOT)), model=selected['model'],
                                     sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    receipt = ROOT / 'Demo_XCP_Qt/models/x280_rt_single/x280_rt_single_ert_rtw/x280_local_build.json'
    with closing(PayloadArchive()) as loader:
        build, = select_builds([receipt], loader)
        extracted = Path(build['payload']['directory'])
        assert extracted.is_dir()
    assert not extracted.exists()
    suite = unittest.defaultTestLoader.discover(str(ROOT / 'tools/tests'), pattern='test_validate_local_workflow.py')
    with (OUTPUT / 'workflow_tests.log').open('w', encoding='utf-8') as stream:
        tests = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    assert tests.wasSuccessful() and not tests.skipped
    subprocess.run([sys.executable, '-B', str(ROOT / 'tools/validate_local_workflow.py'), '--help'],
                   check=True, capture_output=True)
    startup = json.loads((OUTPUT / 'installed_startup.json').read_text(encoding='utf-8-sig'))
    executable = ROOT / 'Demo_XCP_Qt/app/QtXCPHost.exe'
    assert startup['passed'] and hashlib.sha256(executable.read_bytes()).hexdigest() == startup['executable_sha256']
    report = dict(passed=True, documents=len(documents), local_links=len(checked), links=checked,
                  model_archives=archives, real_receipt_loaded=True, temporary_cache_removed=True,
                  workflow_tests=tests.testsRun, matlab_started=False, remote_operations=False,
                  executable_sha256=startup['executable_sha256'])
    (OUTPUT / 'project_verification.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key not in ('links', 'model_archives')}))


if __name__ == '__main__':
    main()
