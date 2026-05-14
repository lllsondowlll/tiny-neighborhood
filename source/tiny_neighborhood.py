#!/usr/bin/env python3
from __future__ import annotations

import configparser
import datetime
import os
import queue
import shlex
import socket
import struct
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

DEFAULT_PORT = 731
CHUNK = 64 * 1024


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


CONFIG_FILE = app_dir() / "config.ini"


class XBDMError(RuntimeError):
    pass


def xp(path: str) -> str:
    p = path.strip().strip('"')
    if p in ("", "Root", "Computer"):
        return ""
    if len(p) >= 3 and p[0] in "/\\" and p[1].isalpha() and p[2] in "/\\":
        drive = p[1].upper()
        rest = p[3:].replace("/", "\\")
        return f"{drive}:\\{rest}" if rest else f"{drive}:\\"
    if len(p) >= 2 and p[1] == ":":
        drive = p[0].upper()
        rest = p[2:].replace("/", "\\")
        if not rest:
            return f"{drive}:\\"
        if not rest.startswith("\\"):
            rest = "\\" + rest
        return f"{drive}:{rest}"
    return p.replace("/", "\\")


def q(value: str) -> str:
    if '"' in value:
        raise XBDMError("XBDM values cannot contain double quotes")
    return '"' + value + '"'


def rjoin(root: str, *parts: str) -> str:
    r = xp(root).rstrip("\\")
    tail = "\\".join(str(p).strip("/\\").replace("/", "\\") for p in parts if str(p))
    if not r and len(tail) == 2 and tail[1] == ":":
        return tail + "\\"
    return r + "\\" + tail if tail else r


def remote_parent(path: str) -> str:
    p = xp(path).rstrip("\\")
    if not p:
        return ""
    if len(p) <= 2 and p[1:2] == ":":
        return ""
    if len(p) <= 3:
        return ""
    return p.rsplit("\\", 1)[0] if "\\" in p[3:] else p[:3]


def remote_basename(path: str) -> str:
    p = xp(path).rstrip("\\")
    if len(p) == 2 and p[1] == ":":
        return p + "\\"
    return p.rsplit("\\", 1)[-1]


def filetime_to_local(hi: int, lo: int) -> str:
    value = (hi << 32) | lo
    if value <= 0:
        return ""
    unix_seconds = (value / 10_000_000) - 11644473600
    try:
        return datetime.datetime.fromtimestamp(unix_seconds).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def human_size(n: int) -> str:
    units = ["B", "KiB", "MiB", "GiB"]
    val = float(n)
    for u in units:
        if val < 1024 or u == units[-1]:
            return f"{int(val)} {u}" if u == "B" else f"{val:.1f} {u}"
        val /= 1024


def parse_int_auto(s: str) -> int:
    return int(s, 0)


def parse_dir_entry(line: str) -> dict:
    entry = {"raw": line}
    try:
        tokens = shlex.split(line, posix=True)
    except ValueError:
        return entry

    flags = []
    for tok in tokens:
        if "=" in tok:
            k, v = tok.split("=", 1)
            entry[k.lower()] = v
        else:
            flags.append(tok.lower())

    entry["flags"] = flags
    entry["is_dir"] = "directory" in flags
    entry["size"] = (parse_int_auto(entry.get("sizehi", "0")) << 32) | parse_int_auto(entry.get("sizelo", "0"))
    entry["changed"] = filetime_to_local(parse_int_auto(entry.get("changehi", "0")), parse_int_auto(entry.get("changelo", "0")))
    entry["created"] = filetime_to_local(parse_int_auto(entry.get("createhi", "0")), parse_int_auto(entry.get("createlo", "0")))
    entry["name"] = entry.get("name", "")
    entry["path"] = entry.get("path", "")
    return entry


def drive_entries_from_drivelist(drives: str) -> list[dict]:
    entries = []
    seen = set()
    for ch in drives.strip():
        if not ch.isalpha():
            continue
        d = ch.upper()
        if d in seen:
            continue
        seen.add(d)
        entries.append({
            "name": f"{d}:\\",
            "path": f"{d}:\\",
            "is_dir": True,
            "size": 0,
            "changed": "",
            "created": "",
            "flags": ["directory", "drive"],
        })
    entries.sort(key=lambda e: e["name"].lower())
    return entries


