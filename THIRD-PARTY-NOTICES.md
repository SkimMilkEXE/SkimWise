# Third-party notices

SkimWise is MIT licensed (see [LICENSE](LICENSE)). The release `SkimWise.exe` bundles the open-source
software below, each under its own license. Their source code is available at the links given.

| Software | Used for | License |
|---|---|---|
| [Qt](https://www.qt.io/) and [PySide6](https://doc.qt.io/qtforpython-6/) (Qt for Python) | the user interface and charts | [LGPL-3.0](https://www.gnu.org/licenses/lgpl-3.0.html) |
| [Python](https://www.python.org/) | the runtime | [PSF License](https://docs.python.org/3/license.html) |
| [pypdf](https://github.com/py-pdf/pypdf) | reading PDF bank statements | [BSD-3-Clause](https://github.com/py-pdf/pypdf/blob/main/LICENSE) |
| [Atkinson Hyperlegible](https://github.com/googlefonts/atkinson-hyperlegible) font, by the Braille Institute of America | the Atkinson Hyperlegible reading font | [SIL Open Font License 1.1](src/skimwise/assets/fonts/OFL-AtkinsonHyperlegible.txt) |
| [OpenDyslexic](https://github.com/antijingoist/opendyslexic) font, by Abbie Gonzalez | the OpenDyslexic reading font | [SIL Open Font License 1.1](src/skimwise/assets/fonts/OFL-OpenDyslexic.txt) |
| [PyInstaller](https://pyinstaller.org/) bootloader | packaging the single-file exe | [GPL-2.0 with a bootloader exception](https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt) that allows distributing the built program under any license |

## Qt / PySide6 (LGPL-3.0)

SkimWise uses Qt and PySide6 unmodified, as separate libraries. The exe unpacks them to a temporary
folder at startup and loads them from there, so they can be replaced with other compatible versions.
You can also run SkimWise from source with your own copy of PySide6 (see "Build from source" in the
[README](README.md)). Qt's source code is available from [qt.io](https://www.qt.io/download-open-source)
and PySide6's from [code.qt.io](https://code.qt.io/cgit/pyside/pyside-setup.git/).
