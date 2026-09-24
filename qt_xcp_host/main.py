"""Launch the PySide6/Qt host with the mandatory C++ data core."""
import argparse
import os
import sys
import tempfile
import traceback
from pathlib import Path

if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ['QT_API'] = 'pyside6'


def main(argv=None):
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName('QtXCPHost')
    app.setOrganizationName('XCP Host')
    try:
        from qt_host.common import apply_theme
        from qt_host.window import MainWindow
        from pyxcp_host.demo import load_demo
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--demo', '--demo-dir', dest='demo', help='Load verified local artifacts without connecting')
        args = parser.parse_args(argv)
        settings = load_demo(args.demo) if args.demo else None
        apply_theme(app)
        window = MainWindow()
        if settings:
            window.apply_demo(settings)
        window.show()
        return app.exec()
    except Exception:
        report = traceback.format_exc()
        log = Path(tempfile.gettempdir()) / 'QtXCPHost-startup.log'
        log.write_text(report, encoding='utf-8')
        QMessageBox.critical(None, 'QtXCPHost 启动失败', '诊断已写入：\n{}'.format(log))
        return 1


if __name__ == '__main__':
    for stream in ('stdout', 'stderr'):
        if getattr(sys, stream) is None:
            setattr(sys, stream, open(os.devnull, 'w', encoding='utf-8'))
    raise SystemExit(main())
