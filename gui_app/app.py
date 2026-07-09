"""
Shoreline Change Uncertainty — tkinter GUI
==========================================
Stand-alone GUI wrapper for the ``surf`` Python package.

Usage::

    python -m gui_app                    # run directly from repo
    python gui_app/build_exe.py          # build a distributable .exe / binary

The GUI mirrors every option in the YAML config schema.  A run config can be
saved to / loaded from a YAML file so it is interchangeable with the CLI::

    python -m surf.cli run --config my_config.yaml
"""
from __future__ import annotations

import logging
import queue
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

# ---------------------------------------------------------------------------
# Optional runtime dependencies
# ---------------------------------------------------------------------------
try:
    import yaml as _yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

try:
    from surf.config import (
        RunConfig,
        ShorelineYear,
        SiteConfig,
        load_config,
    )
    from surf.pipeline import run_pipeline
    _HAS_PKG = True
except ImportError:
    _HAS_PKG = False

APP_TITLE = "Shoreline Change Uncertainty"
PAD = 7

# ---------------------------------------------------------------------------
# Lightweight internal data model (no tk vars — converted at run/load time)
# ---------------------------------------------------------------------------

@dataclass
class _ShorelineRow:
    year: int
    path: str
    rmse95: Optional[float] = None
    acq_date: Optional[str] = None


@dataclass
class _SiteRow:
    name: str = "site_1"
    transect_spacing: float = 10.0
    transect_length: float = 300.0
    coord_priority: str = "UPPER_LEFT"
    shorelines: List[_ShorelineRow] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Add / Edit Shoreline dialog
# ---------------------------------------------------------------------------

