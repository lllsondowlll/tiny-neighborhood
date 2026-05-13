# Tiny Neighborhood


<img width="1916" height="1142" alt="image" src="https://github.com/user-attachments/assets/2950c2fe-132c-4bc5-bbc8-7c0df7ba76ba" />



Tiny Neighborhood is a lightweight Original Xbox file manager for Xboxs running in Debug mode.

It includes:

- GUI file browser
- CLI commands
- File and folder upload/download
- Rename/delete
- `.xbe` launch
- Console reboot

## Download

Download the release zip for your OS from GitHub Releases and extract it.

Typical files:

```text
tiny-neighborhood-<version>-windows-x86_64.zip
tiny-neighborhood-<version>-linux-x86_64.zip
tiny-neighborhood-<version>-macos-<arch>.zip
```

## Windows

The Windows release includes:

```text
TinyNeighborhood.exe
TinyNeighborhood_GUI.exe
```

Use:

```text
TinyNeighborhood.exe      CLI + GUI launcher
TinyNeighborhood_GUI.exe  GUI-only launcher
```

For terminal use:

```powershell
.\TinyNeighborhood.exe connect 192.168.1.50
.\TinyNeighborhood.exe --help
```

For GUI use, double-click:

```text
TinyNeighborhood_GUI.exe
```

## Linux/macOS

Run:

```bash
./TinyNeighborhood
```

For CLI:

```bash
./TinyNeighborhood connect 192.168.1.50
./TinyNeighborhood --help
```

If needed:

```bash
chmod +x ./TinyNeighborhood
```

## First-Time Setup

Save the Xbox Debug address:

```bash
TinyNeighborhood connect 192.168.1.50
```

Optional custom port allowed:

```bash
TinyNeighborhood connect 192.168.1.50 731
TinyNeighborhood connect 192.168.1.50:731
```

## GUI Usage

Launch the GUI:

```bash
TinyNeighborhood
```

or on Windows:

```text
TinyNeighborhood_GUI.exe
```

Basic use:

1. Enter Xbox Debug IP.
2. Click **Connect**.
3. Browse drives/folders.
4. Right-click for actions.

## CLI Commands

List drives:

```bash
TinyNeighborhood ls
```

List folder:

```bash
TinyNeighborhood ls "E:\"
```

Upload file:

```bash
TinyNeighborhood upload ./local-file.bin "E:\"
```

Download file:

```bash
TinyNeighborhood download "E:\remote-file.bin" ./
```

Upload folder:

```bash
TinyNeighborhood upload-dir ./local-folder "E:\"
```

Download folder:

```bash
TinyNeighborhood download-dir "E:\remote-folder" ./
```

Rename:

```bash
TinyNeighborhood rename "E:\old-name.bin" "E:\new-name.bin"
```

Delete file:

```bash
TinyNeighborhood rm "E:\file.bin"
```

Delete folder:

```bash
TinyNeighborhood rmdir "E:\folder" --recursive
```

Launch XBE:

```bash
TinyNeighborhood launch "E:\default.xbe"
```

Reboot:

```bash
TinyNeighborhood reboot
```

## Command Reference

```text
connect       Save Xbox Debug IP (port optional)
ping          Test connection
drives        Show available drives
ls            List drives or folder contents
raw           Send raw XBDM command
mkdir         Create folder
rm            Delete file
rmdir         Delete folder
rename        Rename file/folder
upload        Upload file
download      Download file
upload-dir    Upload folder recursively
download-dir  Download folder recursively
launch        Launch .xbe
reboot        Reboot Xbox/Xemu
```

Aliases:

```text
put       upload
get       download
put-dir   upload-dir
get-dir   download-dir
run       launch
```

## Override Saved Host

```bash
TinyNeighborhood --host 192.168.1.50 ls
TinyNeighborhood --host 192.168.1.50 --port 731 ls
```

Environment variable:

```bash
XBOX=192.168.1.50:731 TinyNeighborhood ls
```

PowerShell:

```powershell
$env:XBOX="192.168.1.50:731"
.\TinyNeighborhood.exe ls
```

## Path Notes

Xbox paths use drive letters:

```text
E:\
F:\
```

Quote paths with spaces:

```bash
TinyNeighborhood ls "E:\Example Folder"
```

Forward-slash paths also work:

```bash
TinyNeighborhood ls /E/
TinyNeighborhood upload ./local-file.bin /E/
```

## Xemu NAT

Forward TCP port `731`:

```text
Host 731 -> Guest 731
```

Then connect to the host IP:

```bash
TinyNeighborhood connect 192.168.1.50 731
```
