#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "source" / "tiny_neighborhood.py"
DIST = ROOT / "dist"
BUILD = ROOT / "build"
RELEASE = ROOT / "release"


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def platform_tag() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower().replace("amd64", "x86_64")
    if system == "darwin":
        system = "macos"
    return f"{system}-{machine}"


def exe_name(name: str) -> str:
    if platform.system().lower() == "windows":
        return name + ".exe"
    return name


def require_pyinstaller() -> None:
    try:
        import PyInstaller.__main__  # noqa: F401
    except Exception:
        print("PyInstaller is not installed.", file=sys.stderr)
        print("Install it with: python -m pip install -r requirements-build.txt", file=sys.stderr)
        raise SystemExit(2)


def build_console_binary(clean: bool) -> Path:
    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--name",
        "tiny-neighborhood",
        "--distpath",
        str(DIST),
        "--workpath",
        str(BUILD),
        str(SOURCE),
    ]
    if clean:
        args.insert(4, "--clean")
    run(args)
    return DIST / exe_name("tiny-neighborhood")


def build_gui_binary(clean: bool) -> Path | None:
    # Windows users often expect a no-console GUI exe. Keep the console binary too,
    # because it is the right one for CLI/headless usage.
    if platform.system().lower() not in {"windows", "darwin"}:
        return None

    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--windowed",
        "--name",
        "TinyNeighborhood",
        "--distpath",
        str(DIST),
        "--workpath",
        str(BUILD),
        str(SOURCE),
    ]
    if clean:
        args.insert(4, "--clean")
    run(args)
    return DIST / exe_name("TinyNeighborhood")


def package_release(version: str, binaries: list[Path]) -> Path:
    RELEASE.mkdir(exist_ok=True)
    tag = platform_tag()
    zip_path = RELEASE / f"tiny-neighborhood-{version}-{tag}.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for binary in binaries:
            if binary and binary.exists():
                z.write(binary, f"bin/{binary.name}")

        z.write(SOURCE, "source/tiny_neighborhood.py")
        for name in ["README_RELEASE.md", "requirements-build.txt", "pyproject.toml"]:
            p = ROOT / name
            if p.exists():
                z.write(p, name)

        license_file = ROOT / "LICENSE"
        if license_file.exists():
            z.write(license_file, "LICENSE")

    return zip_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Tiny Neighborhood release binaries")
    parser.add_argument("--version", default=os.environ.get("TINY_NEIGHBORHOOD_VERSION", "0.1.0"))
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    if not SOURCE.exists():
        raise SystemExit(f"Missing source file: {SOURCE}")

    require_pyinstaller()

    binaries = [build_console_binary(args.clean)]
    gui_binary = build_gui_binary(args.clean)
    if gui_binary:
        binaries.append(gui_binary)

    package = package_release(args.version, binaries)
    print(f"Built release package: {package}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