class XBDMClient:
    def __init__(self, host: str, port: int = DEFAULT_PORT, timeout: float = 60.0, progress=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.s: socket.socket | None = None
        self.progress = progress

    def __enter__(self):
        self.s = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.s.settimeout(self.timeout)
        code, msg = self.resp()
        if code not in (200, 201):
            raise XBDMError(f"bad greeting: {code}- {msg}")
        return self

    def __exit__(self, *exc):
        if self.s:
            try:
                self.s.close()
            finally:
                self.s = None

    def exact(self, n: int) -> bytes:
        out = bytearray()
        while len(out) < n:
            b = self.s.recv(n - len(out))
            if not b:
                raise XBDMError(f"closed while reading {n} bytes; got {len(out)}")
            out.extend(b)
        return bytes(out)

    def line(self) -> str:
        out = bytearray()
        while True:
            b = self.s.recv(1)
            if not b:
                raise XBDMError("closed while reading line")
            if b == b"\r":
                lf = self.s.recv(1)
                if lf not in (b"\n", b"\x00"):
                    raise XBDMError(f"bad line ending: {lf!r}")
                return out.decode("ascii", errors="replace")
            out.extend(b)

    def resp(self):
        line = self.line()
        if len(line) < 3 or not line[:3].isdigit():
            raise XBDMError(f"bad response: {line!r}")
        return int(line[:3]), line[4:] if len(line) > 4 else ""

    def cmd(self, text: str):
        self.s.sendall(text.encode("ascii") + b"\r\n")
        return self.resp()

    def ok(self, text: str):
        code, msg = self.cmd(text)
        if not (200 <= code < 300):
            raise XBDMError(f"{text!r} failed: {code}- {msg}")
        return code, msg

    def multiline(self):
        lines = []
        while True:
            line = self.line()
            if line == ".":
                break
            lines.append(line)
        return lines

    def drivelist(self) -> str:
        _, msg = self.ok("drivelist")
        return msg

    def dirlist(self, remote_dir: str):
        code, msg = self.cmd(f"dirlist name={q(xp(remote_dir))}")
        if code != 202:
            if 200 <= code < 300:
                return []
            raise XBDMError(f"dirlist failed: {code}- {msg}")
        parent = xp(remote_dir)
        entries = []
        for line in self.multiline():
            e = parse_dir_entry(line)
            if e.get("name"):
                e["path"] = rjoin(parent, e["name"])
            entries.append(e)
        return entries

    def mkdir(self, remote_dir: str):
        self.ok(f"mkdir name={q(xp(remote_dir))}")

    def mkdir_if_missing(self, remote_dir: str):
        code, msg = self.cmd(f"mkdir name={q(xp(remote_dir))}")
        # 410 commonly means already exists / cannot create because it exists.
        if code in (200, 410):
            return
        if not (200 <= code < 300):
            raise XBDMError(f"mkdir {remote_dir!r} failed: {code}- {msg}")

    def delete(self, remote_path: str, is_dir: bool = False):
        cmd = f"delete name={q(xp(remote_path))}"
        if is_dir:
            cmd += " dir"
        self.ok(cmd)

    def rename(self, old_path: str, new_path: str):
        self.ok(f"rename name={q(xp(old_path))} newname={q(xp(new_path))}")

    def put(self, local: str, remote: str):
        src = Path(local)
        dest = xp(remote)
        size = src.stat().st_size
        code, msg = self.cmd(f"sendfile name={q(dest)} length={size}")
        if code != 204:
            raise XBDMError(f"sendfile rejected: {code}- {msg}")

        sent = 0
        with src.open("rb") as f:
            while True:
                b = f.read(CHUNK)
                if not b:
                    break
                self.s.sendall(b)
                sent += len(b)
                if self.progress:
                    self.progress(sent, size)
        code, msg = self.resp()
        if not (200 <= code < 300):
            raise XBDMError(f"upload failed after {sent} bytes: {code}- {msg}")

    def get(self, remote: str, local: str):
        src = xp(remote)
        out = Path(local)
        code, msg = self.cmd(f"getfile name={q(src)}")
        if code != 203:
            raise XBDMError(f"getfile rejected: {code}- {msg}")
        size = struct.unpack("<I", self.exact(4))[0]
        got = 0
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("wb") as f:
            while got < size:
                b = self.exact(min(CHUNK, size - got))
                f.write(b)
                got += len(b)
                if self.progress:
                    self.progress(got, size)

    def launch(self, remote_xbe: str, debug: bool = True):
        title = xp(remote_xbe)
        cmd = f"magicboot title={q(title)}"
        if debug:
            cmd += " debug"
        self.s.sendall(cmd.encode("ascii") + b"\r\n")
        try:
            code, msg = self.resp()
        except (OSError, XBDMError, socket.timeout):
            return "sent; connection closed while booting"
        if not (200 <= code < 300):
            raise XBDMError(f"magicboot failed: {code}- {msg}")
        return "launched"



    def reboot(self):
        self.s.sendall(b"reboot\r\n")
        try:
            code, msg = self.resp()
        except (OSError, XBDMError, socket.timeout):
            return "sent; connection closed while rebooting"
        if not (200 <= code < 300):
            raise XBDMError(f"reboot failed: {code}- {msg}")
        return "reboot command accepted"


class FolderPicker(tk.Toplevel):
    def __init__(self, parent, title="Select folder"):
        super().__init__(parent)
        self.title(title)
        self.geometry("700x480")
        self.transient(parent)
        self.grab_set()

        self.selected_path = None
        self.current_path = tk.StringVar(value=str(Path.home()))

        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")

        ttk.Label(top, text="Path").pack(side="left")
        self.path_entry = ttk.Entry(top, textvariable=self.current_path)
        self.path_entry.pack(side="left", fill="x", expand=True, padx=4)
        self.path_entry.bind("<Return>", lambda e: self.load_path(self.current_path.get()))

        ttk.Button(top, text="Up", command=self.go_up).pack(side="left", padx=2)
        ttk.Button(top, text="Refresh", command=lambda: self.load_path(self.current_path.get())).pack(side="left", padx=2)

        columns = ("name", "path")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", selectmode="browse")
        self.tree.heading("name", text="Folder")
        self.tree.column("name", width=260, anchor="w")
        self.tree.heading("path", text="Path")
        self.tree.column("path", width=420, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.tree.bind("<Double-1>", lambda e: self.open_selected())
        self.tree.bind("<Return>", lambda e: self.open_selected())

        bottom = ttk.Frame(self, padding=(8, 0, 8, 8))
        bottom.pack(fill="x")

        ttk.Button(bottom, text="Upload selected folder", command=self.choose_selected).pack(side="right", padx=4)
        ttk.Button(bottom, text="Cancel", command=self.cancel).pack(side="right", padx=4)
        ttk.Button(bottom, text="Open", command=self.open_selected).pack(side="left", padx=4)

        self.load_path(self.current_path.get())

        self.protocol("WM_DELETE_WINDOW", self.cancel)

    def load_path(self, path):
        p = Path(path).expanduser()
        try:
            p = p.resolve()
        except Exception:
            pass

        if not p.exists() or not p.is_dir():
            messagebox.showerror("Folder picker", f"Not a folder: {p}", parent=self)
            return

        self.current_path.set(str(p))
        self.tree.delete(*self.tree.get_children())

        # Add directories only. Single-click selects the directory; double-click opens it.
        dirs = []
        try:
            for child in p.iterdir():
                if child.is_dir():
                    dirs.append(child)
        except PermissionError:
            messagebox.showerror("Folder picker", f"Permission denied: {p}", parent=self)
            return

        dirs.sort(key=lambda x: x.name.lower())
        for child in dirs:
            self.tree.insert("", "end", values=(child.name, str(child)))

    def selected(self):
        sel = self.tree.selection()
        if not sel:
            return None
        vals = self.tree.item(sel[0], "values")
        return Path(vals[1])

    def open_selected(self):
        p = self.selected()
        if p:
            self.load_path(str(p))

    def choose_selected(self):
        p = self.selected()
        if not p:
            messagebox.showinfo("Folder picker", "Select a folder first.", parent=self)
            return
        self.selected_path = str(p)
        self.destroy()

    def go_up(self):
        p = Path(self.current_path.get())
        parent = p.parent
        if parent != p:
            self.load_path(str(parent))

    def cancel(self):
        self.selected_path = None
        self.destroy()


class XBDMGui(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Tiny Neighborhood")
        self.geometry("1040x650")

        self.q = queue.Queue()
        self.current_path = tk.StringVar(value="")
        self.host_var = tk.StringVar(value="")
        self.port_var = tk.StringVar(value=str(DEFAULT_PORT))
        self.debug_var = tk.BooleanVar(value=True)

        self.sort_state = {"column": "name", "descending": False}
        self.current_entries = []
        self.context_menu = None
        self.context_menu_open = False
        self.busy = False
        self.connected = False
        self.manual_disconnect = False
        self.reconnect_pending = False
        self.reconnect_attempt = 0
        self.suppress_next_list_log = False
        self.auto_refresh_ms = 5000
        self.reconnect_ms = 5000

        self.load_config()
        self.ensure_config_exists()

        self._build()
        self.after(100, self._poll_queue)
        self.after(self.auto_refresh_ms, self.auto_refresh)

    def load_config(self):
        cfg = configparser.ConfigParser()
        if CONFIG_FILE.exists():
            cfg.read(CONFIG_FILE)
            self.host_var.set(cfg.get("xbox", "host", fallback=""))
            self.port_var.set(cfg.get("xbox", "port", fallback=str(DEFAULT_PORT)) or str(DEFAULT_PORT))

    def ensure_config_exists(self):
        if not CONFIG_FILE.exists():
            self.save_config()

    def save_config(self):
        cfg = configparser.ConfigParser()
        cfg["xbox"] = {
            "host": self.host_var.get().strip(),
            "port": self.port_var.get().strip() or str(DEFAULT_PORT),
        }
        with CONFIG_FILE.open("w", encoding="utf-8") as f:
            cfg.write(f)

    def _build(self):
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")

        ttk.Label(top, text="Xbox IP").pack(side="left")
        ttk.Entry(top, textvariable=self.host_var, width=18).pack(side="left", padx=(4, 8))
        ttk.Label(top, text="Port").pack(side="left")
        ttk.Entry(top, textvariable=self.port_var, width=6).pack(side="left", padx=(4, 8))

        ttk.Button(top, text="Connect", command=self.connect_and_list).pack(side="left", padx=2)
        ttk.Button(top, text="Disconnect", command=self.disconnect).pack(side="left", padx=2)
        ttk.Button(top, text="Reboot Xbox", command=self.reboot_xbox).pack(side="left", padx=2)
        ttk.Button(top, text="Drives", command=self.show_root).pack(side="left", padx=2)
        ttk.Checkbutton(top, text="Launch with debug", variable=self.debug_var).pack(side="right")

        pathbar = ttk.Frame(self, padding=(8, 0, 8, 8))
        pathbar.pack(fill="x")
        ttk.Label(pathbar, text="Path").pack(side="left")
        path_entry = ttk.Entry(pathbar, textvariable=self.current_path)
        path_entry.pack(side="left", fill="x", expand=True, padx=4)
        path_entry.bind("<Return>", lambda e: self.refresh())
        ttk.Button(pathbar, text="Up", command=self.go_up).pack(side="left", padx=2)
        ttk.Button(pathbar, text="Refresh", command=self.refresh).pack(side="left", padx=2)

        middle = ttk.Frame(self, padding=(8, 0, 8, 8))
        middle.pack(fill="both", expand=True)

        columns = ("type", "name", "size", "modified")
        self.tree = ttk.Treeview(middle, columns=columns, show="headings", selectmode="extended")
        for col, text, width, anchor in [
            ("type", "Type", 70, "w"),
            ("name", "Name", 600, "w"),
            ("size", "Size", 90, "e"),
            ("modified", "Modified", 160, "w"),
        ]:
            self.tree.heading(col, text=text, command=lambda c=col: self.sort_by(c))
            self.tree.column(col, width=width, anchor=anchor)
        self.tree.pack(side="left", fill="both", expand=True)

        ybar = ttk.Scrollbar(middle, orient="vertical", command=self.tree.yview)
        ybar.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=ybar.set)
        self.tree.bind("<Double-1>", lambda e: self.open_selected())
        self.tree.bind("<Button-3>", self.show_context_menu)
        self.tree.bind("<Button-2>", self.show_context_menu)
        self.tree.bind("<Control-a>", self.select_all)
        self.tree.bind("<Control-A>", self.select_all)
        self.bind_all("<ButtonRelease-1>", self.maybe_close_context_menu, add="+")
        self.bind_all("<Escape>", self.close_context_menu, add="+")

        statusbar = ttk.Frame(self, padding=(8, 0, 8, 8))
        statusbar.pack(fill="x")

        self.progress = ttk.Progressbar(statusbar, mode="determinate", length=240)
        self.progress.pack(side="right", padx=4)
        self.status = tk.StringVar(value="Ready")
        ttk.Label(statusbar, textvariable=self.status).pack(side="left")

        log_frame = ttk.Frame(self, padding=(8, 0, 8, 8))
        log_frame.pack(fill="both")
        self.log_box = tk.Text(log_frame, height=8, wrap="word")
        self.log_box.pack(fill="both", expand=False)

        self.refresh_heading_markers()

    def log(self, msg):
        self.log_box.insert("end", msg + "\n")
        self.log_box.see("end")
        self.status.set(msg)

    def target(self):
        host = self.host_var.get().strip()
        if not host:
            raise XBDMError("Xbox IP is blank. Enter the Xemu/Xbox host IP first.")
        port = int(self.port_var.get().strip() or DEFAULT_PORT)
        return host, port

    def run_bg(self, label, fn, set_status=True):
        self.busy = True
        if set_status:
            self.status.set(label)
        self.progress.configure(value=0, maximum=100)

        def worker():
            try:
                result = fn()
                self.q.put(("ok", label, result))
            except Exception as e:
                self.q.put(("err", label, str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_queue(self):
        try:
            while True:
                kind, label, payload = self.q.get_nowait()
                if kind == "progress":
                    cur, total = payload
                    pct = 0 if total <= 0 else int((cur / total) * 100)
                    self.progress.configure(value=pct)
                    self.status.set(f"{label}: {cur}/{total}")
                elif kind == "ok":
                    self.busy = False
                    self.progress.configure(value=0)
                    if isinstance(payload, tuple) and payload and payload[0] == "connected_dir":
                        self.connected = True
                        self.reconnect_pending = False
                        self.reconnect_attempt = 0
                        self.populate(payload[1])
                    elif isinstance(payload, tuple) and payload and payload[0] == "reconnected_dir":
                        self.connected = True
                        self.reconnect_pending = False
                        self.reconnect_attempt = 0
                        self.current_path.set(payload[1])
                        self.populate(payload[2])
                        self.log(f"Reconnected to {payload[1] or 'drive list'}")
                    elif isinstance(payload, tuple) and payload and payload[0] == "dir":
                        self.connected = True
                        self.populate(payload[1], keep_log=not self.suppress_next_list_log)
                        self.suppress_next_list_log = False
                    elif payload is not None:
                        self.log(str(payload))
                    else:
                        self.log(label + " done")
                elif kind == "err":
                    self.busy = False
                    self.suppress_next_list_log = False
                    self.progress.configure(value=0)

                    if "Reconnect attempt" in label:
                        self.reconnect_pending = False
                        self.log(f"Reconnect failed: {payload}")
                        self.schedule_reconnect("Still disconnected")
                    elif label in ("Auto-refresh", "Refreshing", "Refreshing drives"):
                        self.log(f"Connection lost: {payload}")
                        self.schedule_reconnect("Connection lost")
                    else:
                        self.log("ERROR: " + payload)
                        messagebox.showerror("XBDM error", payload)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def client(self):
        host, port = self.target()

        def progress(cur, total):
            self.q.put(("progress", "transfer", (cur, total)))

        return XBDMClient(host, port, progress=progress)


    def auto_refresh(self):
        try:
            if (
                self.connected
                and not self.busy
                and not self.context_menu_open
                and self.context_menu is None
                and not self.tree.selection()
                and self.host_var.get().strip()
            ):
                self.refresh(silent=True)
        finally:
            self.after(self.auto_refresh_ms, self.auto_refresh)

    def disconnect(self):
        self.manual_disconnect = True
        self.connected = False
        self.reconnect_pending = False
        self.reconnect_attempt = 0
        self.current_path.set("")
        self.tree.selection_remove(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        self.status.set("Disconnected")
        self.log("Disconnected")

    def schedule_reconnect(self, reason="connection lost"):
        if self.manual_disconnect or not self.host_var.get().strip():
            return
        if self.reconnect_pending:
            return

        self.connected = False
        self.reconnect_pending = True
        self.reconnect_attempt += 1
        attempt = self.reconnect_attempt
        self.log(f"{reason}; reconnect attempt {attempt} in {self.reconnect_ms // 1000}s")
        self.after(self.reconnect_ms, self.reconnect_once)

    def reconnect_once(self):
        if self.manual_disconnect or not self.reconnect_pending:
            return

        reconnect_path = xp(self.current_path.get())

        def work():
            with self.client() as c:
                if reconnect_path:
                    try:
                        return ("reconnected_dir", reconnect_path, c.dirlist(reconnect_path))
                    except Exception:
                        drives = c.drivelist()
                        return ("reconnected_dir", "", drive_entries_from_drivelist(drives))

                drives = c.drivelist()
                return ("reconnected_dir", "", drive_entries_from_drivelist(drives))

        self.run_bg(f"Reconnect attempt {self.reconnect_attempt}", work)

    def connect_and_list(self):
        self.manual_disconnect = False
        self.reconnect_pending = False
        self.reconnect_attempt = 0
        self.save_config()

        def work():
            with self.client() as c:
                drives = c.drivelist()
            return ("connected_dir", drive_entries_from_drivelist(drives))

        self.current_path.set("")
        self.run_bg("Connecting", work)

    def show_root(self):
        self.connect_and_list()

    def refresh(self, silent=False):
        if silent:
            self.suppress_next_list_log = True

        path = xp(self.current_path.get())
        self.current_path.set(path)

        if not path:
            if not self.connected:
                self.connect_and_list()
                return

            def work_root():
                with self.client() as c:
                    drives = c.drivelist()
                return ("dir", drive_entries_from_drivelist(drives))

            self.run_bg(("Refreshing drives" if not silent else "Auto-refresh"), work_root, set_status=not silent)
            return

        def work():
            with self.client() as c:
                return ("dir", c.dirlist(path))

        self.run_bg(("Refreshing" if not silent else "Auto-refresh"), work, set_status=not silent)

    def sort_key(self, entry, column):
        if column == "type":
            return "0" if entry.get("is_dir") else "1"
        if column == "name":
            return entry.get("name", "").lower()
        if column == "size":
            return entry.get("size", 0)
        if column == "modified":
            return entry.get("changed", "")
        return entry.get("name", "").lower()

    def refresh_heading_markers(self):
        labels = {"type": "Type", "name": "Name", "size": "Size", "modified": "Modified"}
        column = self.sort_state.get("column", "name")
        descending = self.sort_state.get("descending", False)
        for col, label in labels.items():
            marker = ""
            if col == column:
                marker = " ▼" if descending else " ▲"
            self.tree.heading(col, text=label + marker, command=lambda c=col: self.sort_by(c))

    def sort_by(self, column):
        if self.sort_state.get("column") == column:
            self.sort_state["descending"] = not self.sort_state.get("descending", False)
        else:
            self.sort_state["column"] = column
            self.sort_state["descending"] = False
        self.populate(self.current_entries, keep_log=False)

    def populate(self, entries, keep_log=True):
        self.current_entries = list(entries)
        self.tree.delete(*self.tree.get_children())

        column = self.sort_state.get("column", "name")
        descending = self.sort_state.get("descending", False)

        sorted_entries = sorted(
            self.current_entries,
            key=lambda e: (not e.get("is_dir", False), self.sort_key(e, column))
        )
        if descending:
            sorted_entries = list(reversed(sorted_entries))

        self.refresh_heading_markers()

        for e in sorted_entries:
            name = e.get("name", "")
            typ = "<DIR>" if e.get("is_dir") else "FILE"
            size = "" if e.get("is_dir") else human_size(e.get("size", 0))
            modified = e.get("changed", "")
            item_id = self.tree.insert("", "end", values=(typ, name, size, modified))
            self.tree.item(item_id, tags=("dir" if e.get("is_dir") else "file",))

        if keep_log:
            self.log(f"Listed {self.current_path.get() or 'Root'}")

    def select_all(self, event=None):
        self.tree.selection_set(self.tree.get_children())
        return "break"

    def item_name_and_type(self, item_id):
        vals = self.tree.item(item_id, "values")
        if not vals:
            return None, None
        return vals[1], vals[0]

    def item_remote_path(self, item_id):
        name, typ = self.item_name_and_type(item_id)
        if not name:
            return None, None
        if self.current_path.get() == "":
            return name, typ
        return rjoin(self.current_path.get(), name), typ

    def selected_items(self):
        items = []
        for item_id in self.tree.selection():
            remote, typ = self.item_remote_path(item_id)
            if remote:
                items.append((remote, typ))
        return items

    def selected_name_and_type(self):
        sel = self.tree.selection()
        if not sel:
            return None, None
        return self.item_name_and_type(sel[0])

    def selected_remote_path(self):
        sel = self.tree.selection()
        if not sel:
            return None, None
        return self.item_remote_path(sel[0])

    def open_selected(self):
        items = self.selected_items()
        if len(items) != 1:
            return

        path, typ = items[0]
        if typ == "<DIR>":
            self.current_path.set(path)
            self.refresh()
        elif path.lower().endswith(".xbe"):
            self.launch_path(path)

    def go_up(self):
        self.current_path.set(remote_parent(self.current_path.get()))
        self.refresh()

    def download_remote_tree(self, client, remote_dir, local_dir):
        local_dir = Path(local_dir)
        local_dir.mkdir(parents=True, exist_ok=True)

        for entry in client.dirlist(remote_dir):
            name = entry.get("name", "")
            if not name:
                continue
            remote_child = entry.get("path") or rjoin(remote_dir, name)
            local_child = local_dir / name

            if entry.get("is_dir"):
                self.download_remote_tree(client, remote_child, local_child)
            else:
                client.get(remote_child, str(local_child))

    def upload_local_tree(self, client, local_dir, remote_parent):
        local_dir = Path(local_dir)
        remote_root = rjoin(remote_parent, local_dir.name)
        client.mkdir_if_missing(remote_root)

        for dirpath, _, files in os.walk(local_dir):
            d = Path(dirpath)
            rel = d.relative_to(local_dir)
            remote_current = remote_root if str(rel) == "." else rjoin(remote_root, *rel.parts)
            client.mkdir_if_missing(remote_current)

            for name in files:
                local_file = d / name
                remote_file = rjoin(remote_current, name)
                client.put(str(local_file), remote_file)

    def download(self):
        items = self.selected_items()
        if not items:
            return

        local_dir = filedialog.askdirectory(title="Choose download folder")
        if not local_dir:
            return

        def work():
            with self.client() as c:
                for remote, typ in items:
                    local_target = str(Path(local_dir) / remote_basename(remote))
                    if typ == "<DIR>":
                        self.download_remote_tree(c, remote, local_target)
                    else:
                        c.get(remote, local_target)

            if len(items) == 1:
                remote, typ = items[0]
                return f"Downloaded {remote} -> {Path(local_dir) / remote_basename(remote)}"
            return f"Downloaded {len(items)} items -> {local_dir}"

        self.run_bg("Downloading", work)

    def upload(self, target_dir=None):
        current = target_dir or self.current_path.get()
        if not current:
            messagebox.showinfo("Upload", "Open a drive/folder before uploading.")
            return

        choice = tk.StringVar(value="")

        dlg = tk.Toplevel(self)
        dlg.title("Upload")
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()

        frame = ttk.Frame(dlg, padding=14)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="What do you want to upload?").pack(anchor="w", pady=(0, 10))

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")

        def choose(value):
            choice.set(value)
            dlg.destroy()

        ttk.Button(buttons, text="File", command=lambda: choose("file")).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Folder", command=lambda: choose("folder")).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Cancel", command=lambda: choose("")).pack(side="left")

        dlg.bind("<Escape>", lambda e: choose(""))
        dlg.update_idletasks()

        x = self.winfo_rootx() + (self.winfo_width() // 2) - (dlg.winfo_width() // 2)
        y = self.winfo_rooty() + (self.winfo_height() // 2) - (dlg.winfo_height() // 2)
        dlg.geometry(f"+{x}+{y}")

        self.wait_window(dlg)

        if choice.get() == "file":
            self.upload_file(current)
        elif choice.get() == "folder":
            self.upload_folder(current)

    def upload_file(self, target_dir=None):
        current = target_dir or self.current_path.get()
        if not current:
            messagebox.showinfo("Upload file", "Open a drive/folder before uploading.")
            return
        local = filedialog.askopenfilename(title="Upload file to Xbox")
        if not local:
            return
        dest = rjoin(current, Path(local).name)

        def work():
            with self.client() as c:
                c.put(local, dest)
            return f"Uploaded {local} -> {dest}"
        self.run_bg("Uploading", work)
        self.after(800, self.refresh)

    def upload_folder(self, target_dir=None):
        current = target_dir or self.current_path.get()
        if not current:
            messagebox.showinfo("Upload folder", "Open a drive/folder before uploading.")
            return

        picker = FolderPicker(self, title="Upload folder to Xbox")
        self.wait_window(picker)
        local = picker.selected_path

        if not local:
            return

        remote_root = rjoin(current, Path(local).name)

        def work():
            with self.client() as c:
                self.upload_local_tree(c, local, current)
            return f"Uploaded folder {local} -> {remote_root}"
        self.run_bg("Uploading folder", work)
        self.after(800, self.refresh)

    def mkdir(self, parent_dir=None):
        current = parent_dir or self.current_path.get()
        if not current:
            messagebox.showinfo("Create folder", "Open a drive/folder before creating a folder.")
            return
        name = simpledialog.askstring("Create folder", "Folder name:")
        if not name:
            return
        remote = rjoin(current, name)

        def work():
            with self.client() as c:
                c.mkdir(remote)
            return f"Created {remote}"
        self.run_bg("Mkdir", work)
        self.after(800, self.refresh)


    def rename_selected(self):
        items = self.selected_items()
        if len(items) != 1:
            messagebox.showinfo("Rename", "Select exactly one item to rename.")
            return

        remote, typ = items[0]
        old_name = remote_basename(remote)
        new_name = simpledialog.askstring("Rename", "New name:", initialvalue=old_name)
        if not new_name or new_name == old_name:
            return

        new_remote = rjoin(remote_parent(remote), new_name)

        def work():
            with self.client() as c:
                c.rename(remote, new_remote)
            return f"Renamed {remote} -> {new_remote}"

        self.run_bg("Rename", work)
        self.after(800, self.refresh)

    def delete_remote_tree(self, client, remote_dir):
        # XBDM can only delete empty folders, so delete children first.
        entries = client.dirlist(remote_dir)
        for entry in entries:
            name = entry.get("name", "")
            if not name:
                continue

            child = entry.get("path") or rjoin(remote_dir, name)
            if entry.get("is_dir"):
                self.delete_remote_tree(client, child)
                client.delete(child, is_dir=True)
            else:
                client.delete(child, is_dir=False)

    def delete(self):
        items = self.selected_items()
        if not items:
            return

        if len(items) == 1:
            remote, typ = items[0]
            item_kind = "folder" if typ == "<DIR>" else "file"
            message = f"Are you sure you want to permanently delete this {item_kind}?"
        else:
            message = f"Are you sure you want to permanently delete these {len(items)} items?"

        if not messagebox.askyesno("Confirm delete", message):
            return

        def work():
            with self.client() as c:
                for remote, typ in items:
                    if typ == "<DIR>":
                        self.delete_remote_tree(c, remote)
                        c.delete(remote, is_dir=True)
                    else:
                        c.delete(remote, is_dir=False)

            if len(items) == 1:
                return f"Deleted {items[0][0]}"
            return f"Deleted {len(items)} items"

        self.run_bg("Delete", work)
        self.after(800, self.refresh)

    def reboot_xbox(self):
        if not messagebox.askyesno("Reboot Xbox", "Reboot the Xbox now?"):
            return

        self.connected = False

        def work():
            with self.client() as c:
                result = c.reboot()
            return f"Reboot Xbox: {result}"

        self.run_bg("Reboot Xbox", work)
        self.schedule_reconnect("Xbox rebooting")


    def launch_selected(self):
        items = self.selected_items()
        if len(items) != 1:
            messagebox.showinfo("Launch XBE", "Select exactly one .xbe file.")
            return

        remote, typ = items[0]
        if typ == "<DIR>" or not remote.lower().endswith(".xbe"):
            messagebox.showinfo("Launch XBE", "Select an .xbe file.")
            return
        self.launch_path(remote)

    def launch_path(self, remote):
        def work():
            with self.client() as c:
                result = c.launch(remote, debug=self.debug_var.get())
            return f"Launched {remote}: {result}"
        self.run_bg("Launching", work)

    def copy_path_to_clipboard(self, path):
        self.clipboard_clear()
        self.clipboard_append(path)
        self.log(f"Copied path: {path}")

    def close_context_menu(self, event=None):
        if self.context_menu is not None:
            try:
                self.context_menu.unpost()
            except Exception:
                pass
            self.context_menu = None
        self.context_menu_open = False

    def maybe_close_context_menu(self, event=None):
        if not self.context_menu_open or self.context_menu is None:
            return
        if event is not None and isinstance(getattr(event, "widget", None), tk.Menu):
            return
        self.close_context_menu()

    def menu_action(self, callback):
        def wrapped():
            self.close_context_menu()
            callback()
        return wrapped

    def show_context_menu(self, event):
        self.close_context_menu()

        row = self.tree.identify_row(event.y)
        menu = tk.Menu(self, tearoff=0)
        self.context_menu = menu
        self.context_menu_open = True

        if row:
            current_selection = set(self.tree.selection())
            if row not in current_selection:
                self.tree.selection_set(row)

            items = self.selected_items()

            if len(items) > 1:
                menu.add_command(label="Download", command=self.menu_action(self.download))
                menu.add_command(label="Delete", command=self.menu_action(self.delete))
            else:
                remote, typ = items[0]

                if typ == "<DIR>":
                    menu.add_command(label="Open", command=self.menu_action(self.open_selected))
                    menu.add_command(label="Download", command=self.menu_action(self.download))
                    menu.add_command(label="Rename", command=self.menu_action(self.rename_selected))
                    menu.add_separator()
                    menu.add_command(label="Delete", command=self.menu_action(self.delete))
                else:
                    if remote and remote.lower().endswith(".xbe"):
                        menu.add_command(label="Launch XBE", command=self.menu_action(lambda: self.launch_path(remote)))
                        menu.add_separator()
                    menu.add_command(label="Download", command=self.menu_action(self.download))
                    menu.add_command(label="Rename", command=self.menu_action(self.rename_selected))
                    menu.add_command(label="Delete", command=self.menu_action(self.delete))
        else:
            self.tree.selection_remove(self.tree.selection())
            current = self.current_path.get()
            if current:
                menu.add_command(label="Upload", command=self.menu_action(lambda: self.upload(current)))
                menu.add_command(label="New folder", command=self.menu_action(lambda: self.mkdir(current)))
                menu.add_separator()
            menu.add_command(label="Refresh", command=self.menu_action(self.refresh))

        menu.post(event.x_root, event.y_root)


if __name__ == "__main__":
    app = XBDMGui()
    app.protocol("WM_DELETE_WINDOW", lambda: (setattr(app, "manual_disconnect", True), app.destroy()))
    app.mainloop()
