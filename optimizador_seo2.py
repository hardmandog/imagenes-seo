# -*- coding: utf-8 -*-
# OPTIMIZADOR SEO – v3 FINAL
# GUI: edición por archivo de metadatos + vista previa + hotfixes robustos
# Autor: Armando (HardmanDog)
# Fecha: 2025-10-20
#
# Requisitos:
#   python -m pip install pillow
#   (opcional DnD) python -m pip install tkinterdnd2
#   Instalar ExifTool y poner su ruta (ej. C:\Tools\exiftool.exe)
#
# Empaquetar a .exe:
#   pyinstaller --noconfirm --onefile --windowed --name "OPTIMIZADOR_SEO" optimizador_seo_v3_final.py

import os
import io
import subprocess
from pathlib import Path
from typing import Optional, Tuple

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Drag & Drop opcional
DND_AVAILABLE = True
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
except Exception:
    DND_AVAILABLE = False

# --- PIL con fallbacks seguros ---
from PIL import Image, ImageTk, UnidentifiedImageError

# Resampling fallback (para Pillow < 9.1)
if hasattr(Image, "Resampling"):
    RESAMPLE = Image.Resampling.LANCZOS
else:
    RESAMPLE = Image.LANCZOS  # compatibilidad antigua

# ImageCms opcional (muchos builds no traen LCMS)
HAS_CMS = True
try:
    from PIL import ImageCms
except Exception:
    HAS_CMS = False

APP_TITLE = "OPTIMIZADOR SEO – v3 FINAL"
SUPPORTED_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
DEFAULT_JPG_QUALITY = 86
DEFAULT_WEBP_QUALITY = 82


# ---------- utilidades de imagen ----------
def to_srgb(img: Image.Image) -> Image.Image:
    """Convierte a sRGB si hay perfil ICC. Si no hay CMS, cae a .convert('RGB') sin reventar."""
    try:
        if img.mode == "CMYK":
            img = img.convert("RGB")
        if HAS_CMS and "icc_profile" in img.info and img.info["icc_profile"]:
            try:
                src = ImageCms.ImageCmsProfile(io.BytesIO(img.info["icc_profile"]))
                dst = ImageCms.createProfile("sRGB")
                img = ImageCms.profileToProfile(img, src, dst, outputMode="RGB")
            except Exception:
                if img.mode != "RGB":
                    img = img.convert("RGB")
        else:
            if img.mode != "RGB":
                img = img.convert("RGB")
    except Exception:
        if img.mode != "RGB":
            img = img.convert("RGB")
    return img


def force_white_background_if_transparent(img: Image.Image) -> Image.Image:
    """Si hay canal alfa, lo aplana sobre #FFFFFF."""
    if "A" in img.getbands():
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def resize_if_needed(img: Image.Image, max_w: int, max_h: int) -> Image.Image:
    """Reduce manteniendo aspecto si supera límites. No hace upscale."""
    if max_w <= 0 and max_h <= 0:
        return img
    w, h = img.size
    scale = 1.0
    if max_w > 0 and w > max_w:
        scale = min(scale, max_w / w)
    if max_h > 0 and h > max_h:
        scale = min(scale, max_h / h)
    if scale < 1.0:
        nw, nh = int(w * scale), int(h * scale)
        img = img.resize((nw, nh), RESAMPLE)
    return img


# ---------- metadatos / exiftool ----------
def run_exiftool(args_list):
    try:
        subprocess.run(args_list, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, shell=False)
    except Exception as e:
        print("EXIFTOOL ERROR:", e)


def clean_all_metadata(exiftool_path: str, target_path: Path):
    # Borra TODOS los metadatos (EXIF/XMP/IPTC)
    run_exiftool([exiftool_path, "-overwrite_original", "-all=", str(target_path)])


def set_dpi_96(exiftool_path: str, target_path: Path):
    run_exiftool([exiftool_path, "-overwrite_original",
                  "-XResolution=96", "-YResolution=96", "-ResolutionUnit=inches", str(target_path)])


