"""Build the SkimWise app for this platform with PyInstaller.

    pip install -e ".[build]"
    python scripts/build.py

Output: dist/SkimWise.exe on Windows (dist/SkimWise on Linux). PyInstaller can't cross-compile,
so build each platform on that platform.
"""

import os
import shutil
import sys
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
ASSETS = SRC / "skimwise" / "assets"
BUILD = ROOT / "build"


def main() -> None:
    shutil.rmtree(BUILD, ignore_errors=True)  # never ship stale build output
    PyInstaller.__main__.run(
        [
            str(SRC / "skimwise" / "__main__.py"),
            "--name=SkimWise",
            "--onefile",  # one file to download and double-click
            "--windowed",  # a GUI app: no console window
            "--noconfirm",
            f"--icon={ASSETS / 'budget-icon.ico'}",
            # Keep the package layout so main.py finds its icons at skimwise/assets.
            f"--add-data={ASSETS}{os.pathsep}skimwise/assets",
            f"--paths={SRC}",
            # Installed for the tests (fpdf2 writes fake PDFs) but never needed by the app. pypdf
            # would only use Pillow to extract images, which SkimWise doesn't do.
            *(f"--exclude-module={m}" for m in ("fpdf", "PIL", "fontTools", "defusedxml")),
            f"--distpath={ROOT / 'dist'}",
            f"--workpath={BUILD}",
            f"--specpath={BUILD}",  # the generated .spec is build output, not source
        ]
    )
    exe = ROOT / "dist" / ("SkimWise.exe" if sys.platform == "win32" else "SkimWise")
    print(f"\nBuilt {exe} ({exe.stat().st_size / 1_048_576:.0f} MB)")


if __name__ == "__main__":
    main()