class _ShorelineDialog(tk.Toplevel):
    """Modal dialog for entering one shoreline year."""

    def __init__(self, parent, *, title: str = "Add Shoreline",
                 initial: Optional[_ShorelineRow] = None):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.grab_set()
        self.result: Optional[_ShorelineRow] = None

        fr = ttk.Frame(self, padding=12)
        fr.grid(sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        fr.columnconfigure(1, weight=1)

        def row_lbl(text, r):
            ttk.Label(fr, text=text, anchor="e").grid(
                row=r, column=0, sticky="e", padx=(0, 6), pady=5)

        # Year
        row_lbl("Year:", 0)
        self._year = tk.StringVar(value=str(initial.year) if initial else "")
        ttk.Entry(fr, textvariable=self._year, width=10).grid(
            row=0, column=1, sticky="w", pady=5)

        # Shapefile path
        row_lbl("Shapefile:", 1)
        self._path = tk.StringVar(value=initial.path if initial else "")
        pf = ttk.Frame(fr)
        pf.grid(row=1, column=1, sticky="ew", pady=5)
        ttk.Entry(pf, textvariable=self._path, width=46).pack(
            side="left", fill="x", expand=True)
        ttk.Button(pf, text="Browse…", command=self._browse).pack(
            side="left", padx=(4, 0))

        # RMSE95
        row_lbl("RMSE95 (m):", 2)
        self._rmse = tk.StringVar(
            value=str(initial.rmse95) if (initial and initial.rmse95 is not None) else "")
        rf = ttk.Frame(fr)
        rf.grid(row=2, column=1, sticky="w", pady=5)
        ttk.Entry(rf, textvariable=self._rmse, width=12).pack(side="left")
        ttk.Label(rf, text="  optional — leave blank to compute from RMSE components",
                  foreground="gray").pack(side="left")

        # Acquisition date
        row_lbl("Acq. date:", 3)
        self._date = tk.StringVar(
            value=initial.acq_date if (initial and initial.acq_date) else "")
        df = ttk.Frame(fr)
        df.grid(row=3, column=1, sticky="w", pady=5)
        ttk.Entry(df, textvariable=self._date, width=14).pack(side="left")
        ttk.Label(df, text="  optional, YYYY-MM-DD (for NOAA water-level lookup)",
                  foreground="gray").pack(side="left")

        # Buttons
        bf = ttk.Frame(fr)
        bf.grid(row=4, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(bf, text="Cancel", command=self.destroy).pack(
            side="right", padx=(4, 0))
        ttk.Button(bf, text="OK", command=self._ok).pack(side="right")

        self.wait_window()

    def _browse(self):
        p = filedialog.askopenfilename(
            parent=self, title="Select shoreline shapefile",
            filetypes=[("Shapefiles", "*.shp"), ("All files", "*.*")])
        if p:
            self._path.set(p)

    def _ok(self):
        year_s = self._year.get().strip()
        path_s = self._path.get().strip()
        if not year_s.lstrip("-").isdigit():
            messagebox.showerror("Invalid year",
                                 "Year must be a positive integer (e.g. 2010).", parent=self)
            return
        if not path_s:
            messagebox.showerror("Missing path",
                                 "A shapefile path is required.", parent=self)
            return
        rmse = None
        if self._rmse.get().strip():
            try:
                rmse = float(self._rmse.get().strip())
            except ValueError:
                messagebox.showerror("Invalid RMSE95",
                                     "RMSE95 must be a number (e.g. 13.28).", parent=self)
                return
        self.result = _ShorelineRow(
            year=int(year_s),
            path=path_s,
            rmse95=rmse,
            acq_date=self._date.get().strip() or None,
        )
        self.destroy()


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------

class SURFApp(tk.Tk):
    """Main tkinter window for the Shoreline Change Uncertainty GUI."""

    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.minsize(980, 660)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        # Internal state
        self._log_q: queue.Queue = queue.Queue()
        self._running = False
        self.sites: List[_SiteRow] = []
        self._cur_site: int = -1

        self._build_menu()
        self._build_notebook()
        self._build_statusbar()

        if not _HAS_PKG:
            self._warn_no_package()

        self._poll_log()

    # ------------------------------------------------------------------ #
    # Menu                                                                 #
    # ------------------------------------------------------------------ #

    def _build_menu(self):
        mb = tk.Menu(self)
        self.config(menu=mb)

        fm = tk.Menu(mb, tearoff=0)
        mb.add_cascade(label="File", menu=fm)
        fm.add_command(label="New",         command=self._new,         accelerator="Ctrl+N")
        fm.add_command(label="Open YAML…",  command=self._load_yaml,   accelerator="Ctrl+O")
        fm.add_command(label="Save YAML…",  command=self._save_yaml,   accelerator="Ctrl+S")
        fm.add_separator()
        fm.add_command(label="Exit", command=self.destroy)

        hm = tk.Menu(mb, tearoff=0)
        mb.add_cascade(label="Help", menu=hm)
        hm.add_command(label="About", command=self._about)

        self.bind_all("<Control-n>", lambda _: self._new())
        self.bind_all("<Control-o>", lambda _: self._load_yaml())
        self.bind_all("<Control-s>", lambda _: self._save_yaml())

    # ------------------------------------------------------------------ #
    # Notebook                                                             #
    # ------------------------------------------------------------------ #

    def _build_notebook(self):
        self._nb = ttk.Notebook(self)
        self._nb.grid(row=0, column=0, sticky="nsew", padx=PAD, pady=(PAD, 0))
        self._build_settings_tab(self._nb)
        self._build_sites_tab(self._nb)
        self._build_log_tab(self._nb)

    # ------------------------------------------------------------------ #
    # Settings tab                                                         #
    # ------------------------------------------------------------------ #

    def _build_settings_tab(self, nb: ttk.Notebook):
        fr = ttk.Frame(nb, padding=PAD + 2)
        nb.add(fr, text="  Settings  ")
        fr.columnconfigure(1, weight=1)

        r = 0

        def lbl(text):
            nonlocal r
            ttk.Label(fr, text=text, anchor="e").grid(
                row=r, column=0, sticky="e", padx=(0, 6), pady=4)

        # Output directory
        lbl("Output directory:")
        self._out_dir = tk.StringVar()
        od = ttk.Frame(fr)
        od.grid(row=r, column=1, sticky="ew", pady=4); r += 1
        ttk.Entry(od, textvariable=self._out_dir).pack(side="left", fill="x", expand=True)
        ttk.Button(od, text="Browse…", command=self._browse_outdir).pack(side="left", padx=(4, 0))

        # Target CRS
        lbl("Target CRS:")
        self._crs = tk.StringVar(value="EPSG:3175")
        cf = ttk.Frame(fr)
        cf.grid(row=r, column=1, sticky="w", pady=4); r += 1
        ttk.Entry(cf, textvariable=self._crs, width=18).pack(side="left")
        ttk.Label(cf, text="  e.g. EPSG:26989  —  leave blank to inherit from first shoreline",
                  foreground="gray").pack(side="left")

        # Epsilon band method
        lbl("Epsilon band method:")
        self._eps_method = tk.StringVar(value="odb")
        ef = ttk.Frame(fr)
        ef.grid(row=r, column=1, sticky="w", pady=4); r += 1
        for val, txt in [("odb", "ODB (recommended)"),
                         ("perkal", "Perkal (legacy)"),
                         ("both", "Both")]:
            ttk.Radiobutton(ef, text=txt, variable=self._eps_method,
                            value=val).pack(side="left", padx=(0, 12))

        # Significance threshold
        lbl("Significance threshold:")
        self._sig = tk.StringVar(value="0.01")
        sf = ttk.Frame(fr)
        sf.grid(row=r, column=1, sticky="w", pady=4); r += 1
        ttk.Entry(sf, textvariable=self._sig, width=10).pack(side="left")
        ttk.Label(sf, text="  Ps  (Wernette et al. 2017 Eq. 4) — change below this is not statistically real",
                  foreground="gray").pack(side="left")

        # Raster cell size
        lbl("Raster cell size (m):")
        self._cell = tk.StringVar(value="0.5")
        csf = ttk.Frame(fr)
        csf.grid(row=r, column=1, sticky="w", pady=4); r += 1
        ttk.Entry(csf, textvariable=self._cell, width=10).pack(side="left")
        ttk.Label(csf, text="  for Similarity Index / Significant Change raster outputs",
                  foreground="gray").pack(side="left")

        # Confidence levels
        lbl("Confidence levels:")
        self._conf = tk.StringVar(value="0.5, 0.9, 0.95")
        clf = ttk.Frame(fr)
        clf.grid(row=r, column=1, sticky="w", pady=4); r += 1
        ttk.Entry(clf, textvariable=self._conf, width=22).pack(side="left")
        ttk.Label(clf, text="  comma-separated  (used by Perkal method and critical-area identification)",
                  foreground="gray").pack(side="left")

        ttk.Separator(fr, orient="horizontal").grid(
            row=r, column=0, columnspan=2, sticky="ew", pady=10); r += 1

        # Export intersect geometries
        self._export_int = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            fr, text="Export raw intersection / union geometries (for QA in a desktop GIS)",
            variable=self._export_int,
        ).grid(row=r, column=1, sticky="w", pady=2); r += 1

        ttk.Separator(fr, orient="horizontal").grid(
            row=r, column=0, columnspan=2, sticky="ew", pady=10); r += 1

        # Compute prob change
        self._prob = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            fr,
            text="Compute Gaussian change-probability surfaces, segments, and rate-change polygons",
            variable=self._prob,
            command=self._toggle_prob,
        ).grid(row=r, column=1, sticky="w", pady=2); r += 1

        lbl("Segment length (m):")
        self._seg_len = tk.StringVar(value="50.0")
        self._seg_frame = ttk.Frame(fr)
        self._seg_frame.grid(row=r, column=1, sticky="w", pady=4); r += 1
        ttk.Entry(self._seg_frame, textvariable=self._seg_len, width=10).pack(side="left")
        ttk.Label(self._seg_frame,
                  text="  shoreline is broken into segments this long for PROB_CHANGE attribute",
                  foreground="gray").pack(side="left")

        # Compute rate of change
        self._rate = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            fr,
            text="Compute EPR / LRR rate-of-change statistics (End Point Rate and Linear Regression Rate)",
            variable=self._rate,
        ).grid(row=r, column=1, sticky="w", pady=2); r += 1

        self._toggle_prob()

    def _toggle_prob(self):
        state = "normal" if self._prob.get() else "disabled"
        for w in self._seg_frame.winfo_children():
            try:
                w.config(state=state)
            except tk.TclError:
                pass

    def _browse_outdir(self):
        d = filedialog.askdirectory(parent=self, title="Select output directory")
        if d:
            self._out_dir.set(d)

    # ------------------------------------------------------------------ #
    # Sites tab                                                            #
    # ------------------------------------------------------------------ #

    def _build_sites_tab(self, nb: ttk.Notebook):
        outer = ttk.Frame(nb, padding=PAD)
        nb.add(outer, text="  Sites  ")
        outer.rowconfigure(0, weight=1)
        outer.columnconfigure(1, weight=1)

        # ── left: site list ───────────────────────────────────────────
        left = ttk.Frame(outer, width=190)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, PAD))
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        ttk.Label(left, text="Sites", font=("", 10, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 4))

        lb_frame = ttk.Frame(left)
        lb_frame.grid(row=1, column=0, sticky="nsew")
        lb_frame.rowconfigure(0, weight=1)
        lb_frame.columnconfigure(0, weight=1)

        self._site_lb = tk.Listbox(lb_frame, selectmode="single",
                                   exportselection=False, width=22)
        self._site_lb.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(lb_frame, orient="vertical",
                           command=self._site_lb.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self._site_lb.config(yscrollcommand=sb.set)
        self._site_lb.bind("<<ListboxSelect>>", self._on_site_select)

        bf = ttk.Frame(left)
        bf.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        ttk.Button(bf, text="+ Add",    command=self._add_site).pack(
            side="left", fill="x", expand=True)
        ttk.Button(bf, text="✕ Remove", command=self._remove_site).pack(
            side="left", fill="x", expand=True, padx=(4, 0))

        # ── right: site detail ────────────────────────────────────────
        right = ttk.Frame(outer)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(1, weight=1)
        right.rowconfigure(6, weight=1)

        self._detail_frame = right

        ttk.Label(right, text="Site details", font=("", 10, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))

        def dlbl(text, r):
            ttk.Label(right, text=text, anchor="e").grid(
                row=r, column=0, sticky="e", padx=(0, 6), pady=4)

        # Site name
        dlbl("Site name:", 1)
        self._site_name = tk.StringVar()
        self._site_name.trace_add("write", self._sync_site_name)
        ttk.Entry(right, textvariable=self._site_name, width=26).grid(
            row=1, column=1, sticky="w", pady=4)

        # Transect spacing
        dlbl("Transect spacing (m):", 2)
        self._t_spacing = tk.StringVar(value="10.0")
        ttk.Entry(right, textvariable=self._t_spacing, width=12).grid(
            row=2, column=1, sticky="w", pady=4)

        # Transect length
        dlbl("Transect length (m):", 3)
        self._t_length = tk.StringVar(value="300.0")
        ttk.Entry(right, textvariable=self._t_length, width=12).grid(
            row=3, column=1, sticky="w", pady=4)

        # Coordinate priority
        dlbl("Coordinate priority:", 4)
        self._coord = tk.StringVar(value="UPPER_LEFT")
        ttk.OptionMenu(right, self._coord, "UPPER_LEFT",
                       "UPPER_LEFT", "UPPER_RIGHT",
                       "LOWER_LEFT", "LOWER_RIGHT").grid(
            row=4, column=1, sticky="w", pady=4)

        ttk.Separator(right, orient="horizontal").grid(
            row=5, column=0, columnspan=3, sticky="ew", pady=8)

        # Shorelines sub-section
        ttk.Label(right, text="Shorelines", font=("", 10, "bold")).grid(
            row=5, column=0, columnspan=3, sticky="sw", pady=(8, 2))

        cols = ("Year", "Shapefile", "RMSE95 (m)", "Acq. Date")
        self._sl_tree = ttk.Treeview(right, columns=cols, show="headings",
                                     selectmode="browse", height=9)
        for col, w in zip(cols, (60, 380, 90, 90)):
            self._sl_tree.heading(col, text=col, anchor="w")
            self._sl_tree.column(col, width=w, minwidth=50)
        self._sl_tree.grid(row=6, column=0, columnspan=3, sticky="nsew", pady=(0, 4))
        self._sl_tree.bind("<Double-1>", lambda _: self._edit_shoreline())

        sl_sb = ttk.Scrollbar(right, orient="vertical",
                              command=self._sl_tree.yview)
        sl_sb.grid(row=6, column=3, sticky="ns")
        self._sl_tree.config(yscrollcommand=sl_sb.set)

        sl_bf = ttk.Frame(right)
        sl_bf.grid(row=7, column=0, columnspan=3, sticky="w")
        ttk.Button(sl_bf, text="+ Add Shoreline",
                   command=self._add_shoreline).pack(side="left")
        ttk.Button(sl_bf, text="✎ Edit",
                   command=self._edit_shoreline).pack(side="left", padx=(4, 0))
        ttk.Button(sl_bf, text="✕ Remove",
                   command=self._remove_shoreline).pack(side="left", padx=(4, 0))

        self._set_detail_state("disabled")

    def _set_detail_state(self, state: str):
        def recurse(w):
            try:
                w.config(state=state)
            except tk.TclError:
                pass
            for child in w.winfo_children():
                recurse(child)
        for child in self._detail_frame.winfo_children():
            recurse(child)

    # site management -------------------------------------------------

    def _add_site(self):
        self._flush_site_detail()
        new = _SiteRow(name=f"site_{len(self.sites) + 1}")
        self.sites.append(new)
        idx = len(self.sites) - 1
        self._site_lb.insert("end", new.name)
        self._site_lb.selection_clear(0, "end")
        self._site_lb.selection_set(idx)
        self._site_lb.see(idx)
        self._cur_site = idx
        self._load_site_detail(idx)

    def _remove_site(self):
        sel = self._site_lb.curselection()
        if not sel:
            return
        idx = sel[0]
        if not messagebox.askyesno(
                "Remove site",
                f"Remove site '{self.sites[idx].name}'?", parent=self):
            return
        self.sites.pop(idx)
        self._site_lb.delete(idx)
        self._cur_site = -1
        new_idx = min(idx, len(self.sites) - 1)
        if self.sites:
            self._site_lb.selection_set(new_idx)
            self._cur_site = new_idx
            self._load_site_detail(new_idx)
        else:
            self._load_site_detail(-1)

    def _on_site_select(self, _event=None):
        self._flush_site_detail()
        sel = self._site_lb.curselection()
        if not sel:
            return
        self._cur_site = sel[0]
        self._load_site_detail(self._cur_site)

    def _load_site_detail(self, idx: int):
        if idx < 0 or idx >= len(self.sites):
            self._site_name.set("")
            self._t_spacing.set("10.0")
            self._t_length.set("300.0")
            self._coord.set("UPPER_LEFT")
            self._sl_tree.delete(*self._sl_tree.get_children())
            self._set_detail_state("disabled")
            return
        self._set_detail_state("normal")
        s = self.sites[idx]
        self._site_name.set(s.name)
        self._t_spacing.set(str(s.transect_spacing))
        self._t_length.set(str(s.transect_length))
        self._coord.set(s.coord_priority)
        self._sl_tree.delete(*self._sl_tree.get_children())
        for sl in s.shorelines:
            self._sl_tree.insert("", "end", values=(
                sl.year, sl.path,
                sl.rmse95 if sl.rmse95 is not None else "",
                sl.acq_date or ""))

    def _flush_site_detail(self):
        """Write form values back into the current _SiteRow (call before switch)."""
        idx = self._cur_site
        if idx < 0 or idx >= len(self.sites):
            return
        s = self.sites[idx]
        s.name = self._site_name.get().strip() or s.name
        try:
            s.transect_spacing = float(self._t_spacing.get())
        except ValueError:
            pass
        try:
            s.transect_length = float(self._t_length.get())
        except ValueError:
            pass
        s.coord_priority = self._coord.get()

    def _sync_site_name(self, *_):
        idx = self._cur_site
        if idx < 0 or idx >= len(self.sites):
            return
        new_name = self._site_name.get()
        self.sites[idx].name = new_name
        self._site_lb.delete(idx)
        self._site_lb.insert(idx, new_name)
        self._site_lb.selection_set(idx)

    # shoreline management --------------------------------------------

    def _add_shoreline(self):
        if self._cur_site < 0:
            return
        dlg = _ShorelineDialog(self, title="Add Shoreline")
        if dlg.result:
            self.sites[self._cur_site].shorelines.append(dlg.result)
            sl = dlg.result
            self._sl_tree.insert("", "end", values=(
                sl.year, sl.path,
                sl.rmse95 if sl.rmse95 is not None else "",
                sl.acq_date or ""))

    def _edit_shoreline(self):
        sel = self._sl_tree.selection()
        if not sel:
            return
        iid = sel[0]
        ti = self._sl_tree.index(iid)
        existing = self.sites[self._cur_site].shorelines[ti]
        dlg = _ShorelineDialog(self, title="Edit Shoreline", initial=existing)
        if dlg.result:
            self.sites[self._cur_site].shorelines[ti] = dlg.result
            sl = dlg.result
            self._sl_tree.item(iid, values=(
                sl.year, sl.path,
                sl.rmse95 if sl.rmse95 is not None else "",
                sl.acq_date or ""))

    def _remove_shoreline(self):
        sel = self._sl_tree.selection()
        if not sel:
            return
        iid = sel[0]
        ti = self._sl_tree.index(iid)
        self.sites[self._cur_site].shorelines.pop(ti)
        self._sl_tree.delete(iid)

    # ------------------------------------------------------------------ #
    # Log tab                                                              #
    # ------------------------------------------------------------------ #

    def _build_log_tab(self, nb: ttk.Notebook):
        fr = ttk.Frame(nb, padding=PAD)
        nb.add(fr, text="  Log  ")
        fr.rowconfigure(0, weight=1)
        fr.columnconfigure(0, weight=1)

        self._log_txt = scrolledtext.ScrolledText(
            fr, wrap="word", state="disabled",
            font=("Courier New", 9),
            background="#1e1e1e", foreground="#d4d4d4",
            insertbackground="#d4d4d4")
        self._log_txt.grid(row=0, column=0, sticky="nsew")

        bf = ttk.Frame(fr)
        bf.grid(row=1, column=0, sticky="e", pady=(4, 0))
        ttk.Button(bf, text="Save Log…", command=self._save_log).pack(
            side="right", padx=(4, 0))
        ttk.Button(bf, text="Clear", command=self._clear_log).pack(side="right")

    def _append_log(self, msg: str):
        self._log_txt.config(state="normal")
        self._log_txt.insert("end", msg + "\n")
        self._log_txt.see("end")
        self._log_txt.config(state="disabled")

    def _clear_log(self):
        self._log_txt.config(state="normal")
        self._log_txt.delete("1.0", "end")
        self._log_txt.config(state="disabled")

    def _save_log(self):
        p = filedialog.asksaveasfilename(
            parent=self, defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="Save log")
        if p:
            Path(p).write_text(
                self._log_txt.get("1.0", "end"), encoding="utf-8")

    def _log(self, msg: str):
        """Thread-safe: queue a message for the log widget."""
        self._log_q.put(msg)

    def _poll_log(self):
        try:
            while True:
                self._append_log(self._log_q.get_nowait())
        except queue.Empty:
            pass
        self.after(100, self._poll_log)

    # ------------------------------------------------------------------ #
    # Status bar + Run button                                              #
    # ------------------------------------------------------------------ #

    def _build_statusbar(self):
        bar = ttk.Frame(self, relief="sunken")
        bar.grid(row=1, column=0, sticky="ew")
        bar.columnconfigure(0, weight=1)

        self._status = tk.StringVar(value="Ready.")
        ttk.Label(bar, textvariable=self._status, anchor="w").grid(
            row=0, column=0, sticky="ew", padx=PAD, pady=3)

        ttk.Button(bar, text="Save YAML…", command=self._save_yaml).grid(
            row=0, column=1, padx=(0, 4), pady=2)
        self._run_btn = ttk.Button(bar, text="▶  Run Analysis", command=self._run)
        self._run_btn.grid(row=0, column=2, padx=(0, PAD), pady=2, ipadx=8)

    # ------------------------------------------------------------------ #
    # Run logic                                                            #
    # ------------------------------------------------------------------ #

    def _run(self):
        if self._running:
            return
        if not _HAS_PKG:
            messagebox.showerror(
                "Package not installed",
                "surf is not installed.\n\n"
                "From the repo root:\n  pip install -e .",
                parent=self)
            return
        cfg = self._collect_config()
        if cfg is None:
            return
        self._running = True
        self._run_btn.config(state="disabled")
        self._status.set("Running…")
        self._nb.select(2)      # switch to Log tab
        threading.Thread(target=self._run_thread, args=(cfg,), daemon=True).start()

    def _run_thread(self, cfg: "RunConfig"):
        root_log = logging.getLogger()
        handler = _QueueHandler(self._log_q)
        handler.setFormatter(logging.Formatter("%(levelname)s  %(message)s"))
        root_log.addHandler(handler)
        old_level = root_log.level
        root_log.setLevel(logging.INFO)
        try:
            self._log("=" * 64)
            self._log(f"Output directory : {cfg.output_dir}")
            self._log(f"Sites            : {', '.join(s.name for s in cfg.sites)}")
            self._log(f"Epsilon method   : {cfg.epsilon_band_method}")
            self._log(f"Prob change      : {cfg.compute_prob_change}")
            self._log("=" * 64)
            run_pipeline(cfg, progress=False)
            self._log("=" * 64)
            self._log("Analysis complete.")
            self._log(f"Outputs → {cfg.output_dir}")
            self.after(0, lambda: self._status.set(
                f"Complete — outputs in {cfg.output_dir}"))
            self.after(0, lambda: messagebox.showinfo(
                "Complete",
                f"Analysis finished.\nOutputs written to:\n{cfg.output_dir}",
                parent=self))
        except Exception:
            tb = traceback.format_exc()
            self._log("ERROR:\n" + tb)
            self.after(0, lambda: self._status.set(
                "Run failed — see Log tab for details."))
            self.after(0, lambda: messagebox.showerror(
                "Run failed",
                "The analysis encountered an error.\n"
                "See the Log tab for details.",
                parent=self))
        finally:
            root_log.removeHandler(handler)
            root_log.setLevel(old_level)
            self._running = False
            self.after(0, lambda: self._run_btn.config(state="normal"))

    # ------------------------------------------------------------------ #
    # Config collection + validation                                       #
    # ------------------------------------------------------------------ #

    def _collect_config(self) -> Optional["RunConfig"]:
        """Read GUI state and return a RunConfig, or None if validation fails."""
        self._flush_site_detail()

        out_dir = self._out_dir.get().strip()
        if not out_dir:
            messagebox.showerror(
                "Missing output directory",
                "Set an output directory in the Settings tab.", parent=self)
            return None

        if not self.sites:
            messagebox.showerror(
                "No sites",
                "Add at least one site in the Sites tab.", parent=self)
            return None

        site_cfgs = []
        for s in self.sites:
            if len(s.shorelines) < 2:
                messagebox.showerror(
                    "Insufficient shorelines",
                    f"Site '{s.name}' needs at least 2 shoreline years.\n"
                    "Add them in the Sites tab.", parent=self)
                return None
            sl_years = [
                ShorelineYear(
                    year=sl.year, path=sl.path,
                    rmse95_override=sl.rmse95,
                    acquisition_date=sl.acq_date)
                for sl in s.shorelines
            ]
            site_cfgs.append(SiteConfig(
                name=s.name,
                shorelines=sl_years,
                transect_spacing=s.transect_spacing,
                transect_length=s.transect_length,
                coordinate_priority=s.coord_priority,
            ))

        try:
            sig = float(self._sig.get())
        except ValueError:
            messagebox.showerror("Invalid value",
                                 "Significance threshold must be a number.", parent=self)
            return None
        try:
            cell = float(self._cell.get())
        except ValueError:
            messagebox.showerror("Invalid value",
                                 "Raster cell size must be a number.", parent=self)
            return None
        try:
            conf = [float(x.strip())
                    for x in self._conf.get().split(",") if x.strip()]
        except ValueError:
            messagebox.showerror("Invalid value",
                                 "Confidence levels must be comma-separated numbers.", parent=self)
            return None
        try:
            seg_len = float(self._seg_len.get())
        except ValueError:
            seg_len = 50.0

        crs = self._crs.get().strip() or None

        if not crs:
            import logging
            logging.getLogger(__name__).warning(
                "No Target CRS specified. SURF will attempt to auto-detect a common "
                "CRS, but if your shapefiles are in different coordinate systems "
                "(common with historical scans) results may be incorrect. "
                "Set a Target CRS (e.g. EPSG:3175) in the Settings tab."
            )

        return RunConfig(
            output_dir=out_dir,
            sites=site_cfgs,
            target_crs=crs,
            confidence_levels=conf,
            significance_threshold=sig,
            epsilon_band_method=self._eps_method.get(),
            export_intersect_geometries=self._export_int.get(),
            raster_cell_size=cell,
            compute_prob_change=self._prob.get(),
            prob_change_segment_length=seg_len,
            compute_rate_of_change=self._rate.get(),
        )

    # ------------------------------------------------------------------ #
    # YAML import / export                                                 #
    # ------------------------------------------------------------------ #

    def _save_yaml(self):
        if not _HAS_YAML:
            messagebox.showerror(
                "PyYAML not found",
                "Install PyYAML:\n  pip install pyyaml", parent=self)
            return
        cfg = self._collect_config()
        if cfg is None:
            return
        p = filedialog.asksaveasfilename(
            parent=self, defaultextension=".yaml",
            filetypes=[("YAML files", "*.yaml *.yml"), ("All files", "*.*")],
            title="Save YAML configuration")
        if not p:
            return
        d = self._config_to_dict(cfg)
        Path(p).write_text(
            _yaml.dump(d, default_flow_style=False, allow_unicode=True),
            encoding="utf-8")
        self._status.set(f"Config saved to {p}")

    def _load_yaml(self):
        if not _HAS_YAML:
            messagebox.showerror(
                "PyYAML not found",
                "Install PyYAML:\n  pip install pyyaml", parent=self)
            return
        p = filedialog.askopenfilename(
            parent=self, title="Open YAML configuration",
            filetypes=[("YAML files", "*.yaml *.yml"), ("All files", "*.*")])
        if not p:
            return
        try:
            raw = _yaml.safe_load(Path(p).read_text(encoding="utf-8"))
            self._populate_from_dict(raw)
            self._status.set(f"Loaded {p}")
        except Exception as exc:
            messagebox.showerror("Load failed", str(exc), parent=self)

    @staticmethod
    def _config_to_dict(cfg: "RunConfig") -> dict:
        d: dict = {
            "output_dir": cfg.output_dir,
            "significance_threshold": cfg.significance_threshold,
            "epsilon_band_method": cfg.epsilon_band_method,
            "raster_cell_size": cfg.raster_cell_size,
            "confidence_levels": list(cfg.confidence_levels),
            "export_intersect_geometries": cfg.export_intersect_geometries,
            "compute_prob_change": cfg.compute_prob_change,
            "prob_change_segment_length": cfg.prob_change_segment_length,
            "compute_rate_of_change": cfg.compute_rate_of_change,
        }
        if cfg.target_crs:
            d["target_crs"] = cfg.target_crs
        d["sites"] = []
        for s in cfg.sites:
            sd: dict = {
                "name": s.name,
                "transect_spacing": s.transect_spacing,
                "transect_length": s.transect_length,
                "coordinate_priority": s.coordinate_priority,
                "shorelines": [],
            }
            for sl in s.shorelines:
                sld: dict = {"year": sl.year, "path": sl.path}
                if sl.rmse95_override is not None:
                    sld["rmse95_override"] = sl.rmse95_override
                if sl.acquisition_date:
                    sld["acquisition_date"] = sl.acquisition_date
                sd["shorelines"].append(sld)
            d["sites"].append(sd)
        return d

    def _populate_from_dict(self, d: dict):
        self.sites.clear()
        self._site_lb.delete(0, "end")
        self._cur_site = -1

        self._out_dir.set(d.get("output_dir", ""))
        self._crs.set(d.get("target_crs", "") or "")
        self._sig.set(str(d.get("significance_threshold", 0.01)))
        self._eps_method.set((d.get("epsilon_band_method", "odb") or "odb").lower())
        self._cell.set(str(d.get("raster_cell_size", 0.5)))
        self._export_int.set(bool(d.get("export_intersect_geometries", False)))
        self._prob.set(bool(d.get("compute_prob_change", False)))
        self._seg_len.set(str(d.get("prob_change_segment_length", 50.0)))
        self._rate.set(bool(d.get("compute_rate_of_change", False)))
        conf = d.get("confidence_levels", [0.5, 0.9, 0.95])
        self._conf.set(", ".join(str(c) for c in conf))
        self._toggle_prob()

        for sd in d.get("sites", []):
            sls = [
                _ShorelineRow(
                    year=int(x["year"]), path=x.get("path", ""),
                    rmse95=x.get("rmse95_override"),
                    acq_date=x.get("acquisition_date"))
                for x in sd.get("shorelines", [])
            ]
            self.sites.append(_SiteRow(
                name=sd.get("name", "site"),
                transect_spacing=float(sd.get("transect_spacing", 10.0)),
                transect_length=float(sd.get("transect_length", 300.0)),
                coord_priority=(sd.get("coordinate_priority", "UPPER_LEFT") or "UPPER_LEFT").upper(),
                shorelines=sls,
            ))
            self._site_lb.insert("end", self.sites[-1].name)

        if self.sites:
            self._site_lb.selection_set(0)
            self._cur_site = 0
            self._load_site_detail(0)
        else:
            self._load_site_detail(-1)

    # ------------------------------------------------------------------ #
    # New / About                                                          #
    # ------------------------------------------------------------------ #

    def _new(self):
        if not messagebox.askyesno("New", "Clear current configuration?", parent=self):
            return
        self._populate_from_dict({})
        self._status.set("Ready.")

    def _about(self):
        pkg_ver = "not installed"
        if _HAS_PKG:
            try:
                from importlib.metadata import version
                pkg_ver = version("surf")
            except Exception:
                pkg_ver = "installed"
        messagebox.showinfo(
            APP_TITLE,
            f"{APP_TITLE}\n\n"
            f"surf  v{pkg_ver}\n\n"
            "RMSE-based positional uncertainty and\n"
            "rate-of-change analysis for digitized shorelines.\n\n"
            "Based on Wernette et al. (2017, 2020).\n\n"
            "Run:    python -m gui_app\n"
            "Build:  python gui_app/build_exe.py",
            parent=self)

    def _warn_no_package(self):
        messagebox.showwarning(
            "Package not installed",
            "surf is not installed.\n\n"
            "Install from the repo root:\n"
            "  pip install -e .\n\n"
            "Config editing and YAML save/load are available,\n"
            "but Run Analysis will be disabled.",
            parent=self)


# ---------------------------------------------------------------------------
# Logging handler that forwards records to the GUI queue
# ---------------------------------------------------------------------------

class _QueueHandler(logging.Handler):
    def __init__(self, q: queue.Queue):
        super().__init__()
        self._q = q

    def emit(self, record: logging.LogRecord):
        try:
            self._q.put(self.format(record))
        except Exception:
            self.handleError(record)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Launch the SURF GUI application."""
    import logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)-5s %(message)s")
    app = SURFApp()
    app.mainloop()


if __name__ == "__main__":
    main()
