"""Render the editable SimRT vector into PNG and Windows ICO resources."""
import io
import os
from pathlib import Path

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PIL import Image
from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer


def main():
    app = QGuiApplication.instance() or QGuiApplication([])
    assets = Path(__file__).resolve().parent / 'qt_host' / 'assets'
    renderer = QSvgRenderer(str(assets / 'simrt.svg'))
    if not renderer.isValid():
        raise RuntimeError('Invalid SimRT icon source')
    canvas = QImage(1024, 1024, QImage.Format.Format_ARGB32)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    renderer.render(painter)
    painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not canvas.save(buffer, 'PNG'):
        raise RuntimeError('Could not render the SimRT icon')
    image = Image.open(io.BytesIO(bytes(buffer.data()))).convert('RGBA')
    sizes = [(size, size) for size in (16, 20, 24, 32, 48, 64, 128, 256)]
    image.save(assets / 'simrt.ico', sizes=sizes)
    image.resize((256, 256), Image.Resampling.LANCZOS).save(assets / 'simrt.png')
    print('Generated SimRT PNG and 8-resolution ICO resources.')


if __name__ == '__main__':
    main()
