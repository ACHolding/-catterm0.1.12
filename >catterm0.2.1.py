#!/usr/bin/env python3
"""catterm 0.2.1 — Windows Terminal Replica with LM Studio AI Agent"""

import re, os, json, subprocess, threading, sys, webbrowser
import tkinter as tk
from tkinter import font as tkfont, ttk, simpledialog, messagebox
from urllib.request import Request, urlopen
from urllib.error import URLError
from datetime import datetime
from collections import OrderedDict

try:
    import pyperclip
except ImportError:
    pyperclip = None

# ── Configuration ──────────────────────────────────────────────────────────────
LM_STUDIO_URL = os.environ.get("LM_STUDIO_URL", "http://localhost:1234/v1")
LM_STUDIO_MODEL = os.environ.get("LM_STUDIO_MODEL", "")

FONT = "Cascadia Code"
SZ = 12
SM = 11
TNY = 10

TERM_BG = "#0C0C0C"
TAB_BG = "#1F1F1F"
ACTIVE_BG = "#333333"
HOVER_BG = "#2D2D2D"
SURFACE = "#1A1A1A"
BORDER = "#404040"
TEXT_PRI = "#FFFFFF"
TEXT_SEC = "#A3A3A3"
TEXT_MUT = "#5A5A5A"
ACCENT = "#6C8CFF"
ACCENT_HOVER = "#8CA8FF"
PURPLE = "#BB9AF7"
CMD_BG = "#151518"
SCROLL_FG = "#424242"
SCROLL_BG = "#2A2A2A"
ERROR_RED = "#FF6B6B"
SUCCESS_GREEN = "#7ECB8E"
ORANGE = "#FFB86C"
PANEL_BG = "#2D2D30"
PANEL_BORDER = "#3E3E42"
TITLE_BAR_BG = "#1F1F1F"

COLORS = OrderedDict([
    ("Campbell", ["#0C0C0C","#C50F1F","#13A10E","#C19C00","#0037DA","#881798","#3A96DD","#CCCCCC","#767676","#E74856","#16C60C","#F9F1A5","#3B78FF","#B4009E","#61D6D6","#F2F2F2"]),
    ("One Half Dark", ["#1E1E1E","#E06C75","#98C379","#E5C07B","#61AFEF","#C678DD","#56B6C2","#ABB2BF","#5C6370","#E06C75","#98C379","#E5C07B","#61AFEF","#C678DD","#56B6C2","#ABB2BF"]),
    ("Solarized Dark", ["#073642","#DC322F","#859900","#B58900","#268BD2","#D33682","#2AA198","#EEE8D5","#002B36","#CB4B16","#586E75","#657B83","#839496","#6C71C4","#93A1A1","#FDF6E3"]),
    ("Tango", ["#000000","#CC0000","#4E9A06","#C4A000","#3465A4","#75507B","#06989A","#D3D7CF","#555753","#EF2929","#8AE234","#FCE94F","#729FCF","#AD7FA8","#34E2E2","#EEEEEC"]),
    ("Nord", ["#2E3440","#BF616A","#A3BE8C","#EBCB8B","#81A1C1","#B48EAD","#88C0D0","#E5E9F0","#4C566A","#BF616A","#A3BE8C","#EBCB8B","#81A1C1","#B48EAD","#8FBCBB","#ECEFF4"]),
])
THEMES = list(COLORS.keys())
CURRENT_THEME = "One Half Dark"
TRANSPARENCY = 0

AGENT_PROMPT = """You are catterm AI agent integrated into a Windows Terminal replica.
You have full shell access via ```bash blocks.

RULES:
- Answer concisely and conversationally.
- To run shell commands, output them in ```bash code blocks.
- After seeing results, continue the conversation — explain output or suggest next steps.
- Use markdown formatting for readability.
- Be helpful, proactive, and security-conscious.
- Never refuse a reasonable request."""

# ── Utilities ──────────────────────────────────────────────────────────────────

