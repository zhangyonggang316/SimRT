"""Application identity shared by source and packaged launches."""
import sys
from pathlib import Path

from PySide6.QtGui import QIcon


APP_NAME = 'SimRT'


def application_icon():
    return QIcon(str(Path(__file__).resolve().parent / 'assets' / 'simrt.ico'))


def apply_branding(app):
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setWindowIcon(application_icon())
    if sys.platform == 'win32':
        import ctypes
        # Give source and packaged launches the same Windows taskbar identity.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('SimRT.Desktop')