def write_metadata_full(
    exiftool_path: str, target_path: Path,
    author: str, title: str, desc: str,
    copyright_note: str, license_url: str,
    keywords_csv: str, alt_text: str,
    gps_lat: str, gps_lon: str, gps_alt: str
):
    args = [exiftool_path, "-overwrite_original"]

    # Autor / Crédito
    if author.strip():
        args += [
            f"-IPTC:Creator={author}", f"-IPTC:Credit={author}",
            f"-XMP-dc:creator={author}",
            f"-IFD0:Artist={author}", f"-EXIF:XPAuthor={author}",
        ]

    # Título
    if title.strip():
        args += [f"-XMP:Title={title}", f"-IPTC:ObjectName={title}", f"-EXIF:XPTitle={title}"]

    # Descripción
    if desc.strip():
        args += [
            f"-XMP-dc:description={desc}", f"-XMP:Description={desc}",
            f"-IPTC:Caption-Abstract={desc}", f"-EXIF:XPComment={desc}"
        ]

    # ALT (accesibilidad) — no estándar EXIF clásico, pero soportado en XMP moderno
    if alt_text.strip():
        args += [f"-XMP:AltTextAccessibility={alt_text}"]

    # Copyright / Licencia
    if copyright_note.strip():
        args += [
            f"-IPTC:CopyrightNotice={copyright_note}",
            f"-XMP-dc:rights={copyright_note}",
            f"-IFD0:Copyright={copyright_note}",
        ]
    if license_url.strip():
        args += [f"-XMP-xmpRights:WebStatement={license_url}", f"-XMP:UsageTerms={license_url}"]

    # Keywords
    kw = [k.strip() for k in keywords_csv.split(",")] if keywords_csv else []
    kw = [k for k in kw if k]
    if kw:
        for k in kw:
            args += [f"-IPTC:Keywords+={k}", f"-XMP-dc:subject+={k}"]
        args += [f"-EXIF:XPKeywords={', '.join(kw)}"]

    # GPS
    def gps_ref_val(val_str, lat=True):
        if not val_str.strip():
            return None, None
        try:
            v = float(val_str.strip())
        except ValueError:
            return None, None
        ref = ("N" if v >= 0 else "S") if lat else ("E" if v >= 0 else "W")
        return ref, abs(v)

    lat_ref, lat_val = gps_ref_val(gps_lat, lat=True)
    lon_ref, lon_val = gps_ref_val(gps_lon, lat=False)
    if lat_ref and lon_ref:
        args += [f"-EXIF:GPSLatitudeRef={lat_ref}", f"-EXIF:GPSLatitude={lat_val}",
                 f"-EXIF:GPSLongitudeRef={lon_ref}", f"-EXIF:GPSLongitude={lon_val}"]
        if gps_alt.strip():
            try:
                args += [f"-EXIF:GPSAltitude={float(gps_alt.strip())}"]
            except ValueError:
                pass

    args += [str(target_path)]
    run_exiftool(args)


def show_metadata_in_log(exiftool_path: str, target_path: Path) -> str:
    fields = ["Artist","XPAuthor","XPTitle","XPComment","XPKeywords","Copyright",
              "Creator","Title","Description","Caption-Abstract","Rights",
              "AltTextAccessibility","GPSLatitude","GPSLongitude","GPSAltitude",
              "XResolution","YResolution"]
    cmd = [exiftool_path, "-G1", "-a", "-s"] + [f"-{f}" for f in fields] + [str(target_path)]
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           check=False, shell=False, encoding="utf-8", errors="ignore")
        return p.stdout if p.stdout else p.stderr
    except Exception as e:
        return f"ERROR al leer metadatos: {e}"


# ---------- guardado ----------
def save_master_files(
    in_path: Path, out_dir: Path,
    jpg_q: int, webp_q: int,
    convert_png_to_jpg: bool,
    force_white_bg: bool,
    max_w: int, max_h: int,
    overwrite: bool,
    final_stem: Optional[str] = None
) -> Tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = (final_stem or in_path.stem).strip() or in_path.stem
    ext = in_path.suffix.lower()
    jpg_path = out_dir / f"{stem}.jpg"
    webp_path = out_dir / f"{stem}.webp"

    if (not overwrite) and jpg_path.exists():
        raise RuntimeError(f"Ya existe: {jpg_path.name} (activa 'Sobrescribir' o usa otro nombre)")

    try:
        img = Image.open(in_path)
    except UnidentifiedImageError:
        raise RuntimeError(f"No se pudo abrir: {in_path.name}")

    if ext in {".png", ".tif", ".tiff"} and force_white_bg:
        img = force_white_background_if_transparent(img)
    img = to_srgb(img)
    img = resize_if_needed(img, max_w=max_w, max_h=max_h)

    img.save(jpg_path, format="JPEG", quality=jpg_q, optimize=True, progressive=True)
    return jpg_path, webp_path