def lm_studio_request(messages, model=None, temperature=0.5):
    payload = {
        "messages": messages,
        "temperature": temperature,
        "max_tokens": -1,
        "stream": False,
    }
    if model:
        payload["model"] = model
    try:
        data = json.dumps(payload).encode("utf-8")
        req = Request(
            f"{LM_STUDIO_URL}/chat/completions",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(req, timeout=180) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return result["choices"][0]["message"]["content"]
    except URLError as e:
        return f"Error: Cannot reach LM Studio at {LM_STUDIO_URL}\n{e.reason}"
    except (KeyError, json.JSONDecodeError) as e:
        return f"Error: LM Studio response parse failed\n{e}"
    except Exception as e:
        return f"Error: {e}"

def check_lm_studio():
    try:
        req = Request(f"{LM_STUDIO_URL}/models", method="GET")
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [m["id"] for m in data.get("data", [])]
    except Exception:
        return None

def run_shell(cmd):
    try:
        r = subprocess.run(
            ["/bin/sh", "-c", cmd],
            capture_output=True, text=True, timeout=300,
        )
        parts = []
        if r.stdout:
            parts.append(r.stdout.rstrip("\n"))
        if r.stderr:
            parts.append(r.stderr.rstrip("\n"))
        if r.returncode != 0:
            parts.append(f"Exit: {r.returncode}")
        return "\n".join(parts) if parts else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: command timed out (300s)"
    except Exception as e:
        return f"Error: {e}"

def extract_bash_blocks(text):
    return [b.strip() for b in re.findall(r"```(?:bash|sh|shell)?\n(.*?)```", text, re.DOTALL) if b.strip()]

def parse_markdown_inline(text):
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return text

CONFIG_FILE = os.path.expanduser("~/.catterm_config.json")

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass

# ── Split Pane ─────────────────────────────────────────────────────────────────

class SplitPane:
    VERTICAL = "vertical"
    HORIZONTAL = "horizontal"

    def __init__(self, parent, bg=TERM_BG, orientation=VERTICAL):
        self.parent = parent
        self.bg = bg
        self.orientation = orientation
        self.children = []
        self.sash_pos = 0.5
        self.sash_frame = None
        self.frame = tk.Frame(parent, bg=bg)
        self._dragging = False
        self._build()

    def _build(self):
        for w in self.frame.winfo_children():
            w.destroy()
        self.children.clear()

        if not self.sash_frame:
            self.sash_frame = tk.Frame(self.frame, bg=BORDER)
            self.sash_frame.bind("<Button-1>", self._drag_start)
            self.sash_frame.bind("<B1-Motion>", self._drag_move)
            self.sash_frame.bind("<ButtonRelease-1>", self._drag_stop)

        self._layout()

    def _layout(self):
        for w in self.frame.winfo_children():
            w.pack_forget()

        if len(self.children) == 0:
            return

        if len(self.children) == 1:
            self.children[0].pack(fill=tk.BOTH, expand=True)
            return

        is_v = self.orientation == self.VERTICAL
        sash_size = 4

        if is_v:
            self.children[0].pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
            self.sash_frame.configure(width=sash_size, cursor="sb_h_double_arrow")
            self.sash_frame.pack(fill=tk.Y, side=tk.LEFT)
            self.children[1].pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        else:
            self.children[0].pack(fill=tk.BOTH, expand=True, side=tk.TOP)
            self.sash_frame.configure(height=sash_size, cursor="sb_v_double_arrow")
            self.sash_frame.pack(fill=tk.X, side=tk.TOP)
            self.children[1].pack(fill=tk.BOTH, expand=True, side=tk.TOP)

        total = self.frame.winfo_width() or 800
        if is_v:
            pos = int(total * self.sash_pos)
            self.frame.update_idletasks()
            self.frame.pack_propagate(False)
        else:
            total = self.frame.winfo_height() or 600
            pos = int(total * self.sash_pos)
            self.frame.update_idletasks()
            self.frame.pack_propagate(False)

    def _drag_start(self, e):
        self._dragging = True
        self._start_pos = e.x_root if self.orientation == self.VERTICAL else e.y_root

    def _drag_move(self, e):
        if not self._dragging:
            return
        is_v = self.orientation == self.VERTICAL
        total = self.frame.winfo_width() if is_v else self.frame.winfo_height()
        if total <= 0:
            return
        delta = (e.x_root if is_v else e.y_root) - self._start_pos
        new_pos = self.sash_pos + delta / total
        self.sash_pos = max(0.2, min(0.8, new_pos))
        self._start_pos = e.x_root if is_v else e.y_root
        self._apply_weights()

    def _drag_stop(self, e):
        self._dragging = False

    def _apply_weights(self):
        is_v = self.orientation == self.VERTICAL
        total = self.frame.winfo_width() if is_v else self.frame.winfo_height()
        if total <= 0:
            return
        w0 = int(total * self.sash_pos)
        w1 = total - w0 - 4
        if w0 < 50 or w1 < 50:
            return
        if is_v:
            self.children[0].pack_forget()
            self.sash_frame.pack_forget()
            self.children[1].pack_forget()
            self.children[0].pack(fill=tk.BOTH, side=tk.LEFT)
            self.sash_frame.pack(fill=tk.Y, side=tk.LEFT)
            self.children[1].pack(fill=tk.BOTH, side=tk.LEFT, expand=True)
            self.frame.update_idletasks()
        else:
            self.children[0].pack_forget()
            self.sash_frame.pack_forget()
            self.children[1].pack_forget()
            self.children[0].pack(fill=tk.BOTH, side=tk.TOP)
            self.sash_frame.pack(fill=tk.X, side=tk.TOP)
            self.children[1].pack(fill=tk.BOTH, side=tk.TOP, expand=True)
            self.frame.update_idletasks()

    def add_child(self, child):
        if len(self.children) >= 2:
            return False
        self.children.append(child)
        self._layout()
        return True

    def remove_child(self, child):
        if child in self.children:
            self.children.remove(child)
            child.pack_forget()
            self._layout()
            return True
        return False

    def pack(self, **kwargs):
        self.frame.pack(**kwargs)

    def pack_forget(self):
        self.frame.pack_forget()

    def destroy(self):
        self.frame.destroy()

# ── Search Dialog ──────────────────────────────────────────────────────────────

class SearchDialog:
    def __init__(self, parent, text_widget, callback=None):
        self.text = text_widget
        self.callback = callback
        self.win = tk.Toplevel(parent)
        self.win.title("Find")
        self.win.configure(bg=ACTIVE_BG)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)

        frame = tk.Frame(self.win, bg=ACTIVE_BG, bd=1, relief=tk.SOLID, highlightbackground=BORDER, highlightthickness=1)
        frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        row = tk.Frame(frame, bg=ACTIVE_BG)
        row.pack(fill=tk.X, padx=6, pady=6)

        tk.Label(row, text="Find:", bg=ACTIVE_BG, fg=TEXT_PRI, font=(FONT, TNY)).pack(side=tk.LEFT)
        self.entry = tk.Entry(row, bg=SURFACE, fg=TEXT_PRI, insertbackground=TEXT_PRI,
                              font=(FONT, SM), relief=tk.FLAT, bd=0, highlightthickness=1,
                              highlightbackground=BORDER, highlightcolor=ACCENT)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0), ipady=2)
        self.entry.focus_set()
        self.entry.bind("<Return>", lambda e: self._search())
        self.entry.bind("<Escape>", lambda e: self._close())

        btn_frame = tk.Frame(frame, bg=ACTIVE_BG)
        btn_frame.pack(fill=tk.X, padx=6, pady=(0, 6))

        self.case_var = tk.BooleanVar(value=False)
        tk.Checkbutton(btn_frame, text="Match case", variable=self.case_var,
                       bg=ACTIVE_BG, fg=TEXT_SEC, selectcolor=ACTIVE_BG,
                       font=(FONT, TNY), activebackground=ACTIVE_BG, activeforeground=TEXT_PRI).pack(side=tk.LEFT)

        self.wrap_var = tk.BooleanVar(value=True)
        tk.Checkbutton(btn_frame, text="Wrap", variable=self.wrap_var,
                       bg=ACTIVE_BG, fg=TEXT_SEC, selectcolor=ACTIVE_BG,
                       font=(FONT, TNY), activebackground=ACTIVE_BG, activeforeground=TEXT_PRI).pack(side=tk.LEFT, padx=(6, 0))

        self.prev_btn = tk.Label(btn_frame, text="▲", bg=ACTIVE_BG, fg=TEXT_SEC,
                                 font=(FONT, TNY), cursor="hand2")
        self.prev_btn.pack(side=tk.RIGHT, padx=(2, 0))
        self.prev_btn.bind("<Button-1>", lambda e: self._search(backward=True))

        self.next_btn = tk.Label(btn_frame, text="▼", bg=ACTIVE_BG, fg=TEXT_SEC,
                                 font=(FONT, TNY), cursor="hand2")
        self.next_btn.pack(side=tk.RIGHT, padx=(2, 0))
        self.next_btn.bind("<Button-1>", lambda e: self._search(backward=False))

        self.status = tk.Label(frame, text="", bg=ACTIVE_BG, fg=TEXT_MUT, font=(FONT, TNY))
        self.status.pack(fill=tk.X, padx=6, pady=(0, 4))

        self._matches = []
        self._current = -1
        self._search()

    def _search(self, backward=False):
        query = self.entry.get()
        if not query:
            self._clear_highlights()
            self._matches = []
            self.status.configure(text="")
            return

        self._clear_highlights()
        self._matches = []

        content = self.text.get("1.0", tk.END)
        flags = 0 if self.case_var.get() else re.IGNORECASE
        start = 1.0

        while True:
            idx = self.text.search(query, start, tk.END, nocase=not self.case_var.get(), regexp=False)
            if not idx:
                break
            end = f"{idx}+{len(query)}c"
            self._matches.append((idx, end))
            self.text.tag_add("search_match", idx, end)
            self.text.tag_configure("search_match", background="#5A5A5A", foreground=TEXT_PRI)
            start = end

        if not self._matches:
            self.status.configure(text="No results")
            return

        if backward:
            self._current = (self._current - 1) % len(self._matches)
        else:
            self._current = (self._current + 1) % len(self._matches)

        idx, end = self._matches[self._current]
        self.text.see(idx)
        self.text.tag_remove("search_current", "1.0", tk.END)
        self.text.tag_add("search_current", idx, end)
        self.text.tag_configure("search_current", background=ACCENT, foreground="#000000")

        self.status.configure(text=f"{self._current + 1} of {len(self._matches)}")

    def _clear_highlights(self):
        self.text.tag_remove("search_match", "1.0", tk.END)
        self.text.tag_remove("search_current", "1.0", tk.END)

    def _close(self):
        self._clear_highlights()
        self.win.destroy()
        if self.callback:
            self.callback()

