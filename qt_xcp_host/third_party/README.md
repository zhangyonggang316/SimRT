# Third-Party Components

The Qt host uses unmodified PySide6 Essentials 6.8.3 / Qt 6.8.3 and shiboken6 6.8.3,
loaded as dynamic libraries. Qt is not statically linked into the application's C++ data core.
The packaged `_internal/PySide6` and `_internal/shiboken6` directories contain the runtime libraries.

The license metadata shipped by those Python wheels is retained alongside this notice.
The LGPL v3 text and its incorporated GPL v3 text are also included here, obtained unchanged from:

- https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/LGPL-3.0-only.txt
- https://github.com/qt/qtbase/blob/v6.8.3/LICENSES/GPL-3.0-only.txt

Corresponding upstream sources and official licensing information:

- Qt 6.8.3: https://download.qt.io/archive/qt/6.8/6.8.3/single/
- PySide / Shiboken 6.8.3: https://code.qt.io/cgit/pyside/pyside-setup.git/tag/?h=v6.8.3
- Qt for Python: https://doc.qt.io/qtforpython-6/licenses.html

Other Python dependencies retain their installed metadata and notices in this directory, including
Matplotlib 3.9.4, NumPy 2.0.2, pyxcp 0.22.32, Paramiko 4.0.0 and their dependencies.
The portable LLVM-MinGW toolchain notice is included for the statically linked compiler runtime.
Application and data-core source and build instructions are in the full project's `qt_xcp_host` directory.
This inventory is not a legal opinion or a substitute for reviewing external distribution obligations.