# ---------- GUI ----------
class App:
    COLS = ("ruta", "final_name", "title", "alt", "desc", "keywords")

    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1350x760")
        self.root.minsize(1200, 680)

        # Vars generales
        self.var_exiftool = tk.StringVar(value="exiftool" if os.name != "nt" else r"C:\Tools\exiftool.exe")
        self.var_outdir = tk.StringVar(value=str(Path.cwd() / "salida"))
        self.var_overwrite = tk.BooleanVar(value=True)
        self.var_keep_original = tk.BooleanVar(value=True)
        self.var_convert_png = tk.BooleanVar(value=True)
        self.var_force_white = tk.BooleanVar(value=True)
        self.var_make_webp = tk.BooleanVar(value=True)
        self.var_clean_ai = tk.BooleanVar(value=True)
        self.var_set_dpi96 = tk.BooleanVar(value=True)
        self.var_rename_after_meta = tk.BooleanVar(value=True)
        self.var_jpg_q = tk.IntVar(value=DEFAULT_JPG_QUALITY)
        self.var_webp_q = tk.IntVar(value=DEFAULT_WEBP_QUALITY)
        self.var_max_w = tk.IntVar(value=1600)
        self.var_max_h = tk.IntVar(value=0)

        # Metadatos por defecto (lote)
        self.var_author = tk.StringVar(value="DecoTech Publicidad")
        self.var_title = tk.StringVar(value="")
        self.var_desc = tk.StringVar(value="")
        self.var_copyright = tk.StringVar(value="© 2025 DecoTech Publicidad. Todos los derechos reservados.")
        self.var_license = tk.StringVar(value="https://tudominio.com/licencias/uso-de-imagenes")
        self.var_keywords = tk.StringVar(value="letreros, acrilico, oficina, lima")
        self.var_alt = tk.StringVar(value="")  # ALT por defecto

        # GPS
        self.var_lat = tk.StringVar(value="")
        self.var_lon = tk.StringVar(value="")
        self.var_alt_m = tk.StringVar(value="")

        # Datos por fila
        # row_data[iid] = {"final_name":..., "title":..., "alt":..., "desc":..., "keywords":...}
        self.row_data = {}
        self._edit_entry = None
        self._popup = None
        self._preview_imgtk = None

        # Panel lateral de edición rápida (bindeado a la selección)
        self.var_side_name = tk.StringVar("")
        self.var_side_title = tk.StringVar("")
        self.var_side_alt = tk.StringVar("")
        self.var_side_desc = tk.StringVar("")
        self.var_side_keywords = tk.StringVar("")

        self.build_ui()
        if not DND_AVAILABLE:
            self.log("Drag & Drop desactivado (instala 'tkinterdnd2' para habilitar).")

    # ----- UI -----
    def build_ui(self):
        top = ttk.LabelFrame(self.root, text="Rutas y opciones")
        top.pack(fill="x", padx=10, pady=8)

        ttk.Label(top, text="ExifTool:").grid(row=0, column=0, sticky="e", padx=6, pady=4)
        ttk.Entry(top, textvariable=self.var_exiftool, width=60).grid(row=0, column=1, sticky="we", padx=6, pady=4)
        ttk.Button(top, text="Buscar...", command=self.pick_exiftool).grid(row=0, column=2, padx=6, pady=4)

        ttk.Label(top, text="Salida:").grid(row=1, column=0, sticky="e", padx=6, pady=4)
        ttk.Entry(top, textvariable=self.var_outdir, width=60).grid(row=1, column=1, sticky="we", padx=6, pady=4)
        ttk.Button(top, text="Seleccionar...", command=self.pick_outdir).grid(row=1, column=2, padx=6, pady=4)

        opt = ttk.Frame(top); opt.grid(row=2, column=0, columnspan=3, sticky="we", padx=6, pady=4)
        for text, var in [
            ("Convertir PNG→JPG", self.var_convert_png),
            ("Fondo #FFFFFF si hay alfa", self.var_force_white),
            ("Generar WEBP", self.var_make_webp),
            ("Eliminar huellas IA (-all=)", self.var_clean_ai),
            ("DPI 96", self.var_set_dpi96),
            ("No borrar original", self.var_keep_original),
            ("Sobrescribir si existe", self.var_overwrite),
            ("Renombrar tras meta (*-meta)", self.var_rename_after_meta),
        ]:
            ttk.Checkbutton(opt, text=text, variable=var).pack(side="left", padx=6)

        qual = ttk.Frame(top); qual.grid(row=3, column=0, columnspan=3, sticky="we", padx=6, pady=4)
        ttk.Label(qual, text="JPG Q:").pack(side="left")
        ttk.Spinbox(qual, from_=60, to=100, textvariable=self.var_jpg_q, width=5).pack(side="left", padx=4)
        ttk.Label(qual, text="WEBP Q:").pack(side="left")
        ttk.Spinbox(qual, from_=60, to=100, textvariable=self.var_webp_q, width=5).pack(side="left", padx=4)
        ttk.Label(qual, text="Máx. Ancho:").pack(side="left", padx=(12,4))
        ttk.Spinbox(qual, from_=0, to=10000, textvariable=self.var_max_w, width=6).pack(side="left")
        ttk.Label(qual, text="Máx. Alto:").pack(side="left", padx=(12,4))
        ttk.Spinbox(qual, from_=0, to=10000, textvariable=self.var_max_h, width=6).pack(side="left")

        for i in range(3): top.columnconfigure(i, weight=1)

        mid = ttk.Frame(self.root); mid.pack(fill="both", expand=True, padx=10, pady=(0,8))

        # ---- Archivos (Treeview con columnas editables) ----
        left = ttk.LabelFrame(mid, text="Archivos")
        left.pack(side="left", fill="both", expand=True, padx=(0,8))

        self.tree = ttk.Treeview(left, columns=self.COLS, show="headings", selectmode="extended")
        self.tree.heading("ruta", text="Archivo (ruta completa)")
        self.tree.heading("final_name", text="Nombre final")
        self.tree.heading("title", text="Título")
        self.tree.heading("alt", text="ALT")
        self.tree.heading("desc", text="Descripción")
        self.tree.heading("keywords", text="Keywords (,)")
        self.tree.column("ruta", width=480, anchor="w")
        self.tree.column("final_name", width=200, anchor="w")
        self.tree.column("title", width=200, anchor="w")
        self.tree.column("alt", width=220, anchor="w")
        self.tree.column("desc", width=260, anchor="w")
        self.tree.column("keywords", width=220, anchor="w")

        yscroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        yscroll.pack(side="left", fill="y")

        self.tree.bind("<Double-1>", self.on_tree_double_click)
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.tree.bind("<F2>", lambda e: self.edit_selected_popup())

        self.ctx = tk.Menu(self.tree, tearoff=0)
        self.ctx.add_command(label="Editar…", command=self.edit_selected_popup)
        self.ctx.add_command(label="Renombrar nombre final…", command=lambda: self.edit_selected_popup(focus="final_name"))
        self.tree.bind("<Button-3>", self.on_right_click)

        if DND_AVAILABLE:
            try:
                self.tree.drop_target_register(DND_FILES)
                self.tree.dnd_bind("<<Drop>>", self.on_drop_files)
            except Exception:
                pass  # si falla, seguimos sin DnD

        fb = ttk.Frame(left); fb.pack(fill="x", padx=6, pady=(0,6))
        ttk.Button(fb, text="Agregar archivos", command=self.add_files).pack(side="left", padx=4)
        ttk.Button(fb, text="Agregar carpeta", command=self.add_folder).pack(side="left", padx=4)
        ttk.Button(fb, text="Quitar seleccionados", command=self.remove_selected).pack(side="left", padx=4)
        ttk.Button(fb, text="Limpiar lista", command=self.clear_list).pack(side="left", padx=4)

        side = ttk.LabelFrame(left, text="Edición rápida seleccionado")
        side.pack(fill="x", padx=6, pady=(0,6))
        self._make_labeled_entry(side, "Nombre:", self.var_side_name, 0)
        self._make_labeled_entry(side, "Título:", self.var_side_title, 1)
        self._make_labeled_entry(side, "ALT:", self.var_side_alt, 2)
        self._make_labeled_entry(side, "Descripción:", self.var_side_desc, 3, width=60)
        self._make_labeled_entry(side, "Keywords (,):", self.var_side_keywords, 4)
        ttk.Button(side, text="Aplicar cambios al seleccionado", command=self.apply_side_edit).grid(row=5, column=0, columnspan=2, pady=6)

        # ---- Vista previa ----
        preview = ttk.LabelFrame(mid, text="Vista previa")
        preview.pack(side="left", fill="y", padx=(0,8))
        self.preview_canvas = tk.Canvas(preview, width=300, height=300, bg="#ffffff",
                                        highlightthickness=1, highlightbackground="#999")
        self.preview_canvas.pack(padx=6, pady=6)
        self.preview_canvas.create_text(150, 150, text="(sin vista previa)", fill="#666", font=("Segoe UI", 9))

        # ---- Metadatos por defecto / GPS ----
        right = ttk.LabelFrame(mid, text="Metadatos por defecto (si una fila está vacía se toma de aquí)")
        right.pack(side="left", fill="both", expand=True)

        g = ttk.Frame(right); g.pack(fill="x", padx=8, pady=4)
        self._make_labeled_entry(g, "Autor/Crédito:", self.var_author, 0)
        self._make_labeled_entry(g, "Título (def.):", self.var_title, 1)
        self._make_labeled_entry(g, "ALT (def.):", self.var_alt, 2)
        self._make_labeled_entry(g, "Descripción (def.):", self.var_desc, 3, width=60)
        self._make_labeled_entry(g, "Keywords (def., ,):", self.var_keywords, 4)
        self._make_labeled_entry(g, "Copyright:", self.var_copyright, 5, width=60)
        self._make_labeled_entry(g, "Licencia (URL):", self.var_license, 6, width=60)

        gps = ttk.LabelFrame(right, text="GPS (opcional)"); gps.pack(fill="x", padx=8, pady=6)
        self._make_labeled_entry(gps, "Lat:", self.var_lat, 0, width=12)
        self._make_labeled_entry(gps, "Lon:", self.var_lon, 1, width=12)
        self._make_labeled_entry(gps, "Alt (m):", self.var_alt_m, 2, width=8)

        # Ejecutar
        run = ttk.Frame(self.root); run.pack(fill="x", padx=10, pady=6)
        self.progress = ttk.Progressbar(run, orient="horizontal", mode="determinate")
        self.progress.pack(fill="x", side="left", expand=True, padx=(0,6))
        ttk.Button(run, text="Procesar", command=self.process).pack(side="left")
        ttk.Button(run, text="Ver metadatos del seleccionado", command=self.view_selected_meta).pack(side="left", padx=(6,0))

        # Log
        logf = ttk.LabelFrame(self.root, text="Registro"); logf.pack(fill="both", expand=True, padx=10, pady=(0,10))
        self.txt = tk.Text(logf, height=10)
        self.txt.pack(fill="both", expand=True, padx=6, pady=6)

    def _make_labeled_entry(self, parent, label, var, row, width=40):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="e", padx=4, pady=3)
        ttk.Entry(parent, textvariable=var, width=width).grid(row=row, column=1, sticky="we", padx=4, pady=3)
        parent.columnconfigure(1, weight=1)

    # ---- helpers UI ----
    def log(self, msg: str):
        self.txt.insert("end", msg + "\n")
        self.txt.see("end")
        self.root.update_idletasks()

    def pick_exiftool(self):
        p = filedialog.askopenfilename(title="Selecciona exiftool.exe o exiftool",
                                       filetypes=[("Ejecutable", "*.*")])
        if p: self.var_exiftool.set(p)

    def pick_outdir(self):
        d = filedialog.askdirectory(title="Selecciona carpeta de salida")
        if d: self.var_outdir.set(d)

    # ---- archivos y datos por fila ----
    def _add(self, p: Path):
        if not p.exists() or p.suffix.lower() not in SUPPORTED_EXT:
            return
        iid = str(p.resolve())
        if iid in self.row_data:
            return
        self.row_data[iid] = {"final_name": p.stem, "title": "", "alt": "", "desc": "", "keywords": ""}
        self.tree.insert("", "end", iid=iid, values=(iid, p.stem, "", "", "", ""))
        if len(self.tree.get_children()) == 1:
            self.draw_preview(p)
            self._sync_side_from_row(iid)

    def add_files(self):
        paths = filedialog.askopenfilenames(title="Agregar imágenes",
            filetypes=[("Imágenes", "*.jpg;*.jpeg;*.png;*.tif;*.tiff;*.webp")])
        for p in paths: self._add(Path(p))

    def add_folder(self):
        d = filedialog.askdirectory(title="Agregar carpeta")
        if not d: return
        for p in Path(d).rglob("*"):
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXT:
                self._add(p)

    def on_drop_files(self, event):
        for raw in self.root.splitlist(event.data):
            p = Path(raw)
            if p.is_dir():
                for f in p.rglob("*"):
                    if f.is_file() and f.suffix.lower() in SUPPORTED_EXT:
                        self._add(f)
            else:
                self._add(p)

    def remove_selected(self):
        for iid in self.tree.selection():
            try: del self.row_data[iid]
            except KeyError: pass
            self.tree.delete(iid)
        if not self.tree.selection():
            self._clear_preview()
            self._clear_side()

    def clear_list(self):
        for iid in self.tree.get_children(): self.tree.delete(iid)
        self.row_data.clear()
        self._clear_preview(); self._clear_side()

    # ---- edición inline / popup / lateral ----
    def on_right_click(self, event):
        row = self.tree.identify_row(event.y)
        if row:
            if row not in self.tree.selection():
                self.tree.selection_set(row)
            self.ctx.tk_popup(event.x_root, event.y_root)

    def on_tree_double_click(self, event):
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell": return
        col = self.tree.identify_column(event.x)  # '#1'..'#6'
        row = self.tree.identify_row(event.y)
        if not row or col == "#1":  # no editamos 'ruta'
            return
        try:
            x, y, w, h = self.tree.bbox(row, col)
        except Exception:
            return self.edit_selected_popup()

        col_key = self.COLS[int(col[1:]) - 1]
        val_actual = self.tree.set(row, col_key)

        if self._edit_entry is not None:
            try: self._edit_entry.destroy()
            except: pass
        self._edit_entry = tk.Entry(self.tree)
        self._edit_entry.insert(0, val_actual)
        self._edit_entry.select_range(0, tk.END)
        self._edit_entry.focus()
        self._edit_entry.place(x=x, y=y, width=w, height=h)

        def commit(e=None):
            nuevo = self._edit_entry.get().strip()
            self._apply_cell_edit(row, col_key, nuevo)
            try: self._edit_entry.destroy()
            except: pass
            self._edit_entry = None

        def cancel(e=None):
            try: self._edit_entry.destroy()
            except: pass
            self._edit_entry = None

        self._edit_entry.bind("<Return>", commit)
        self._edit_entry.bind("<Escape>", cancel)
        self._edit_entry.bind("<FocusOut>", commit)

    def _apply_cell_edit(self, iid: str, col_key: str, value: str):
        # Sanitiza nombre final
        if col_key == "final_name":
            v = value or self.row_data[iid]["final_name"]
            v = v.replace("/", "-").replace("\\", "-")
            if "." in v: v = v.rsplit(".", 1)[0]
            self.row_data[iid]["final_name"] = v
            self.tree.set(iid, "final_name", v)
            if iid in self.tree.selection():
                self.var_side_name.set(v)
            return
        # Otras columnas
        self.row_data[iid][col_key] = value
        self.tree.set(iid, col_key, value)
        if iid in self.tree.selection():
            if col_key == "title": self.var_side_title.set(value)
            elif col_key == "alt": self.var_side_alt.set(value)
            elif col_key == "desc": self.var_side_desc.set(value)
            elif col_key == "keywords": self.var_side_keywords.set(value)

    def edit_selected_popup(self, focus=None):
        sel = self.tree.selection()
        if not sel: return
        iid = sel[0]
        data = self.row_data.get(iid, {})
        win = tk.Toplevel(self.root); win.title("Editar metadatos"); win.transient(self.root); win.resizable(False, False); win.grab_set()

        v_name = tk.StringVar(value=data.get("final_name",""))
        v_title = tk.StringVar(value=data.get("title",""))
        v_alt = tk.StringVar(value=data.get("alt",""))
        v_desc = tk.StringVar(value=data.get("desc",""))
        v_keys = tk.StringVar(value=data.get("keywords",""))

        def mk(row, label, var, width=56):
            ttk.Label(win, text=label).grid(row=row, column=0, sticky="e", padx=6, pady=4)
            e = ttk.Entry(win, textvariable=var, width=width); e.grid(row=row, column=1, sticky="we", padx=6, pady=4); return e

        e1 = mk(0,"Nombre final:", v_name, 40)
        e2 = mk(1,"Título:", v_title)
        e3 = mk(2,"ALT:", v_alt)
        e4 = mk(3,"Descripción:", v_desc)
        e5 = mk(4,"Keywords (,):", v_keys)

        btnf = ttk.Frame(win); btnf.grid(row=5, column=0, columnspan=2, pady=8)
        def ok():
            self._apply_cell_edit(iid, "final_name", v_name.get().strip())
            self._apply_cell_edit(iid, "title", v_title.get().strip())
            self._apply_cell_edit(iid, "alt", v_alt.get().strip())
            self._apply_cell_edit(iid, "desc", v_desc.get().strip())
            self._apply_cell_edit(iid, "keywords", v_keys.get().strip())
            win.destroy()
        ttk.Button(btnf, text="Aceptar", command=ok).pack(side="left", padx=6)
        ttk.Button(btnf, text="Cancelar", command=win.destroy).pack(side="left", padx=6)

        if focus == "final_name": e1.focus_set()
        else: e2.focus_set()

    def apply_side_edit(self):
        sel = self.tree.selection()
        if not sel: return
        iid = sel[0]
        self._apply_cell_edit(iid, "final_name", self.var_side_name.get().strip())
        self._apply_cell_edit(iid, "title", self.var_side_title.get().strip())
        self._apply_cell_edit(iid, "alt", self.var_side_alt.get().strip())
        self._apply_cell_edit(iid, "desc", self.var_side_desc.get().strip())
        self._apply_cell_edit(iid, "keywords", self.var_side_keywords.get().strip())

    def _sync_side_from_row(self, iid: str):
        d = self.row_data.get(iid, {})
        self.var_side_name.set(d.get("final_name",""))
        self.var_side_title.set(d.get("title",""))
        self.var_side_alt.set(d.get("alt",""))
        self.var_side_desc.set(d.get("desc",""))
        self.var_side_keywords.set(d.get("keywords",""))

    # ---- preview ----
    def _clear_preview(self):
        self.preview_canvas.delete("all")
        self.preview_canvas.create_text(150, 150, text="(sin vista previa)", fill="#666", font=("Segoe UI", 9))
        self._preview_imgtk = None

    def _clear_side(self):
        self.var_side_name.set(""); self.var_side_title.set(""); self.var_side_alt.set("")
        self.var_side_desc.set(""); self.var_side_keywords.set("")

    def draw_preview(self, path: Path):
        self.preview_canvas.delete("all")
        w, h = 300, 300
        self.preview_canvas.create_rectangle(1, 1, w - 1, h - 1, outline="#999", fill="#ffffff")
        if not path.exists():
            self.preview_canvas.create_text(w//2, h//2, text="(Archivo no existe)", fill="#a00", font=("Segoe UI", 9))
            self._preview_imgtk = None; return
        try:
            img = Image.open(path)
            img = force_white_background_if_transparent(to_srgb(img))
            img.thumbnail((288, 288), RESAMPLE)
            self._preview_imgtk = ImageTk.PhotoImage(img)
            x = (w - img.width) // 2; y = (h - img.height) // 2
            self.preview_canvas.create_image(x, y, image=self._preview_imgtk, anchor="nw")
        except Exception:
            self.preview_canvas.create_text(w//2, h//2, text="(No se puede mostrar)", fill="#a00", font=("Segoe UI", 9))
            self._preview_imgtk = None

    def on_tree_select(self, event):
        sel = self.tree.selection()
        if not sel:
            self._clear_preview(); self._clear_side(); return
        iid = sel[0]
        self.draw_preview(Path(iid))
        self._sync_side_from_row(iid)

    # ---- ver metadatos de la salida ----
    def view_selected_meta(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Ver metadatos", "Selecciona un archivo (de salida) en la lista.")
            return
        iid = sel[0]
        outdir = Path(self.var_outdir.get().strip())
        final_stem = (self.row_data.get(iid, {}).get("final_name") or Path(iid).stem).strip()
        candidate = outdir / f"{final_stem}-meta.jpg"
        target = candidate if candidate.exists() else (outdir / f"{final_stem}.jpg")
        if not target.exists():
            messagebox.showwarning("Ver metadatos", f"No encuentro salida: {target.name}")
            return
        info = show_metadata_in_log(self.var_exiftool.get().strip(), target)
        self.log("--- METADATOS ---\n" + info.strip() + "\n------------------")

    # ---- proceso principal ----
    def _merge_defaults(self, d: dict) -> dict:
        # Si está vacío en la fila, cae al valor por defecto global
        return {
            "final_name": d.get("final_name","").strip() or "",
            "title": (d.get("title","").strip() or self.var_title.get().strip()),
            "alt": (d.get("alt","").strip() or self.var_alt.get().strip()),
            "desc": (d.get("desc","").strip() or self.var_desc.get().strip()),
            "keywords": (d.get("keywords","").strip() or self.var_keywords.get().strip()),
        }

    def process(self):
        items = list(self.tree.get_children())
        if not items:
            messagebox.showwarning("Atención", "Agrega imágenes primero."); return

        exiftool = self.var_exiftool.get().strip()
        if not exiftool:
            messagebox.showwarning("Atención", "Indica la ruta de ExifTool."); return

        outdir = Path(self.var_outdir.get().strip()); outdir.mkdir(parents=True, exist_ok=True)

        overwrite = self.var_overwrite.get()
        keep_original = self.var_keep_original.get()
        convert_png = self.var_convert_png.get()
        force_white = self.var_force_white.get()
        make_webp = self.var_make_webp.get()
        clean_ai = self.var_clean_ai.get()
        set_dpi96 = self.var_set_dpi96.get()
        rename_after_meta = self.var_rename_after_meta.get()

        jpg_q = int(self.var_jpg_q.get()); webp_q = int(self.var_webp_q.get())
        max_w = int(self.var_max_w.get()); max_h = int(self.var_max_h.get())

        author = self.var_author.get().strip()
        copyright_note = self.var_copyright.get().strip()
        license_url = self.var_license.get().strip()
        gps_lat = self.var_lat.get().strip(); gps_lon = self.var_lon.get().strip(); gps_alt = self.var_alt_m.get().strip()

        total = len(items); self.progress["maximum"] = total; self.progress["value"] = 0
        ok, fail = 0, 0

        for idx, iid in enumerate(items, start=1):
            src = Path(iid)
            try:
                merged = self._merge_defaults(self.row_data.get(iid, {}))
                final_stem = merged["final_name"] or src.stem

                # Guardar JPG maestro (+ reserva WEBP)
                jpg_path, webp_path = save_master_files(
                    in_path=src, out_dir=outdir,
                    jpg_q=jpg_q, webp_q=webp_q,
                    convert_png_to_jpg=convert_png,
                    force_white_bg=force_white,
                    max_w=max_w, max_h=max_h,
                    overwrite=overwrite,
                    final_stem=final_stem
                )

                # WEBP
                webp_done = None
                if make_webp:
                    try:
                        im = Image.open(jpg_path); im = to_srgb(im)
                        im.save(webp_path, format="WEBP", quality=webp_q, method=6)
                        webp_done = webp_path
                    except Exception as e:
                        self.log(f"[{idx}/{total}] WEBP falló: {src.name} → {e}")

                # Limpieza metadatos (huellas IA)
                if clean_ai:
                    clean_all_metadata(exiftool, jpg_path)
                    if webp_done and webp_done.exists():
                        clean_all_metadata(exiftool, webp_done)

                # DPI 96
                if set_dpi96:
                    set_dpi_96(exiftool, jpg_path)
                    if webp_done and webp_done.exists():
                        set_dpi_96(exiftool, webp_done)

                # Escribir metadatos finales (por-archivo OR defaults)
                write_metadata_full(
                    exiftool, jpg_path,
                    author=author,
                    title=merged["title"], desc=merged["desc"],
                    copyright_note=copyright_note, license_url=license_url,
                    keywords_csv=merged["keywords"], alt_text=merged["alt"],
                    gps_lat=gps_lat, gps_lon=gps_lon, gps_alt=gps_alt
                )
                if webp_done and webp_done.exists():
                    write_metadata_full(
                        exiftool, webp_done,
                        author=author,
                        title=merged["title"], desc=merged["desc"],
                        copyright_note=copyright_note, license_url=license_url,
                        keywords_csv=merged["keywords"], alt_text=merged["alt"],
                        gps_lat=gps_lat, gps_lon=gps_lon, gps_alt=gps_alt
                    )

                # Renombrar para refrescar caché de Windows
                final_jpg = jpg_path
                if rename_after_meta:
                    rn = jpg_path.with_name(jpg_path.stem + "-meta" + jpg_path.suffix)
                    try:
                        if rn.exists(): rn.unlink()
                        jpg_path.rename(rn); final_jpg = rn
                    except Exception as e:
                        self.log(f"[{idx}/{total}] Renombrado post-meta falló: {e}")

                # Borrar original
                if not keep_original:
                    try: src.unlink()
                    except Exception: pass

                ok += 1
                self.log(f"[{idx}/{total}] OK: {src.name} → {final_jpg.name}{' + WEBP' if webp_done else ''}")
            except Exception as e:
                fail += 1
                self.log(f"[{idx}/{total}] ERROR: {src.name} → {e}")

            self.progress["value"] = idx; self.root.update_idletasks()

        self.log(f"--- Terminado. {ok} OK / {fail} errores. Salida: {outdir} ---")
        messagebox.showinfo("Listo", f"Procesado: {ok} OK, {fail} errores.")

    # ---- selección ----
    def on_tree_select(self, event):
        sel = self.tree.selection()
        if not sel:
            self._clear_preview(); self._clear_side(); return
        iid = sel[0]
        self.draw_preview(Path(iid)); self._sync_side_from_row(iid)


def main():
    # Raíz robusta: si TkinterDnD falla, cae a Tk normal
    if DND_AVAILABLE:
        try:
            root = TkinterDnD.Tk()
        except Exception:
            root = tk.Tk()
    else:
        root = tk.Tk()

    # Tema
    style = ttk.Style()
    try:
        if os.name == "nt":
            style.theme_use("vista")
        else:
            style.theme_use(style.theme_names()[0])
    except Exception:
        pass

    App(root)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # Muestra el error en popup para no perder el mensaje si se ejecuta por doble clic
        try:
            messagebox.showerror("Error al iniciar", f"{type(e).__name__}: {e}")
        except Exception:
            print("Error al iniciar:", repr(e))
        raise