# ── Command Palette ────────────────────────────────────────────────────────────

class CommandPalette:
    def __init__(self, parent, app):
        self.app = app
        self.win = tk.Toplevel(parent)
        self.win.title("Command Palette")
        self.win.configure(bg=ACTIVE_BG)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)

        frame = tk.Frame(self.win, bg=ACTIVE_BG, bd=1, relief=tk.SOLID, highlightbackground=BORDER, highlightthickness=1)
        frame.pack(fill=tk.BOTH, expand=True)

        self.entry = tk.Entry(frame, bg=SURFACE, fg=TEXT_PRI, insertbackground=TEXT_PRI,
                              font=(FONT, SM), relief=tk.FLAT, bd=0, highlightthickness=0)
        self.entry.pack(fill=tk.X, padx=6, pady=(6, 2), ipady=4)
        self.entry.focus_set()
        self.entry.bind("<KeyRelease>", self._filter)
        self.entry.bind("<Escape>", lambda e: self._close())
        self.entry.bind("<Return>", lambda e: self._execute())
        self.entry.bind("<Up>", lambda e: self._move(-1))
        self.entry.bind("<Down>", lambda e: self._move(1))

        self.listbox = tk.Listbox(frame, bg=SURFACE, fg=TEXT_PRI, selectbackground=ACCENT,
                                  selectforeground="#000000", font=(FONT, SM),
                                  relief=tk.FLAT, bd=0, highlightthickness=0,
                                  activestyle="none", height=10)
        scroll = tk.Scrollbar(frame, bg=SURFACE, troughcolor=SURFACE, activebackground=SCROLL_FG,
                              command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scroll.set)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0), pady=(2, 6))
        scroll.pack(side=tk.RIGHT, fill=tk.Y, pady=(2, 6))
        self.listbox.bind("<Double-Button-1>", lambda e: self._execute())
        self.listbox.bind("<Button-1>", lambda e: self.listbox.focus_set())

        self.commands = [
            ("Close Tab", lambda: self.app._close_active_tab()),
            ("New Tab", lambda: self.app._new_tab()),
            ("Split Vertical", lambda: self.app._split_vertical()),
            ("Split Horizontal", lambda: self.app._split_horizontal()),
            ("Close Pane", lambda: self.app._close_pane()),
            ("Search", lambda: self.app._open_search()),
            ("Toggle Transparency", lambda: self.app._toggle_transparency()),
            ("Toggle Fullscreen", lambda: self.app._toggle_fullscreen()),
            ("Color Scheme → Nord", lambda: self.app._set_theme("Nord")),
            ("Color Scheme → Campbell", lambda: self.app._set_theme("Campbell")),
            ("Color Scheme → One Half Dark", lambda: self.app._set_theme("One Half Dark")),
            ("Color Scheme → Solarized Dark", lambda: self.app._set_theme("Solarized Dark")),
            ("Color Scheme → Tango", lambda: self.app._set_theme("Tango")),
            ("Settings", lambda: self.app._open_settings()),
            ("About", lambda: self.app._show_about()),
        ]
        self._filtered = list(self.commands)
        self._selected = 0
        self._populate()

    def _populate(self):
        self.listbox.delete(0, tk.END)
        for name, _ in self._filtered:
            self.listbox.insert(tk.END, name)
        if self._filtered:
            self.listbox.selection_set(0)
            self.listbox.activate(0)

    def _filter(self, e=None):
        q = self.entry.get().lower()
        self._filtered = [(n, c) for n, c in self.commands if q in n.lower()]
        self._selected = 0
        self._populate()

    def _move(self, delta):
        if not self._filtered:
            return
        self._selected = (self._selected + delta) % len(self._filtered)
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(self._selected)
        self.listbox.activate(self._selected)
        self.listbox.see(self._selected)

    def _execute(self):
        if not self._filtered:
            return
        idx = self.listbox.curselection()
        if not idx:
            idx = (0,)
        _, cmd = self._filtered[idx[0]]
        self._close()
        cmd()

    def _close(self):
        self.win.destroy()

# ── Settings Panel ─────────────────────────────────────────────────────────────

