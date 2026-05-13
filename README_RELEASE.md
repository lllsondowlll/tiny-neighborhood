# Tiny Neighborhood release kit

This kit builds distributable binaries for Tiny Neighborhood while still shipping the source.

## Why build per OS?

PyInstaller bundles your Python script, the Python interpreter, and imported dependencies into a distributable folder or one-file executable. It supports Windows, macOS, and Linux, but it is **not** a cross-compiler. Build Windows binaries on Windows, Linux binaries on Linux, and macOS binaries on macOS.

GitHub Actions is the easiest way to do that automatically.

## Layout

```text
source/tiny_neighborhood.py
requirements-build.txt
pyproject.toml
scripts/build_binaries.py
.github/workflows/build-release.yml
README_RELEASE.md
```

## Local build

Install build dependencies:

```bash
python -m pip install -r requirements-build.txt
```

Build:

```bash
python scripts/build_binaries.py --clean --version 0.1.0
```

Output:

```text
release/tiny-neighborhood-0.1.0-<platform>-<arch>.zip
```

## Windows notes

The build script creates:

```text
tiny-neighborhood.exe
```

for CLI and GUI usage.

On Windows and macOS it also creates:

```text
TinyNeighborhood.exe
```

or a GUI-style app binary where applicable. Keep the console binary too, because it is the one users want for CLI/headless workflows.

## GitHub Actions build

Commit the files in this kit to your repo, then run the workflow manually from GitHub Actions, or push a tag:

```bash
git tag v0.1.0
git push origin v0.1.0
```

Artifacts will appear for:

```text
ubuntu-latest
windows-latest
macos-latest
```

## Recommended release bundle

For each release, ship:

```text
tiny-neighborhood-<version>-windows-x86_64.zip
tiny-neighborhood-<version>-linux-x86_64.zip
tiny-neighborhood-<version>-macos-arm64/x86_64.zip
source zip/tarball
```

Also include checksums once you are ready to make this public.
