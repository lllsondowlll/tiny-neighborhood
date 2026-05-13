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

MAIN_BINARY_NAME = "TinyNeighborhood"
GUI_BINARY_NAME = "TinyNeighborhood_GUI"


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def platform_tag() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower().replace("amd64", "x86_64")
    if system == "darwin":
        system = "macos"
    return f"{system}-{machine}"


def normalize_version(version: str) -> str:
    version = version.strip()
    if version.startswith("refs/tags/"):
        version = version.removeprefix("refs/tags/")
    if version.startswith("v"):
        version = version[1:]
    return version or "0.1.0"


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


def dist_artifact(name: str, windowed: bool = False) -> Path:
    system = platform.system().lower()

    if system == "windows":
        return DIST / f"{name}.exe"

    if system == "darwin" and windowed:
        app_bundle = DIST / f"{name}.app"
        if app_bundle.exists():
            return app_bundle

    return DIST / name


def build_console_binary(clean: bool) -> Path:
    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--name",
        MAIN_BINARY_NAME,
        "--distpath",
        str(DIST),
        "--workpath",
        str(BUILD),
        str(SOURCE),
    ]
    if clean:
        args.insert(4, "--clean")

    run(args)
    return dist_artifact(MAIN_BINARY_NAME)


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
        GUI_BINARY_NAME,
        "--distpath",
        str(DIST),
        "--workpath",
        str(BUILD),
        str(SOURCE),
    ]
    if clean:
        args.insert(4, "--clean")

    run(args)
    return dist_artifact(GUI_BINARY_NAME, windowed=True)


def write_zip_file(z: zipfile.ZipFile, path: Path, archive_path: str) -> None:
    if path.is_file():
        z.write(path, archive_path)
        return

    if path.is_dir():
        for child in path.rglob("*"):
            if child.is_file():
                z.write(child, str(Path(archive_path) / child.relative_to(path)))
        return

    print(f"warning: artifact not found, skipping: {path}", file=sys.stderr)


def package_release(version: str, binaries: list[Path]) -> Path:
    RELEASE.mkdir(exist_ok=True)
    version = normalize_version(version)
    tag = platform_tag()
    zip_path = RELEASE / f"tiny-neighborhood-{version}-{tag}.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for binary in binaries:
            if binary:
                write_zip_file(z, binary, f"bin/{binary.name}")

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