class SettingsPanel:
    def __init__(self, parent, app):
        self.app = app
        self.win = tk.Toplevel(parent)
        self.win.title("Settings")
        self.win.configure(bg=PANEL_BG)
        self.win.geometry("700x500")
        self.win.minsize(500, 400)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background=SURFACE, foreground=TEXT_PRI, fieldbackground=SURFACE, borderwidth=0)
        style.configure("Treeview.Heading", background=ACTIVE_BG, foreground=TEXT_PRI, borderwidth=1, relief=tk.FLAT)
        style.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "#000000")])

        main = tk.Frame(self.win, bg=PANEL_BG)
        main.pack(fill=tk.BOTH, expand=True)

        nav = tk.Frame(main, bg=PANEL_BG, width=180)
        nav.pack(side=tk.LEFT, fill=tk.Y)
        nav.pack_propagate(False)

        sep = tk.Frame(main, bg=PANEL_BORDER, width=1)
        sep.pack(side=tk.LEFT, fill=tk.Y)

        self.content = tk.Frame(main, bg=PANEL_BG)
        self.content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        nav_items = ["General", "Appearance", "Profiles", "AI Agent", "About"]
        self.nav_btns = []
        for item in nav_items:
            btn = tk.Label(nav, text=item, bg=PANEL_BG, fg=TEXT_SEC, font=(FONT, SM),
                           cursor="hand2", padx=16, pady=8, anchor="w")
            btn.pack(fill=tk.X)
            btn.bind("<Button-1>", lambda e, i=item: self._show_section(i))
            btn.bind("<Enter>", lambda e, b=btn: b.configure(bg=ACTIVE_BG) if b.cget("bg") != ACCENT else None)
            btn.bind("<Leave>", lambda e, b=btn: b.configure(bg=PANEL_BG) if b.cget("bg") != ACCENT else None)
            self.nav_btns.append(btn)

        self._show_section("General")

    def _clear_content(self):
        for w in self.content.winfo_children():
            w.destroy()
        for b in self.nav_btns:
            b.configure(bg=PANEL_BG, fg=TEXT_SEC)

    def _highlight_nav(self, name):
        for b in self.nav_btns:
            if b.cget("text") == name:
                b.configure(bg=ACCENT, fg="#000000")
            else:
                b.configure(bg=PANEL_BG, fg=TEXT_SEC)

    def _make_row(self, parent, label, widget, desc=None):
        row = tk.Frame(parent, bg=PANEL_BG)
        row.pack(fill=tk.X, padx=16, pady=6)
        lbl = tk.Label(row, text=label, bg=PANEL_BG, fg=TEXT_PRI, font=(FONT, SM), anchor="w", width=20)
        lbl.pack(side=tk.LEFT)
        widget.pack(side=tk.LEFT, padx=(8, 0))
        if desc:
            d = tk.Label(parent, text=desc, bg=PANEL_BG, fg=TEXT_MUT, font=(FONT, TNY), anchor="w", padx=(200, 0))
            d.pack(fill=tk.X, padx=16, pady=(0, 4))

    def _show_section(self, name):
        self._clear_content()
        self._highlight_nav(name)

        scroll_c = tk.Frame(self.content, bg=PANEL_BG)
        scroll_c.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(scroll_c, bg=PANEL_BG, highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(scroll_c, bg=SURFACE, troughcolor=SURFACE, activebackground=SCROLL_FG, command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg=PANEL_BG)
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        sec = tk.Frame(scroll_frame, bg=PANEL_BG)
        sec.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        tk.Label(sec, text=name, bg=PANEL_BG, fg=TEXT_PRI, font=(FONT, SZ, "bold"),
                 anchor="w").pack(fill=tk.X, padx=16, pady=(16, 8))

        if name == "General":
            tk.Label(sec, text="Startup", bg=PANEL_BG, fg=TEXT_SEC, font=(FONT, SM, "bold"),
                     anchor="w").pack(fill=tk.X, padx=16, pady=(8, 4))

            def on_start_cfg():
                cfg = load_config()
                cfg["launch_on_startup"] = start_var.get()
                save_config(cfg)
            start_var = tk.BooleanVar(value=load_config().get("launch_on_startup", False))
            cb = tk.Checkbutton(sec, text="Launch on startup", variable=start_var, command=on_start_cfg,
                                bg=PANEL_BG, fg=TEXT_PRI, selectcolor=PANEL_BG, font=(FONT, SM),
                                activebackground=PANEL_BG, activeforeground=TEXT_PRI)
            cb.pack(anchor="w", padx=16, pady=4)

            def on_cwd_cfg():
                cfg = load_config()
                cfg["default_cwd"] = cwd_var.get()
                save_config(cfg)
            tk.Label(sec, text="Default directory", bg=PANEL_BG, fg=TEXT_PRI, font=(FONT, SM),
                     anchor="w").pack(fill=tk.X, padx=16, pady=(8, 2))
            cwd_var = tk.StringVar(value=load_config().get("default_cwd", os.path.expanduser("~")))
            cwd_e = tk.Entry(sec, textvariable=cwd_var, bg=SURFACE, fg=TEXT_PRI,
                             font=(FONT, SM), relief=tk.FLAT, bd=0, highlightthickness=1,
                             highlightbackground=BORDER, highlightcolor=ACCENT)
            cwd_e.pack(fill=tk.X, padx=16, ipady=3)
            cwd_e.bind("<KeyRelease>", lambda e: on_cwd_cfg())

        elif name == "Appearance":
            tk.Label(sec, text="Color scheme", bg=PANEL_BG, fg=TEXT_PRI, font=(FONT, SM),
                     anchor="w").pack(fill=tk.X, padx=16, pady=(8, 2))
            theme_var = tk.StringVar(value=CURRENT_THEME)
            theme_menu = ttk.Combobox(sec, textvariable=theme_var, values=THEMES,
                                      state="readonly", font=(FONT, SM))
            theme_menu.pack(padx=16, pady=4, anchor="w")
            theme_menu.bind("<<ComboboxSelected>>", lambda e: self.app._set_theme(theme_var.get()))

            tk.Label(sec, text="Transparency", bg=PANEL_BG, fg=TEXT_PRI, font=(FONT, SM),
                     anchor="w").pack(fill=tk.X, padx=16, pady=(8, 2))
            trans_var = tk.IntVar(value=TRANSPARENCY)
            trans_slider = tk.Scale(sec, from_=0, to=50, orient=tk.HORIZONTAL, variable=trans_var,
                                    bg=PANEL_BG, fg=TEXT_PRI, troughcolor=SURFACE, activebackground=ACCENT,
                                    highlightthickness=0, font=(FONT, TNY), length=200)
            trans_slider.pack(padx=16, pady=4, anchor="w")
            def on_trans(e=None):
                self.app._set_transparency(trans_var.get())
            trans_slider.configure(command=on_trans)

        elif name == "Profiles":
            tk.Label(sec, text="Default profile: catterm", bg=PANEL_BG, fg=TEXT_PRI, font=(FONT, SM),
                     anchor="w").pack(fill=tk.X, padx=16, pady=(8, 2))
            tk.Label(sec, text="Profiles can be configured in the JSON settings file.",
                     bg=PANEL_BG, fg=TEXT_MUT, font=(FONT, TNY), anchor="w").pack(fill=tk.X, padx=16, pady=4)

            tk.Label(sec, text="Font", bg=PANEL_BG, fg=TEXT_PRI, font=(FONT, SM),
                     anchor="w").pack(fill=tk.X, padx=16, pady=(16, 2))
            font_var = tk.StringVar(value=FONT)
            font_e = tk.Entry(sec, textvariable=font_var, bg=SURFACE, fg=TEXT_PRI,
                              font=(FONT, SM), relief=tk.FLAT, bd=0, highlightthickness=1,
                              highlightbackground=BORDER, highlightcolor=ACCENT)
            font_e.pack(fill=tk.X, padx=16, ipady=3)

            tk.Label(sec, text="Font size", bg=PANEL_BG, fg=TEXT_PRI, font=(FONT, SM),
                     anchor="w").pack(fill=tk.X, padx=16, pady=(8, 2))
            size_var = tk.IntVar(value=SZ)
            size_spin = tk.Spinbox(sec, from_=8, to=72, textvariable=size_var, width=6,
                                   bg=SURFACE, fg=TEXT_PRI, buttonbackground=SURFACE,
                                   font=(FONT, SM), relief=tk.FLAT, bd=0, highlightthickness=1,
                                   highlightbackground=BORDER, highlightcolor=ACCENT)
            size_spin.pack(padx=16, pady=4, anchor="w")

        elif name == "AI Agent":
            tk.Label(sec, text="LM Studio URL", bg=PANEL_BG, fg=TEXT_PRI, font=(FONT, SM),
                     anchor="w").pack(fill=tk.X, padx=16, pady=(8, 2))
            url_var = tk.StringVar(value=LM_STUDIO_URL)
            url_e = tk.Entry(sec, textvariable=url_var, bg=SURFACE, fg=TEXT_PRI,
                             font=(FONT, SM), relief=tk.FLAT, bd=0, highlightthickness=1,
                             highlightbackground=BORDER, highlightcolor=ACCENT)
            url_e.pack(fill=tk.X, padx=16, ipady=3)

            tk.Label(sec, text="Default model", bg=PANEL_BG, fg=TEXT_PRI, font=(FONT, SM),
                     anchor="w").pack(fill=tk.X, padx=16, pady=(12, 2))
            model_var = tk.StringVar(value=LM_STUDIO_MODEL or "auto")
            model_e = tk.Entry(sec, textvariable=model_var, bg=SURFACE, fg=TEXT_PRI,
                               font=(FONT, SM), relief=tk.FLAT, bd=0, highlightthickness=1,
                               highlightbackground=BORDER, highlightcolor=ACCENT)
            model_e.pack(fill=tk.X, padx=16, ipady=3)

            def apply_ai():
                os.environ["LM_STUDIO_URL"] = url_var.get()
                os.environ["LM_STUDIO_MODEL"] = "" if model_var.get() == "auto" else model_var.get()
                self.app._refresh_status()
                messagebox.showinfo("AI Agent", "Settings applied. Restart recommended for persistent changes.")
            tk.Button(sec, text="Apply", command=apply_ai, bg=ACCENT, fg="#000000",
                      font=(FONT, SM), relief=tk.FLAT, padx=16, pady=4,
                      activebackground=ACCENT_HOVER, activeforeground="#000000",
                      cursor="hand2").pack(padx=16, pady=(16, 4), anchor="w")

        elif name == "About":
            about_text = """catterm 0.2.1
Windows Terminal Replica with AI Agent
            
Built with Python + Tkinter
LM Studio AI integration
            
Powered by deepseek-v4-flash-free"""
            tk.Label(sec, text=about_text, bg=PANEL_BG, fg=TEXT_PRI, font=(FONT, SM),
                     anchor="w", justify=tk.LEFT).pack(padx=16, pady=16)

# ── About Dialog ───────────────────────────────────────────────────────────────

class AboutDialog:
    def __init__(self, parent):
        self.win = tk.Toplevel(parent)
        self.win.title("About catterm")
        self.win.configure(bg=PANEL_BG)
        self.win.geometry("400x300")
        self.win.resizable(False, False)
        self.win.transient(parent)
        self.win.grab_set()

        frame = tk.Frame(self.win, bg=PANEL_BG)
        frame.pack(expand=True, fill=tk.BOTH, padx=24, pady=24)

        tk.Label(frame, text="catterm 0.2.1", bg=PANEL_BG, fg=TEXT_PRI,
                 font=(FONT, 16, "bold")).pack()

        tk.Label(frame, text="Windows Terminal Replica", bg=PANEL_BG, fg=TEXT_SEC,
                 font=(FONT, SM)).pack(pady=(4, 12))

        tk.Label(frame, text="Built with Python + Tkinter", bg=PANEL_BG, fg=TEXT_MUT,
                 font=(FONT, TNY)).pack()
        tk.Label(frame, text="LM Studio AI Integration", bg=PANEL_BG, fg=TEXT_MUT,
                 font=(FONT, TNY)).pack()
        tk.Label(frame, text="", bg=PANEL_BG, fg=TEXT_MUT, font=(FONT, TNY)).pack()
        tk.Label(frame, text="Model: deepseek-v4-flash-free", bg=PANEL_BG, fg=PURPLE,
                 font=(FONT, TNY)).pack()

        tk.Button(frame, text="OK", command=self.win.destroy,
                  bg=ACCENT, fg="#000000", font=(FONT, SM), relief=tk.FLAT,
                  padx=24, pady=4, cursor="hand2",
                  activebackground=ACCENT_HOVER).pack(pady=(16, 0))

# ── Tab ────────────────────────────────────────────────────────────────────────

class Tab:
    def __init__(self, terminal, tab_id, label=None):
        self.terminal = terminal
        self.tab_id = tab_id
        self.conversation = []
        self.label = label or f"Tab {tab_id}"
        self.split_root = None
        self.panes = []

        self.frame = tk.Frame(terminal.out_c, bg=TERM_BG)
        self._build_output()

    def _build_output(self):
        for w in self.frame.winfo_children():
            w.destroy()

        self.text = tk.Text(
            self.frame,
            bg=TERM_BG, fg=TEXT_PRI,
            insertbackground=TEXT_PRI,
            font=self.terminal.mono,
            relief=tk.FLAT, bd=0,
            padx=16, pady=12,
            wrap=tk.WORD,
            state=tk.DISABLED,
            highlightthickness=0,
        )
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        sb = tk.Scrollbar(
            self.frame,
            bg=SURFACE, troughcolor=TERM_BG,
            activebackground=SCROLL_FG,
            command=self.text.yview,
            width=10, relief=tk.FLAT, bd=0,
        )
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.text.configure(yscrollcommand=sb.set)

        self.text.tag_configure("welcome", foreground=ACCENT, font=self.terminal.bold, spacing1=4, spacing3=8)
        self.text.tag_configure("dim", foreground=TEXT_MUT, font=self.terminal.mono, spacing3=2)
        self.text.tag_configure("hdr_user", foreground=ACCENT, font=self.terminal.bold, spacing1=10)
        self.text.tag_configure("txt_user", foreground=TEXT_PRI, spacing3=6, lmargin1=8, lmargin2=8)
        self.text.tag_configure("hdr_ai", foreground=PURPLE, font=self.terminal.bold, spacing1=10)
        self.text.tag_configure("txt_ai", foreground="#E8E8EC", spacing3=6, lmargin1=8, lmargin2=8)
        self.text.tag_configure("code_bg", background=CMD_BG, lmargin1=16, lmargin2=16, spacing1=2, spacing3=2, font=self.terminal.sm)
        self.text.tag_configure("code_out", background=CMD_BG, foreground="#C0CAF5", lmargin1=16, lmargin2=16, font=self.terminal.sm, spacing3=4, spacing1=2)
        self.text.tag_configure("sep", foreground=TEXT_MUT, font=self.terminal.sm, spacing1=2)
        self.text.tag_configure("error", foreground=ERROR_RED, font=self.terminal.mono, spacing1=6, spacing3=6, lmargin1=8)

        # Enable text selection and copy
        self.text.bind("<ButtonPress-1>", self._on_click)
        self.text.bind("<B1-Motion>", self._on_drag)
        self.text.bind("<ButtonRelease-1>", self._on_release)
        self.text.bind("<Button-3>", self._on_right_click)

        self._selection_start = None
        self._selected_text = None

        self._welcome()

    def _on_click(self, e):
        self._selection_start = self.text.index(f"@{e.x},{e.y}")

    def _on_drag(self, e):
        if self._selection_start:
            current = self.text.index(f"@{e.x},{e.y}")
            self.text.tag_remove("sel", "1.0", tk.END)
            self.text.tag_add("sel", self._selection_start, current)
            self.text.tag_configure("sel", background="#5A5A5A")
            self._selected_text = self.text.get(self._selection_start, current)

    def _on_release(self, e):
        if self._selected_text and pyperclip:
            pyperclip.copy(self._selected_text)

    def _on_right_click(self, e):
        menu = tk.Menu(self.frame, bg=SURFACE, fg=TEXT_PRI, activebackground=ACCENT,
                       activeforeground="#000000", relief=tk.FLAT, bd=0)
        menu.add_command(label="Copy", command=self._copy_selection)
        menu.add_command(label="Paste", command=self._paste)
        menu.add_separator(background=BORDER, foreground=TEXT_MUT)
        menu.add_command(label="Select All", command=self._select_all)
        menu.add_command(label="Clear", command=self._clear)
        menu.tk_popup(e.x_root, e.y_root)

    def _copy_selection(self):
        try:
            text = self.text.get(tk.SEL_FIRST, tk.SEL_LAST)
            if pyperclip:
                pyperclip.copy(text)
            else:
                self.text.clipboard_clear()
                self.text.clipboard_append(text)
        except tk.TclError:
            pass

    def _paste(self):
        try:
            if pyperclip:
                text = pyperclip.paste()
            else:
                text = self.text.clipboard_get()
            self.terminal._inject_input(text)
        except Exception:
            pass

    def _select_all(self):
        self.text.tag_add("sel", "1.0", tk.END)
        self.text.tag_configure("sel", background="#5A5A5A")

    def _clear(self):
        self.text.configure(state=tk.NORMAL)
        self.text.delete("1.0", tk.END)
        self.text.configure(state=tk.DISABLED)
        self._welcome()

    def _welcome(self):
        self.out("catterm 0.2.1 — Windows Terminal Replica\n", "welcome")
        self.out("   AI Agent mode — type anything\n", "dim")
        models = check_lm_studio()
        if models:
            self.terminal.model = LM_STUDIO_MODEL or models[0]
            self.out(f"   LM Studio · {len(models)} model(s) loaded\n", "dim")
        else:
            self.out(f"   LM Studio not detected — start LM Studio server\n", "dim")
        self.out("\n", "dim")

    def out(self, text, tag="normal"):
        self.text.configure(state=tk.NORMAL)
        self.text.insert(tk.END, text, tag)
        self.text.configure(state=tk.DISABLED)
        self.text.see(tk.END)

    def show(self):
        self.frame.pack(fill=tk.BOTH, expand=True)

    def hide(self):
        self.frame.pack_forget()

    def reset_output(self):
        for w in self.frame.winfo_children():
            w.destroy()
        self._build_output()

# ── Main Application ───────────────────────────────────────────────────────────

class App:
    def __init__(self, root):
        self.root = root
        self.root.title("catterm 0.2.1")
        self.root.configure(bg=TITLE_BAR_BG)
        self.root.minsize(920, 580)
        try:
            self.root.state("zoomed")
        except Exception:
            pass

        self.model = LM_STUDIO_MODEL
        self.tabs = []
        self.active = None
        self.tc = 0
        self.thinking = False
        self._transparency = TRANSPARENCY
        self._fullscreen = False
        self._theme = CURRENT_THEME

        self.mono = tkfont.Font(family=FONT, size=SZ)
        self.sm = tkfont.Font(family=FONT, size=SM)
        self.tny = tkfont.Font(family=FONT, size=TNY)
        self.bold = tkfont.Font(family=FONT, size=SZ, weight="bold")

        self._build()
        self._new_tab()
        self._tick()
        self._bind_global_keys()

    def _build(self):
        # ── Custom title bar ──
        self.title_bar = tk.Frame(self.root, bg=TITLE_BAR_BG, height=30)
        self.title_bar.pack(fill=tk.X)
        self.title_bar.pack_propagate(False)

        self.title_icon = tk.Label(self.title_bar, text="⊞", bg=TITLE_BAR_BG, fg=TEXT_SEC,
                                   font=(FONT, TNY), padx=8)
        self.title_icon.pack(side=tk.LEFT)

        self.title_text = tk.Label(self.title_bar, text="catterm 0.2.1", bg=TITLE_BAR_BG,
                                   fg=TEXT_SEC, font=(FONT, TNY), anchor="w")
        self.title_text.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Title bar buttons
        tb_btns = tk.Frame(self.title_bar, bg=TITLE_BAR_BG)
        tb_btns.pack(side=tk.RIGHT)

        self._make_title_btn(tb_btns, "─", self._minimize_window)
        self._make_title_btn(tb_btns, "☐", self._toggle_maximize)
        self._make_title_btn(tb_btns, "✕", self.root.quit, hover_bg="#E81123")

        # ── Tab bar ──
        tab_frame = tk.Frame(self.root, bg=TAB_BG, height=32)
        tab_frame.pack(fill=tk.X)
        tab_frame.pack_propagate(False)

        # Tab bar left side (tabs)
        self.tab_bar = tk.Frame(tab_frame, bg=TAB_BG)
        self.tab_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Tab bar right side buttons
        right_btns = tk.Frame(tab_frame, bg=TAB_BG)
        right_btns.pack(side=tk.RIGHT, padx=(0, 4))

        # Profile dropdown
        self.profile_btn = tk.Label(
            right_btns, text="∎ Profile",
            bg=TAB_BG, fg=TEXT_SEC,
            font=(FONT, TNY), cursor="hand2", padx=6,
        )
        self.profile_btn.pack(side=tk.RIGHT, padx=(0, 2))
        self.profile_btn.bind("<Button-1>", self._show_profile_menu)

        self.mlbl = tk.Label(right_btns, text="", bg=TAB_BG, fg=TEXT_MUT, font=self.tny)
        self.mlbl.pack(side=tk.RIGHT, padx=(0, 4))

        # Settings gear
        gear_btn = tk.Label(
            right_btns, text="⚙", fg=TEXT_SEC, bg=TAB_BG,
            font=(FONT, SM), cursor="hand2", padx=4,
        )
        gear_btn.pack(side=tk.RIGHT, padx=(0, 2))
        gear_btn.bind("<Button-1>", lambda e: self._open_settings())

        # 1px separator below tab bar
        sep = tk.Frame(self.root, bg=BORDER, height=1)
        sep.pack(fill=tk.X)

        # ── Main terminal area ──
        main = tk.Frame(self.root, bg=TERM_BG)
        main.pack(fill=tk.BOTH, expand=True)
        self.out_c = tk.Frame(main, bg=TERM_BG)
        self.out_c.pack(fill=tk.BOTH, expand=True)

        # ── Input bar ──
        tk.Frame(self.root, bg=BORDER, height=1).pack(fill=tk.X)

        ic = tk.Frame(self.root, bg=SURFACE)
        ic.pack(fill=tk.X)
        ic.pack_propagate(False)
        ic.configure(height=44)

        row = tk.Frame(ic, bg=SURFACE)
        row.pack(fill=tk.X, padx=12, pady=(5, 5))

        agent_label = tk.Label(
            row, text="✦ Agent",
            bg=SURFACE, fg=PURPLE,
            font=self.tny, padx=6, pady=3,
        )
        agent_label.pack(side=tk.LEFT, padx=(0, 6))

        self.inp = tk.Entry(
            row,
            bg=SURFACE, fg=TEXT_MUT,
            insertbackground=TEXT_PRI,
            font=self.mono,
            relief=tk.FLAT, bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
        )
        self.inp.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=2)
        self.inp.insert(0, "Ask anything...")
        self.inp.bind("<Return>", self._sub)
        self.inp.bind("<FocusIn>", self._fin, "+")
        self.inp.bind("<Key>", self._ky, "+")
        self.inp.bind("<Escape>", lambda e: self.root.focus_set())
        self.inp.focus_set()

        self.snd = tk.Label(
            row, text="▶",
            bg=SURFACE, fg=ACCENT,
            font=self.sm, padx=8, pady=3,
            cursor="hand2",
        )
        self.snd.pack(side=tk.RIGHT, padx=(4, 0))
        self.snd.bind("<Button-1>", lambda e: self._sub(None))

        # ── Status bar ──
        st = tk.Frame(self.root, bg=TERM_BG, height=20)
        st.pack(fill=tk.X)
        st.pack_propagate(False)

        self.stat = tk.Label(
            st, text="", bg=TERM_BG, fg=TEXT_MUT,
            font=self.tny, anchor="w",
        )
        self.stat.pack(side=tk.LEFT, fill=tk.X, padx=12, pady=(1, 0))

        self.stat_right = tk.Label(
            st, text="", bg=TERM_BG, fg=TEXT_MUT,
            font=self.tny, anchor="e",
        )
        self.stat_right.pack(side=tk.RIGHT, padx=12, pady=(1, 0))

    def _make_title_btn(self, parent, text, cmd, hover_bg=None):
        btn = tk.Label(parent, text=text, bg=TITLE_BAR_BG, fg=TEXT_SEC,
                       font=(FONT, TNY, "bold"), padx=10, cursor="hand2")
        btn.pack(side=tk.RIGHT)
        btn.bind("<Button-1>", lambda e: cmd())
        btn.bind("<Enter>", lambda e, b=btn, h=hover_bg: b.configure(bg=h or HOVER_BG))
        btn.bind("<Leave>", lambda e, b=btn: b.configure(bg=TITLE_BAR_BG))

    def _minimize_window(self):
        self.root.iconify()

    def _toggle_maximize(self):
        state = self.root.state()
        if state == "zoomed":
            self.root.state("normal")
        else:
            self.root.state("zoomed")

    def _toggle_fullscreen(self):
        self._fullscreen = not self._fullscreen
        self.root.attributes("-fullscreen", self._fullscreen)

    def _set_transparency(self, val):
        self._transparency = val
        alpha = 1.0 - (val / 100.0)
        self.root.attributes("-alpha", max(0.1, alpha))

    def _set_theme(self, name):
        if name in COLORS:
            self._theme = name
            self._refresh_status()

    def _fin(self, e=None):
        if self.inp.get() == "Ask anything...":
            self.inp.delete(0, tk.END)
            self.inp.configure(fg=TEXT_PRI)

    def _ky(self, e=None):
        if self.inp.get() != "Ask anything...":
            self.inp.configure(fg=TEXT_PRI)

    def _bind_global_keys(self):
        self.root.bind("<Control-c>", lambda e: self._copy())
        self.root.bind("<Control-v>", lambda e: self._paste())
        self.root.bind("<Control-Shift-c>", lambda e: self._copy())
        self.root.bind("<Control-Shift-v>", lambda e: self._paste())
        self.root.bind("<Control-Shift-f>", lambda e: self._open_search())
        self.root.bind("<Control-Shift-p>", lambda e: self._open_command_palette())
        self.root.bind("<Control-Shift-d>", lambda e: self._split_vertical())
        self.root.bind("<Control-Shift-minus>", lambda e: self._split_horizontal())
        self.root.bind("<Control-Shift-w>", lambda e: self._close_active_tab())
        self.root.bind("<Control-Shift-t>", lambda e: self._new_tab())
        self.root.bind("<Control-Shift-z>", lambda e: self._toggle_transparency())
        self.root.bind("<Control-plus>", lambda e: self._zoom_in())
        self.root.bind("<Control-minus>", lambda e: self._zoom_out())
        self.root.bind("<Control-equal>", lambda e: self._zoom_in())
        self.root.bind("<Control-0>", lambda e: self._zoom_reset())
        self.root.bind("<F11>", lambda e: self._toggle_fullscreen())
        self.root.bind("<Alt-Shift-d>", lambda e: self._split_vertical())
        self.root.bind("<Alt-Shift-minus>", lambda e: self._split_horizontal())
        self.root.bind("<Control-Shift-comma>", lambda e: self._open_settings())
        self.root.bind("<Control-Shift-4>", lambda e: self._close_pane())

    def _copy(self):
        if self.active:
            self.active._copy_selection()

    def _paste(self):
        if self.active:
            self.active._paste()

    def _open_search(self):
        if self.active and hasattr(self.active, 'text'):
            SearchDialog(self.root, self.active.text, callback=lambda: self.inp.focus_set())

    def _open_command_palette(self):
        CommandPalette(self.root, self)

    def _open_settings(self):
        SettingsPanel(self.root, self)

    def _show_about(self):
        AboutDialog(self.root)

    def _zoom_in(self):
        new = min(72, SZ + 1)
        self._update_font_size(new)

    def _zoom_out(self):
        new = max(6, SZ - 1)
        self._update_font_size(new)

    def _zoom_reset(self):
        self._update_font_size(12)

    def _update_font_size(self, new_size):
        global SZ
        SZ = new_size
        SM = max(6, SZ - 1)
        TNY = max(6, SZ - 2)
        self.mono.configure(size=SZ)
        self.sm.configure(size=SM)
        self.tny.configure(size=TNY)
        self.bold.configure(size=SZ)
        for tab in self.tabs:
            tab.reset_output()

    def _toggle_transparency(self):
        new = 20 if self._transparency == 0 else 0
        self._set_transparency(new)
        self._refresh_status()

    def _split_vertical(self):
        self._split_pane(SplitPane.VERTICAL)

    def _split_horizontal(self):
        self._split_pane(SplitPane.HORIZONTAL)

    def _split_pane(self, orientation):
        if not self.active:
            return
        tab = self.active
        parent = tab.frame.master
        tab.hide()
        old_frame = tab.frame
        old_frame.pack_forget()

        sp = SplitPane(parent, TERM_BG, orientation)
        tab2 = Tab(self, self.tc + 1, label=f"Pane {self.tc + 1}")
        self.tc += 1

        sp.add_child(old_frame)
        sp.add_child(tab2.frame)
        sp.pack(fill=tk.BOTH, expand=True)
        self.active = tab
        tab.show()
        self._rebuild_tabs()

    def _close_pane(self):
        if not self.active:
            return
        self._cl(self.active)

    def _close_active_tab(self):
        if self.active and len(self.tabs) > 1:
            self._cl(self.active)

    def _show_profile_menu(self, e):
        menu = tk.Menu(self.root, bg=SURFACE, fg=TEXT_PRI, activebackground=ACCENT,
                       activeforeground="#000000", relief=tk.FLAT, bd=0)
        menu.add_command(label="Settings", command=self._open_settings)
        menu.add_separator(background=BORDER)
        for theme in THEMES:
            menu.add_command(label=f"Color: {theme}", command=lambda t=theme: self._set_theme(t))
        menu.add_separator(background=BORDER)
        menu.add_command(label="About", command=self._show_about)
        menu.tk_popup(e.x_root, e.y_root)

    def _rebuild_tabs(self):
        for w in self.tab_bar.winfo_children():
            w.destroy()

        for i, tab in enumerate(self.tabs):
            act = (tab == self.active)
            bg = ACTIVE_BG if act else TAB_BG
            fg = TEXT_PRI if act else TEXT_SEC

            container = tk.Frame(self.tab_bar, bg=TAB_BG)
            container.pack(side=tk.LEFT)

            inner = tk.Frame(container, bg=bg)
            inner.pack(fill=tk.Y, ipadx=0, ipady=0)

            if act:
                accent_outer = tk.Frame(inner, bg=ACTIVE_BG, height=2)
                accent_outer.pack(side=tk.BOTTOM, fill=tk.X)
                tk.Frame(accent_outer, bg=ACCENT, height=2).pack(fill=tk.X, padx=0)

            sep_line = tk.Frame(container, bg=BORDER, width=1)
            sep_line.pack(side=tk.RIGHT, fill=tk.Y)

            favicon = tk.Label(
                inner, text="⊞",
                bg=bg, fg=ACCENT if act else TEXT_MUT,
                font=self.tny, cursor="hand2",
            )
            favicon.pack(side=tk.LEFT, padx=(10, 2), pady=(5, 3))

            lbl = tk.Label(
                inner, text=tab.label,
                bg=bg, fg=fg,
                font=self.sm, cursor="hand2",
            )
            lbl.pack(side=tk.LEFT, padx=(0, 2), pady=(5, 3))
            lbl.bind("<Button-1>", lambda e, t=tab: self._sw(t))
            lbl.bind("<Double-Button-1>", lambda e, t=tab: self._rn(t))

            close = tk.Label(
                inner, text="×",
                bg=bg, fg=TEXT_MUT if not act else TEXT_SEC,
                font=(FONT, TNY, "bold"), cursor="hand2",
            )
            close.pack(side=tk.RIGHT, padx=(2, 8), pady=(5, 3))
            close.bind("<Button-1>", lambda e, t=tab: self._cl(t))
            close.bind("<Enter>", lambda e, c=close, b=bg: c.configure(bg="#E81123" if act else ERROR_RED, fg=TEXT_PRI))
            close.bind("<Leave>", lambda e, c=close, b=bg: c.configure(bg=b, fg=TEXT_MUT))

        plus = tk.Label(
            self.tab_bar, text="+",
            bg=TAB_BG, fg=TEXT_SEC,
            font=self.sm, cursor="hand2",
        )
        plus.pack(side=tk.LEFT, padx=(4, 0), pady=(4, 4))
        plus.bind("<Button-1>", lambda e: self._new_tab())

    def _rn(self, tab, e=None):
        def done(e=None):
            n = en.get().strip()
            if n:
                tab.label = n
            en.destroy()
            self._rebuild_tabs()

        tg = None
        for c in self.tab_bar.winfo_children():
            for gc in (c.winfo_children() if hasattr(c, 'winfo_children') else []):
                for w in (gc.winfo_children() if hasattr(gc, 'winfo_children') else []):
                    if isinstance(w, tk.Label) and w.cget("text") == tab.label and w.cget("cursor") == "hand2":
                        tg = gc
                        break
        if not tg:
            return

        en = tk.Entry(
            tg,
            bg=ACTIVE_BG, fg=TEXT_PRI,
            insertbackground=TEXT_PRI,
            font=self.sm,
            relief=tk.FLAT, bd=0,
            highlightthickness=0,
            width=12,
        )
        en.insert(0, tab.label)
        en.select_range(0, tk.END)
        en.icursor(tk.END)
        en.focus_set()
        en.bind("<Return>", done)
        en.bind("<Escape>", lambda e: en.destroy() or self._rebuild_tabs())
        en.bind("<FocusOut>", done)
        en.pack(side=tk.LEFT, padx=(24, 4), pady=4, ipady=1)

    def _new_tab(self, e=None):
        self.tc += 1
        tab = Tab(self, self.tc)
        self.tabs.append(tab)
        tab.hide()
        if self.active:
            self.active.hide()
        self.active = tab
        tab.show()
        self._rebuild_tabs()
        self.inp.focus_set()

    def _sw(self, tab):
        if tab == self.active:
            return
        if self.active:
            self.active.hide()
        self.active = tab
        tab.show()
        self._rebuild_tabs()
        self.inp.focus_set()

    def _cl(self, tab):
        if len(self.tabs) <= 1:
            return
        i = self.tabs.index(tab)
        self.tabs.remove(tab)
        tab.frame.destroy()
        if self.active == tab:
            self.active = None
            next_idx = i if i < len(self.tabs) else len(self.tabs) - 1
            self.active = self.tabs[next_idx]
            self.active.show()
        self._rebuild_tabs()
        self.inp.focus_set()

    def _close_tab(self, tab):
        self._cl(tab)

    def _inject_input(self, text):
        self.inp.delete(0, tk.END)
        self.inp.insert(0, text)
        self.inp.configure(fg=TEXT_PRI)

    def _sub(self, e):
        t = self.inp.get().strip()
        if not t or t == "Ask anything..." or self.thinking or not self.active:
            return "break"
        self.inp.delete(0, tk.END)
        self.inp.configure(fg=TEXT_PRI)
        self._go(t)
        return "break"

    def _go(self, txt):
        self.thinking = True
        self.snd.configure(text="⋯", fg=TEXT_MUT)
        self.inp.configure(state=tk.DISABLED)
        tab = self.active

        tab.out("[You]\n", "hdr_user")
        tab.out(f"  {txt}\n", "txt_user")
        tab.out("[Agent]\n", "hdr_ai")
        tab.out("  ", "txt_ai")

        threading.Thread(target=self._thr, args=(txt, tab), daemon=True).start()

    def _thr(self, txt, tab):
        try:
            sys = {"role": "system", "content": AGENT_PROMPT}
            msgs = [sys] + tab.conversation + [{"role": "user", "content": txt}]
            r = lm_studio_request(msgs, model=self.model)

            if r.startswith("Error:"):
                self.root.after(0, self._err, tab, r)
                return

            tab.conversation.append({"role": "user", "content": txt})
            tab.conversation.append({"role": "assistant", "content": r})
            if len(tab.conversation) > 30:
                tab.conversation[:4] = []

            cmds = extract_bash_blocks(r)
            self.root.after(0, self._res, tab, r, cmds)
        except Exception as e:
            self.root.after(0, self._err, tab, str(e))

    def _res(self, tab, r, cmds):
        clean = re.sub(r"```(?:bash|sh|shell)?\n.*?```", "", r, flags=re.DOTALL)
        clean = clean.strip()
        if clean:
            clean = parse_markdown_inline(clean)
            tab.out(clean + "\n", "txt_ai")

        if cmds:
            for cmd in cmds:
                tab.out(f"  $ {cmd}\n", "code_bg")
                out = run_shell(cmd)
                tab.out(f"  {out}\n", "code_out")
                tab.conversation.append({
                    "role": "user",
                    "content": f"[system: output of `{cmd}`]:\n{out}"
                })

        if not clean and not cmds:
            tab.out("(no response)\n", "dim")

        tab.out("\n", "dim")
        self.thinking = False
        self.snd.configure(text="▶", fg=ACCENT)
        self.inp.configure(state=tk.NORMAL)
        self.inp.focus_set()

    def _err(self, tab, msg):
        tab.out(f"\n  {msg}\n\n", "error")
        self.thinking = False
        self.snd.configure(text="▶", fg=ACCENT)
        self.inp.configure(state=tk.NORMAL)
        self.inp.focus_set()

    def _tick(self):
        s = f"LM Studio: {LM_STUDIO_URL}"
        if self.model:
            s += f"  |  {self.model}"
        if self.active:
            s += f"  |  [{self.active.label}]"
        self.stat.configure(text=s)

        r = f"Scheme: {self._theme}"
        if self._transparency > 0:
            r += f"  |  Alpha: {1.0 - self._transparency/100:.0%}"
        self.stat_right.configure(text=r)
        self.root.after(16, self._tick)

    def _refresh_status(self):
        pass


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
