# -*- coding: utf-8 -*-
"""
OPTIMIZADOR SEO – v4.5.2 (scroll global, vista previa fija a la derecha, sin botón flotante)
Windows 10/11 · Python 3.10+

Funciones clave:
- Lote JPG/PNG/TIF/WEBP → exporta JPG (y WEBP opcional), redimensiona, DPI 96, limpia "huellas IA" (-all=), y escribe metadatos:
  Autor/Título/ALT/Descripción/Keywords/Copyright/Licencia/GPS.
- UI robusta: toolbar operativa, log con scroll, DnD opcional, vista previa estable (CMYK/alpha), validaciones, atajos.
- Scroll vertical global (toda la ventana).
- Perfiles JSON persistentes (incluyen rutas, flags, calidades, tamaño, metadatos de lote y por archivo).
- Procesamiento en hilo con cola (no congela UI). Renombrado post-meta con sufijo -meta confiable.

Dependencias mínimas:
    pip install pillow
(opcional)
    pip install tkinterdnd2
ExifTool (configurable en UI):
    C:\Tools\exiftool.exe

Empaquetar:
    pyinstaller --noconfirm --onefile --windowed --name OPTIMIZADOR_SEO optimizador_seo_v452.py
"""

import os, io, json, shutil, subprocess, threading, queue
from pathlib import Path
from typing import Optional, Tuple, Dict, Any

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# ---------- DnD opcional ----------
DND_AVAILABLE = True
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
except Exception:
    DND_AVAILABLE = False

# ---------- ScrolledText ----------
try:
    from tkinter import scrolledtext
    HAS_SCROLLED = True
except Exception:
    HAS_SCROLLED = False

# ---------- Pillow (con fallback de arranque) ----------
MISSING_PIL = False
try:
    from PIL import Image, ImageTk, UnidentifiedImageError
    try:
        from PIL import ImageCms
        HAS_CMS = True
    except Exception:
        HAS_CMS = False
    RESAMPLE = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.LANCZOS)
except Exception:
    MISSING_PIL = True
    Image = None
    ImageTk = None
    UnidentifiedImageError = Exception
    HAS_CMS = False
    RESAMPLE = None

APP_TITLE = "OPTIMIZADOR SEO – v4.5.2"
SUPPORTED_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}
DEFAULT_JPG_QUALITY = 86
DEFAULT_WEBP_QUALITY = 82

# ---------------- util imagen ----------------
def to_srgb(img):
    if MISSING_PIL: return img
    try:
        if img.mode == "CMYK":
            img = img.convert("RGB")
        if HAS_CMS and "icc_profile" in img.info and img.info["icc_profile"]:
            try:
                src = ImageCms.ImageCmsProfile(io.BytesIO(img.info["icc_profile"]))
                dst = ImageCms.createProfile("sRGB")
                img = ImageCms.profileToProfile(img, src, dst, outputMode="RGB")
            except Exception:
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGB")
        else:
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
    except Exception:
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
    return img

def force_white_background_if_transparent(img):
    if MISSING_PIL: return img
    if "A" in img.getbands():
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        return bg
    return img.convert("RGB") if img.mode != "RGB" else img

def resize_if_needed(img, max_w: int, max_h: int):
    if MISSING_PIL: return img
    if max_w <= 0 and max_h <= 0: return img
    w, h = img.size
    scale = 1.0
    if max_w > 0 and w > max_w:
        scale = min(scale, max_w / w)
    if max_h > 0 and h > max_h:
        scale = min(scale, max_h / h)
    if scale < 1.0:
        img = img.resize((max(1,int(w*scale)), max(1,int(h*scale))), RESAMPLE or Image.LANCZOS)
    return img

# ---------------- exiftool ----------------
def run_exiftool(args_list) -> Tuple[int, str, str]:
    try:
        p = subprocess.run(args_list, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           check=False, shell=False, encoding="utf-8", errors="ignore")
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except Exception as e:
        return 1, "", str(e)

def clean_all_metadata(exiftool_path: str, target_path: Path):
    return run_exiftool([exiftool_path, "-overwrite_original", "-all=", str(target_path)])

def set_dpi_96(exiftool_path: str, target_path: Path):
    return run_exiftool([exiftool_path, "-overwrite_original",
                         "-XResolution=96", "-YResolution=96", "-ResolutionUnit=inches", str(target_path)])

def write_metadata_full(
    exiftool_path: str, target_path: Path,
    author: str, title: str, desc: str,
    copyright_note: str, license_url: str,
    keywords_csv: str, alt_text: str,
    gps_lat: str, gps_lon: str, gps_alt: str
):
    args = [exiftool_path, "-overwrite_original"]

    if author:
        args += [
            f"-IPTC:Creator={author}", f"-IPTC:Credit={author}",
            f"-XMP-dc:creator={author}", f"-IFD0:Artist={author}", f"-EXIF:XPAuthor={author}"
        ]
    if title:
        args += [f"-XMP:Title={title}", f"-IPTC:ObjectName={title}", f"-EXIF:XPTitle={title}"]
    if desc:
        args += [
            f"-XMP-dc:description={desc}", f"-XMP:Description={desc}",
            f"-IPTC:Caption-Abstract={desc}", f"-EXIF:XPComment={desc}"
        ]
    if alt_text:
        args += [f"-XMP:AltTextAccessibility={alt_text}"]
    if copyright_note:
        args += [f"-IPTC:CopyrightNotice={copyright_note}",
                 f"-XMP-dc:rights={copyright_note}", f"-IFD0:Copyright={copyright_note}"]
    if license_url:
        args += [f"-XMP-xmpRights:WebStatement={license_url}", f"-XMP:UsageTerms={license_url}"]

    kw = [k.strip() for k in (keywords_csv or "").split(",") if k.strip()]
    if kw:
        for k in kw:
            args += [f"-IPTC:Keywords+={k}", f"-XMP-dc:subject+={k}"]
        args += [f"-EXIF:XPKeywords={', '.join(kw)}"]

    # GPS helpers
    def gps_ref_val(val_str, lat=True):
        s = (val_str or "").strip()
        if not s: return None, None
        try:
            v = float(s)
        except ValueError:
            return None, None
        ref = ("N" if v >= 0 else "S") if lat else ("E" if v >= 0 else "W")
        return ref, abs(v)

    lat_ref, lat_val = gps_ref_val(gps_lat, lat=True)
    lon_ref, lon_val = gps_ref_val(gps_lon, lat=False)
    if lat_ref and lon_ref:
        args += [f"-EXIF:GPSLatitudeRef={lat_ref}", f"-EXIF:GPSLatitude={lat_val}",
                 f"-EXIF:GPSLongitudeRef={lon_ref}", f"-EXIF:GPSLongitude={lon_val}"]
        s_alt = (gps_alt or "").strip()
        if s_alt:
            try:
                args += [f"-EXIF:GPSAltitude={float(s_alt)}"]
            except ValueError:
                pass

    args += [str(target_path)]
    return run_exiftool(args)

def show_metadata_dump(exiftool_path: str, target_path: Path) -> str:
    fields = ["Artist","XPAuthor","XPTitle","XPComment","XPKeywords","Copyright",
              "Creator","Title","Description","Caption-Abstract","Rights",
              "AltTextAccessibility","GPSLatitude","GPSLongitude","GPSAltitude",
              "XResolution","YResolution","ResolutionUnit"]
    cmd = [exiftool_path, "-G1", "-a", "-s"] + [f"-{f}" for f in fields] + [str(target_path)]
    code, out, err = run_exiftool(cmd)
    return out if out else err

# ---------------- export ----------------
def export_jpg_and_webp(
    in_path: Path, out_dir: Path,
    jpg_q: int, webp_q: int,
    convert_png_to_jpg: bool,
    force_white_bg: bool,
    max_w: int, max_h: int,
    overwrite: bool,
    final_stem: Optional[str] = None
) -> Tuple[Path, Optional[Path]]:
    """Devuelve (jpg_path, webp_path|None) — aún no aplica metadatos."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = (final_stem or in_path.stem).strip() or in_path.stem
    ext = in_path.suffix.lower()
    jpg_path = out_dir / f"{stem}.jpg"
    webp_path = out_dir / f"{stem}.webp"

    if (not overwrite) and jpg_path.exists():
        raise RuntimeError(f"Ya existe: {jpg_path.name} (activa 'Sobrescribir' o cambia nombre)")

    if MISSING_PIL:
        raise RuntimeError("Pillow no está instalado. Ejecuta: pip install pillow")

    try:
        img = Image.open(in_path)
    except UnidentifiedImageError:
        raise RuntimeError(f"No se pudo abrir: {in_path.name}")

    # Transparencia → fondo blanco si se pide
    if ext in {".png", ".tif", ".tiff", ".webp"} and force_white_bg:
        img = force_white_background_if_transparent(img)
    img = to_srgb(img)
    img = resize_if_needed(img, max_w=max_w, max_h=max_h)

    # Guardar JPG
    img_jpg = img.convert("RGB")  # asegurar
    img_jpg.save(jpg_path, format="JPEG", quality=int(jpg_q), optimize=True, progressive=True)

    # WEBP (opcional; el caller decide si genera o no)
    return jpg_path, webp_path

# ---------------- Scrollable Frame ----------------
class ScrollableWindow(ttk.Frame):
    """Contenedor con scroll vertical global: canvas + scrollbar + frame interno."""
    def __init__(self, master):
        super().__init__(master)
        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.vscroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vscroll.set)

        self.inner = ttk.Frame(self.canvas)
        self.inner_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.canvas.pack(side="left", fill="both", expand=True)
        self.vscroll.pack(side="right", fill="y")

        # Ajustar scrollregion cuando cambie el contenido
        self.inner.bind("<Configure>", self._on_configure)
        self.canvas.bind("<Configure>", self._on_canvas_resize)

        # Rueda del mouse (Windows)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_configure(self, _event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_resize(self, event):
        # Ensancha inner para ocupar el ancho del canvas
        self.canvas.itemconfig(self.inner_id, width=event.width)

    def _on_mousewheel(self, event):
        # Delta positivo = arriba; negativo = abajo
        # Ajuste típico:  -int(event.delta/120) * N
        self.canvas.yview_scroll(-int(event.delta/120)*3, "units")

# ---------------- GUI ----------------
class App:
    COLS = ("ruta", "final_name", "title", "alt", "keywords")

    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)

        # Tamaño por defecto + mínimo
        try:
            if os.name == "nt":
                self.root.state("zoomed")
        except Exception:
            self.root.geometry("1280x780")
        try:
            self.root.minsize(1100, 720)
        except Exception:
            pass

        # Vars de rutas
        self.var_exiftool = tk.StringVar(self.root, r"C:\Tools\exiftool.exe" if os.name == "nt" else "exiftool")
        self.var_outdir   = tk.StringVar(self.root, str(Path.cwd() / "salida"))

        # Flags y opciones
        self.var_overwrite         = tk.BooleanVar(self.root, True)
        self.var_keep_original     = tk.BooleanVar(self.root, True)
        self.var_convert_png       = tk.BooleanVar(self.root, True)
        self.var_force_white       = tk.BooleanVar(self.root, True)
        self.var_make_webp         = tk.BooleanVar(self.root, True)
        self.var_clean_ai          = tk.BooleanVar(self.root, True)
        self.var_set_dpi96         = tk.BooleanVar(self.root, True)
        self.var_rename_after_meta = tk.BooleanVar(self.root, True)
        self.var_jpg_q = tk.IntVar(self.root, DEFAULT_JPG_QUALITY)
        self.var_webp_q= tk.IntVar(self.root, DEFAULT_WEBP_QUALITY)
        self.var_max_w = tk.IntVar(self.root, 1600)
        self.var_max_h = tk.IntVar(self.root, 0)

        # Metadatos globales (lote)
        self.var_author    = tk.StringVar(self.root, "DecoTech Publicidad")
        self.var_title     = tk.StringVar(self.root, "")
        self.var_alt       = tk.StringVar(self.root, "")
        self.var_desc      = tk.StringVar(self.root, "")
        self.var_keywords  = tk.StringVar(self.root, "letreros, acrilico, oficina, lima")
        self.var_copyright = tk.StringVar(self.root, "© 2025 DecoTech Publicidad. Todos los derechos reservados.")
        self.var_license   = tk.StringVar(self.root, "https://tudominio.com/licencias/uso-de-imagenes")
        self.var_lat = tk.StringVar(self.root, ""); self.var_lon = tk.StringVar(self.root, ""); self.var_alt_m = tk.StringVar(self.root, "")

        # Por archivo (overrides)
        self.row_data: Dict[str, Dict[str, str]] = {}
        self._edit_entry = None
        self._preview_imgtk = None

        # Editor de seleccionado
        self.var_sel_name     = tk.StringVar(self.root, "")
        self.var_sel_title    = tk.StringVar(self.root, "")
        self.var_sel_alt      = tk.StringVar(self.root, "")
        self.var_sel_keywords = tk.StringVar(self.root, "")
        self.txt_sel_desc: Optional[tk.Text] = None

        # Proceso en hilo
        self.worker_thread: Optional[threading.Thread] = None
        self.q_log: "queue.Queue[str]" = queue.Queue()
        self.q_prog: "queue.Queue[tuple]" = queue.Queue()
        self._stop_processing = threading.Event()

        # --- Scrollable wrapper ---
        self.scrollwin = ScrollableWindow(self.root)
        self.scrollwin.pack(fill="both", expand=True)
        self.content = self.scrollwin.inner  # aquí se construye toda la UI

        self._build_ui()
        self._bind_shortcuts()
        self._post_init_checks()
        self._poll_queues()

    # ----- UI -----
    def _build_ui(self):
        # ======= TOP =======
        top = ttk.LabelFrame(self.content, text="Configuración + Metadatos + Editor seleccionado")
        top.pack(fill="x", padx=10, pady=8)

        # Rutas
        r0 = ttk.Frame(top); r0.pack(fill="x", padx=4, pady=(4,0))
        ttk.Label(r0, text="ExifTool:").pack(side="left")
        ttk.Entry(r0, textvariable=self.var_exiftool, width=56).pack(side="left", padx=4)
        ttk.Button(r0, text="Buscar…", command=self._pick_exiftool).pack(side="left", padx=2)
        ttk.Label(r0, text="Salida:").pack(side="left", padx=(12,0))
        ttk.Entry(r0, textvariable=self.var_outdir, width=56).pack(side="left", padx=4)
        ttk.Button(r0, text="Seleccionar…", command=self._pick_outdir).pack(side="left", padx=2)

        # Toolbar
        tb = ttk.Frame(top); tb.pack(fill="x", padx=4, pady=(6,6))
        ttk.Button(tb, text="Agregar archivos", command=self._add_files).pack(side="left", padx=3)
        ttk.Button(tb, text="Agregar carpeta", command=self._add_folder).pack(side="left", padx=3)
        ttk.Separator(tb, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Button(tb, text="Quitar seleccionados", command=self._remove_selected).pack(side="left", padx=3)
        ttk.Button(tb, text="Limpiar lista", command=self._clear_list).pack(side="left", padx=3)
        ttk.Separator(tb, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Button(tb, text="Guardar perfil (Ctrl+S)", command=self._save_profile).pack(side="left", padx=3)
        ttk.Button(tb, text="Cargar perfil (Ctrl+O)", command=self._load_profile).pack(side="left", padx=3)
        ttk.Button(tb, text="Aplicar globales a todos", command=self._apply_globals_to_all).pack(side="left", padx=12)
        ttk.Separator(tb, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Button(tb, text="Opciones avanzadas…", command=self._open_advanced_dialog).pack(side="left", padx=3)
        # Acción visible arriba: Procesar
        ttk.Separator(tb, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Button(tb, text="Procesar (F5)", command=self._process).pack(side="left", padx=3)

        # Metadatos lote + Editor seleccionado
        grid = ttk.Frame(top); grid.pack(fill="x", padx=4, pady=(0,6))
        lote = ttk.Labelframe(grid, text="Metadatos del lote (por defecto)")
        lote.grid(row=0, column=0, sticky="nwe", padx=(0,6))
        self._mk_entry(lote, "Autor/Crédito:", self.var_author, 0, 40)
        self._mk_entry(lote, "Título:", self.var_title, 1, 60)
        self._mk_entry(lote, "ALT:", self.var_alt, 2, 60)
        self._mk_entry(lote, "Descripción:", self.var_desc, 3, 60)
        self._mk_entry(lote, "Keywords (,):", self.var_keywords, 4, 60)
        self._mk_entry(lote, "Copyright:", self.var_copyright, 5, 60)
        self._mk_entry(lote, "Licencia (URL):", self.var_license, 6, 60)
        gps = ttk.Frame(lote); gps.grid(row=7, column=0, columnspan=2, sticky="we", pady=(2,4))
        self._mk_small(gps, "Lat:", self.var_lat).pack(side="left", padx=3)
        self._mk_small(gps, "Lon:", self.var_lon).pack(side="left", padx=12)
        self._mk_small(gps, "Alt (m):", self.var_alt_m).pack(side="left", padx=12)
        lote.columnconfigure(1, weight=1)

        sel = ttk.Labelframe(grid, text="Seleccionado (overrides si llenas)")
        sel.grid(row=0, column=1, sticky="nwe")
        self._mk_entry(sel, "Nombre final:", self.var_sel_name, 0, 36)
        self._mk_entry(sel, "Título:", self.var_sel_title, 1, 36)
        self._mk_entry(sel, "ALT:", self.var_sel_alt, 2, 36)
        ttk.Label(sel, text="Descripción:").grid(row=3, column=0, sticky="ne", padx=4, pady=3)
        if HAS_SCROLLED:
            self.txt_sel_desc = scrolledtext.ScrolledText(sel, height=4, width=36, wrap="word")
            self.txt_sel_desc.grid(row=3, column=1, sticky="we", padx=4, pady=3)
        else:
            wrap = ttk.Frame(sel); wrap.grid(row=3, column=1, sticky="we", padx=4, pady=3)
            self.txt_sel_desc = tk.Text(wrap, height=4, width=36, wrap="word")
            sb = ttk.Scrollbar(wrap, orient="vertical", command=self.txt_sel_desc.yview)
            self.txt_sel_desc.configure(yscrollcommand=sb.set)
            self.txt_sel_desc.pack(side="left", fill="both", expand=True); sb.pack(side="left", fill="y")
        self._mk_entry(sel, "Keywords (,):", self.var_sel_keywords, 4, 36)
        ttk.Button(sel, text="Aplicar al seleccionado", command=self._apply_selected).grid(row=5, column=0, columnspan=2, pady=6)
        sel.columnconfigure(1, weight=1)
        grid.columnconfigure(0, weight=2)
        grid.columnconfigure(1, weight=1)

        # ======= MID (grid 2 columnas: lista + preview fijo) =======
        mid = ttk.Frame(self.content)
        mid.pack(fill="both", expand=True, padx=10, pady=(0,8))
        mid.grid_columnconfigure(0, weight=1)
        mid.grid_columnconfigure(1, weight=0)
        mid.grid_rowconfigure(0, weight=1)

        # --- Panel izquierdo: Treeview de archivos ---
        left = ttk.LabelFrame(mid, text="Archivos (doble clic = renombrar)")
        left.grid(row=0, column=0, sticky="nsew", padx=(0,8))

        self.tree = ttk.Treeview(left, columns=self.COLS, show="headings",
                                 selectmode="extended", height=18)
        self.tree.heading("ruta", text="Archivo (ruta completa)")
        self.tree.heading("final_name", text="Nombre final")
        self.tree.heading("title", text="Título (override)")
        self.tree.heading("alt", text="ALT (override)")
        self.tree.heading("keywords", text="Keywords (override)")
        self.tree.column("ruta", width=680, anchor="w")
        self.tree.column("final_name", width=220, anchor="w")
        self.tree.column("title", width=200, anchor="w")
        self.tree.column("alt", width=200, anchor="w")
        self.tree.column("keywords", width=200, anchor="w")

        yscroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(left, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)

        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(0, weight=1)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=6, pady=(6,0))
        yscroll.grid(row=0, column=1, sticky="ns", pady=(6,0))
        xscroll.grid(row=1, column=0, sticky="ew", padx=6)

        self.tree.bind("<Double-1>", self._on_tree_double_click)
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        if DND_AVAILABLE:
            self.tree.drop_target_register(DND_FILES)
            self.tree.dnd_bind("<<Drop>>", self._on_drop_files)

        # --- Panel derecho: Vista previa fija ---
        preview = ttk.LabelFrame(mid, text="Vista previa")
        preview.grid(row=0, column=1, sticky="n", padx=(0,0))
        self.preview_canvas = tk.Canvas(preview, width=380, height=320, bg="#ffffff",
                                        highlightthickness=1, highlightbackground="#999")
        self.preview_canvas.pack(padx=6, pady=6)
        self.preview_canvas.create_text(190, 160, text="(sin vista previa)", fill="#666")

        # ======= BOTTOM =======
        bottom = ttk.LabelFrame(self.content, text="Opciones + Acciones + Registro")
        bottom.pack(fill="both", expand=True, padx=10, pady=(0,10))

        opts = ttk.Frame(bottom); opts.pack(fill="x", padx=6, pady=6)
        ttk.Label(opts, text="JPG Q:").pack(side="left")
        ttk.Spinbox(opts, from_=60, to=100, textvariable=self.var_jpg_q, width=5).pack(side="left", padx=4)
        ttk.Label(opts, text="WEBP Q:").pack(side="left")
        ttk.Spinbox(opts, from_=60, to=100, textvariable=self.var_webp_q, width=5).pack(side="left", padx=4)
        ttk.Label(opts, text="Máx. Ancho:").pack(side="left", padx=(12,4))
        ttk.Spinbox(opts, from_=0, to=10000, textvariable=self.var_max_w, width=6).pack(side="left")
        ttk.Label(opts, text="Máx. Alto:").pack(side="left", padx=(12,4))
        ttk.Spinbox(opts, from_=0, to=10000, textvariable=self.var_max_h, width=6).pack(side="left")

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
            ttk.Checkbutton(opts, text=text, variable=var).pack(side="left", padx=8)

        actions = ttk.Frame(bottom); actions.pack(fill="x", padx=6, pady=(0,6))
        self.progress = ttk.Progressbar(actions, orient="horizontal", mode="determinate")
        self.progress.pack(fill="x", side="left", expand=True, padx=(0,6))
        ttk.Button(actions, text="Procesar (F5)", command=self._process).pack(side="left")
        ttk.Button(actions, text="Ver metadatos del seleccionado", command=self._view_selected_meta).pack(side="left", padx=(6,0))

        # Log con scroll estable
        if HAS_SCROLLED:
            self.txt = scrolledtext.ScrolledText(bottom, height=10, wrap="none")
            self.txt.pack(fill="both", expand=True, padx=6, pady=6)
        else:
            wrap = ttk.Frame(bottom); wrap.pack(fill="both", expand=True, padx=6, pady=6)
            self.txt = tk.Text(wrap, height=10, wrap="none")
            sby = ttk.Scrollbar(wrap, orient="vertical", command=self.txt.yview)
            sbx = ttk.Scrollbar(wrap, orient="horizontal", command=self.txt.xview)
            self.txt.configure(yscrollcommand=sby.set, xscrollcommand=sbx.set)
            self.txt.pack(side="left", fill="both", expand=True)
            sby.pack(side="left", fill="y"); sbx.pack(side="bottom", fill="x")

    def _mk_entry(self, parent, label, var, row, width=50):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="e", padx=4, pady=3)
        ttk.Entry(parent, textvariable=var, width=width).grid(row=row, column=1, sticky="we", padx=4, pady=3)
        parent.columnconfigure(1, weight=1)

    def _mk_small(self, parent, text, var):
        f = ttk.Frame(parent)
        ttk.Label(f, text=text).pack(side="left")
        ttk.Entry(f, textvariable=var, width=10).pack(side="left", padx=3)
        return f

    # ----- Helpers -----
    def _log(self, msg: str):
        try:
            self.txt.insert("end", msg + "\n")
            self.txt.see("end")
        except Exception:
            print(msg)
        self.root.update_idletasks()

    def _bind_shortcuts(self):
        self.root.bind("<Delete>",   lambda e: self._remove_selected())
        self.root.bind("<Control-s>",lambda e: self._save_profile())
        self.root.bind("<Control-o>",lambda e: self._load_profile())
        self.root.bind("<F5>",       lambda e: self._process())

    def _post_init_checks(self):
        if MISSING_PIL:
            self._log("⚠ Pillow NO instalado. Instala con: pip install pillow")
        if not DND_AVAILABLE:
            self._log("ℹ DnD no disponible (opcional). Instala: pip install tkinterdnd2")

    def _pick_exiftool(self):
        p = filedialog.askopenfilename(title="Selecciona exiftool.exe o exiftool", filetypes=[("Ejecutable", "*.*")])
        if p: self.var_exiftool.set(p)

    def _pick_outdir(self):
        d = filedialog.askdirectory(title="Selecciona carpeta de salida")
        if d: self.var_outdir.set(d)

    # ----- perfiles -----
    def _profile_dict(self) -> Dict[str, Any]:
        return dict(
            exiftool=self.var_exiftool.get(), outdir=self.var_outdir.get(),
            author=self.var_author.get(), title=self.var_title.get(), alt=self.var_alt.get(),
            desc=self.var_desc.get(), keywords=self.var_keywords.get(),
            copyright=self.var_copyright.get(), license=self.var_license.get(),
            gps_lat=self.var_lat.get(), gps_lon=self.var_lon.get(), gps_alt=self.var_alt_m.get(),
            jpg_q=int(self.var_jpg_q.get()), webp_q=int(self.var_webp_q.get()),
            max_w=int(self.var_max_w.get()), max_h=int(self.var_max_h.get()),
            overwrite=bool(self.var_overwrite.get()), keep_original=bool(self.var_keep_original.get()),
            convert_png=bool(self.var_convert_png.get()), force_white=bool(self.var_force_white.get()),
            make_webp=bool(self.var_make_webp.get()), clean_ai=bool(self.var_clean_ai.get()),
            set_dpi96=bool(self.var_set_dpi96.get()), rename_after_meta=bool(self.var_rename_after_meta.get()),
            files=[{"path": iid, **self.row_data.get(iid, {})} for iid in self.tree.get_children()]
        )

    def _save_profile(self):
        data = self._profile_dict()
        path = filedialog.asksaveasfilename(
            title="Guardar perfil", defaultextension=".json", initialfile="perfil_optimizador_seo.json",
            filetypes=[("Perfil JSON", "*.json")])
        if not path: return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self._log(f"Perfil guardado: {path}")

    def _load_profile(self):
        path = filedialog.askopenfilename(title="Cargar perfil", filetypes=[("Perfil JSON", "*.json")])
        if not path: return
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception as e:
            messagebox.showerror("Perfil", f"No se pudo abrir: {e}"); return

        self.var_exiftool.set(d.get("exiftool", self.var_exiftool.get()))
        self.var_outdir.set(d.get("outdir", self.var_outdir.get()))
        self.var_author.set(d.get("author","")); self.var_title.set(d.get("title","")); self.var_alt.set(d.get("alt",""))
        self.var_desc.set(d.get("desc","")); self.var_keywords.set(d.get("keywords",""))
        self.var_copyright.set(d.get("copyright","")); self.var_license.set(d.get("license",""))
        self.var_lat.set(d.get("gps_lat","")); self.var_lon.set(d.get("gps_lon","")); self.var_alt_m.set(d.get("gps_alt",""))
        self.var_jpg_q.set(int(d.get("jpg_q", DEFAULT_JPG_QUALITY)))
        self.var_webp_q.set(int(d.get("webp_q", DEFAULT_WEBP_QUALITY)))
        self.var_max_w.set(int(d.get("max_w", 1600))); self.var_max_h.set(int(d.get("max_h", 0)))
        self.var_overwrite.set(bool(d.get("overwrite", True))); self.var_keep_original.set(bool(d.get("keep_original", True)))
        self.var_convert_png.set(bool(d.get("convert_png", True))); self.var_force_white.set(bool(d.get("force_white", True)))
        self.var_make_webp.set(bool(d.get("make_webp", True))); self.var_clean_ai.set(bool(d.get("clean_ai", True)))
        self.var_set_dpi96.set(bool(d.get("set_dpi96", True))); self.var_rename_after_meta.set(bool(d.get("rename_after_meta", True)))

        # Archivos
        self._clear_list()
        for fobj in d.get("files", []):
            p = Path(fobj.get("path",""))
            iid = str(p.resolve()) if p.exists() else str(p)
            if iid in self.row_data: continue
            data = {
                "final_name": fobj.get("final_name", p.stem if p else ""),
                "title": fobj.get("title",""),
                "alt": fobj.get("alt",""),
                "desc": fobj.get("desc",""),
                "keywords": fobj.get("keywords",""),
            }
            self.row_data[iid] = data
            self.tree.insert("", "end", iid=iid,
                             values=(iid, data["final_name"], data["title"], data["alt"], data["keywords"]))
        self._log(f"Perfil cargado: {path}")

    def _apply_globals_to_all(self):
        for iid, d in self.row_data.items():
            if not d.get("title"):    d["title"] = self.var_title.get().strip()
            if not d.get("alt"):      d["alt"] = self.var_alt.get().strip()
            if not d.get("desc"):     d["desc"] = self.var_desc.get().strip()
            if not d.get("keywords"): d["keywords"] = self.var_keywords.get().strip()
            # refrescar fila
            self.tree.set(iid, "title", d["title"])
            self.tree.set(iid, "alt", d["alt"])
            self.tree.set(iid, "keywords", d["keywords"])
        self._log("Globales aplicados a filas vacías.")

    # ----- archivos -----
    def _add_files(self):
        paths = filedialog.askopenfilenames(title="Agregar imágenes",
                                            filetypes=[("Imágenes", "*.jpg;*.jpeg;*.png;*.tif;*.tiff;*.webp")])
        for p in paths:
            self._add(Path(p))

    def _add_folder(self):
        d = filedialog.askdirectory(title="Agregar carpeta")
        if not d: return
        for p in Path(d).rglob("*"):
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXT:
                self._add(p)

    def _add(self, p: Path):
        try:
            iid = str(p.resolve())
        except Exception:
            iid = str(p)
        if not str(p).lower().endswith(tuple(SUPPORTED_EXT)): return
        if iid in self.row_data: return
        self.row_data[iid] = {"final_name": p.stem, "title":"", "alt":"", "desc":"", "keywords":""}
        self.tree.insert("", "end", iid=iid, values=(iid, p.stem, "", "", ""))
        if len(self.tree.get_children()) == 1:
            self._draw_preview(p); self._sync_selected_editor(iid)

    def _remove_selected(self):
        for iid in self.tree.selection():
            try: del self.row_data[iid]
            except KeyError: pass
            self.tree.delete(iid)
        if not self.tree.selection():
            self._clear_preview(); self._clear_selected_editor()

    def _clear_list(self):
        for iid in self.tree.get_children(): self.tree.delete(iid)
        self.row_data.clear()
        self._clear_preview(); self._clear_selected_editor()

    # DnD
    def _on_drop_files(self, event):
        try:
            items = self.root.splitlist(event.data)
        except Exception:
            items = [x.strip("{}") for x in event.data.strip().split()]
        for raw in items:
            p = Path(raw)
            if p.is_dir():
                for f in p.rglob("*"):
                    if f.is_file() and f.suffix.lower() in SUPPORTED_EXT:
                        self._add(f)
            else:
                self._add(p)

    # edición inline nombre (columna 2)
    def _on_tree_double_click(self, event):
        if self.tree.identify("region", event.x, event.y) != "cell": return
        col = self.tree.identify_column(event.x); row = self.tree.identify_row(event.y)
        if not row or col != "#2": return
        x, y, w, h = self.tree.bbox(row, col)
        current = self.tree.set(row, "final_name")
        if self._edit_entry:
            try: self._edit_entry.destroy()
            except Exception: pass
        self._edit_entry = tk.Entry(self.tree)
        self._edit_entry.insert(0, current)
        self._edit_entry.place(x=x, y=y, width=w, height=h); self._edit_entry.focus()
        def commit(_=None):
            self._apply_name_edit(row, self._edit_entry.get().strip())
            try: self._edit_entry.destroy()
            except Exception: pass
            self._edit_entry = None
        self._edit_entry.bind("<Return>", commit)
        self._edit_entry.bind("<Escape>", commit)
        self._edit_entry.bind("<FocusOut>", commit)

    def _apply_name_edit(self, iid: str, value: str):
        v = value or self.row_data[iid]["final_name"]
        if "." in v: v = v.rsplit(".",1)[0]
        v = v.replace("/", "-").replace("\\","-")
        self.row_data[iid]["final_name"] = v
        self.tree.set(iid, "final_name", v)
        if iid in self.tree.selection(): self.var_sel_name.set(v)

    def _on_tree_select(self, _e):
        sel = self.tree.selection()
        if not sel:
            self._clear_preview(); self._clear_selected_editor(); return
        iid = sel[0]
        self._draw_preview(Path(iid)); self._sync_selected_editor(iid)

    # editor seleccionado
    def _sync_selected_editor(self, iid: str):
        d = self.row_data.get(iid, {})
        self.var_sel_name.set(d.get("final_name",""))
        self.var_sel_title.set(d.get("title",""))
        self.var_sel_alt.set(d.get("alt",""))
        self.var_sel_keywords.set(d.get("keywords",""))
        self.txt_sel_desc.delete("1.0", "end"); self.txt_sel_desc.insert("1.0", d.get("desc",""))

    def _clear_selected_editor(self):
        for v in [self.var_sel_name, self.var_sel_title, self.var_sel_alt, self.var_sel_keywords]:
            v.set("")
        if self.txt_sel_desc: self.txt_sel_desc.delete("1.0", "end")

    def _apply_selected(self):
        sel = self.tree.selection()
        if not sel: return
        iid = sel[0]
        d = self.row_data[iid]
        d["final_name"] = (self.var_sel_name.get().strip() or d["final_name"])
        d["title"] = self.var_sel_title.get().strip()
        d["alt"] = self.var_sel_alt.get().strip()
        d["keywords"] = self.var_sel_keywords.get().strip()
        d["desc"] = self.txt_sel_desc.get("1.0", "end").strip()
        self.tree.set(iid, "final_name", d["final_name"])
        self.tree.set(iid, "title", d["title"])
        self.tree.set(iid, "alt", d["alt"])
        self.tree.set(iid, "keywords", d["keywords"])

    # preview
    def _clear_preview(self):
        self.preview_canvas.delete("all")
        self.preview_canvas.create_text(190, 160, text="(sin vista previa)", fill="#666")
        self._preview_imgtk = None

    def _draw_preview(self, path: Path):
        self.preview_canvas.delete("all")
        w, h = 380, 320
        self.preview_canvas.create_rectangle(1,1,w-1,h-1, outline="#999", fill="#fff")
        if not path.exists():
            self.preview_canvas.create_text(w//2, h//2, text="(Archivo no existe)", fill="#a00"); return
        if MISSING_PIL:
            self.preview_canvas.create_text(w//2, h//2, text="(Pillow no instalado)", fill="#a00"); return
        try:
            img = Image.open(path)
            img = force_white_background_if_transparent(to_srgb(img))
            img.thumbnail((w-24, h-24), RESAMPLE or Image.LANCZOS)
            self._preview_imgtk = ImageTk.PhotoImage(img)
            x = (w-img.width)//2; y=(h-img.height)//2
            self.preview_canvas.create_image(x, y, image=self._preview_imgtk, anchor="nw")
        except Exception as e:
            self.preview_canvas.create_text(w//2, h//2, text=f"(No se puede mostrar)", fill="#a00")
            self._log(f"Vista previa falló: {e}")

    # opciones avanzadas
    def _open_advanced_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Opciones avanzadas")
        dlg.transient(self.root); dlg.grab_set()
        frm = ttk.Frame(dlg, padding=10); frm.pack(fill="both", expand=True)
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
            ttk.Checkbutton(frm, text=text, variable=var).pack(anchor="w", pady=2)
        row2 = ttk.Frame(frm); row2.pack(fill="x", pady=(8,4))
        ttk.Label(row2, text="JPG Q:").pack(side="left"); ttk.Spinbox(row2, from_=60, to=100, textvariable=self.var_jpg_q, width=5).pack(side="left", padx=4)
        ttk.Label(row2, text="WEBP Q:").pack(side="left"); ttk.Spinbox(row2, from_=60, to=100, textvariable=self.var_webp_q, width=5).pack(side="left", padx=4)
        ttk.Label(row2, text="Máx. Ancho:").pack(side="left", padx=(12,4)); ttk.Spinbox(row2, from_=0, to=10000, textvariable=self.var_max_w, width=6).pack(side="left")
        ttk.Label(row2, text="Máx. Alto:").pack(side="left", padx=(12,4)); ttk.Spinbox(row2, from_=0, to=10000, textvariable=self.var_max_h, width=6).pack(side="left")
        ttk.Button(frm, text="Cerrar", command=dlg.destroy).pack(pady=6)

    # ----- metadatos / proceso -----
    def _merge_defaults(self, iid: str) -> dict:
        d = self.row_data.get(iid, {})
        return {
            "final_name": d.get("final_name","").strip() or "",
            "title": (d.get("title","").strip() or self.var_title.get().strip()),
            "alt": (d.get("alt","").strip() or self.var_alt.get().strip()),
            "desc": (d.get("desc","").strip() or self.var_desc.get().strip()),
            "keywords": (d.get("keywords","").strip() or self.var_keywords.get().strip()),
        }

    def _view_selected_meta(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Ver metadatos", "Selecciona una salida existente."); return
        iid = sel[0]
        outdir = Path(self.var_outdir.get().strip())
        final_stem = (self.row_data.get(iid, {}).get("final_name") or Path(iid).stem).strip()
        candidate = outdir / f"{final_stem}-meta.jpg"
        target = candidate if candidate.exists() else (outdir / f"{final_stem}.jpg")
        if not target.exists():
            messagebox.showwarning("Ver metadatos", f"No encuentro salida: {target.name}"); return
        info = show_metadata_dump(self.var_exiftool.get().strip(), target)
        self._log("--- METADATOS ---\n" + info + "\n------------------")

    # ---- procesamiento en hilo ----
    def _validate_before_process(self) -> Optional[str]:
        if not self.tree.get_children():
            return "Agrega imágenes primero."
        # ExifTool
        exif = self.var_exiftool.get().strip()
        if not exif: return "Ruta a ExifTool vacía."
        exe = Path(exif)
        if not exe.exists():
            return "ExifTool no existe en la ruta indicada."
        # outdir
        outdir = Path(self.var_outdir.get().strip())
        try:
            outdir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return f"No se puede usar la carpeta de salida: {e}"
        # PIL
        if MISSING_PIL:
            return "Pillow no está instalado. Ejecuta: pip install pillow"
        return None

    def _process(self):
        err = self._validate_before_process()
        if err:
            messagebox.showerror("Validación", err); return

        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo("Procesando", "Ya hay un procesamiento en curso."); return

        items = list(self.tree.get_children())
        total = len(items)
        self.progress.configure(maximum=total, value=0)
        self._stop_processing.clear()

        # recopilar lote
        job = dict(
            items=items,
            exiftool=self.var_exiftool.get().strip(),
            outdir=Path(self.var_outdir.get().strip()),
            jpg_q=int(self.var_jpg_q.get()), webp_q=int(self.var_webp_q.get()),
            max_w=int(self.var_max_w.get()), max_h=int(self.var_max_h.get()),
            overwrite=bool(self.var_overwrite.get()),
            convert_png=bool(self.var_convert_png.get()),
            force_white=bool(self.var_force_white.get()),
            make_webp=bool(self.var_make_webp.get()),
            clean_ai=bool(self.var_clean_ai.get()),
            set_dpi96=bool(self.var_set_dpi96.get()),
            rename_after_meta=bool(self.var_rename_after_meta.get()),
            author=self.var_author.get().strip(), title=self.var_title.get().strip(),
            alt=self.var_alt.get().strip(), desc=self.var_desc.get().strip(),
            keywords=self.var_keywords.get().strip(),
            copyright=self.var_copyright.get().strip(), license=self.var_license.get().strip(),
            gps_lat=self.var_lat.get().strip(), gps_lon=self.var_lon.get().strip(), gps_alt=self.var_alt_m.get().strip(),
        )

        def worker():
            ok, fail = 0, 0
            for idx, iid in enumerate(items, 1):
                if self._stop_processing.is_set(): break
                src = Path(iid)
                meta = self._merge_defaults(iid)
                final_name = meta["final_name"] or src.stem
                self.q_log.put(f"• [{idx}/{total}] {src.name} → {final_name}.jpg ...")

                try:
                    # Export JPG (y preparamos path WEBP)
                    jpg_path, webp_path = export_jpg_and_webp(
                        src, job["outdir"], job["jpg_q"], job["webp_q"],
                        job["convert_png"], job["force_white"],
                        job["max_w"], job["max_h"],
                        job["overwrite"], final_stem=final_name
                    )

                    # WEBP opcional: generar a partir del JPG producido
                    if job["make_webp"]:
                        try:
                            img_tmp = Image.open(jpg_path)
                            webp_tmp = webp_path
                            img_tmp.save(webp_tmp, format="WEBP", quality=int(job["webp_q"]))
                        except Exception as e:
                            self.q_log.put(f"   - WEBP falló: {e}")

                    # Limpieza -all=
                    if job["clean_ai"]:
                        code, out, err = clean_all_metadata(job["exiftool"], jpg_path)
                        if code != 0:
                            self.q_log.put(f"   - Limpieza metadatos (JPG) avisó: {err or out}")
                        if job["make_webp"]:
                            webp_real = job["outdir"] / f"{final_name}.webp"
                            if webp_real.exists():
                                code, out, err = clean_all_metadata(job["exiftool"], webp_real)
                                if code != 0:
                                    self.q_log.put(f"   - Limpieza metadatos (WEBP) avisó: {err or out}")

                    # DPI 96
                    if job["set_dpi96"]:
                        code, out, err = set_dpi_96(job["exiftool"], jpg_path)
                        if code != 0:
                            self.q_log.put(f"   - DPI 96 (JPG) avisó: {err or out}")
                        if job["make_webp"]:
                            webp_real = job["outdir"] / f"{final_name}.webp"
                            if webp_real.exists():
                                code, out, err = set_dpi_96(job["exiftool"], webp_real)
                                if code != 0:
                                    self.q_log.put(f"   - DPI 96 (WEBP) avisó: {err or out}")

                    # Escribir metadatos (JPG)
                    code, out, err = write_metadata_full(
                        job["exiftool"], jpg_path,
                        job["author"], meta["title"], meta["desc"],
                        job["copyright"], job["license"],
                        meta["keywords"], meta["alt"],
                        job["gps_lat"], job["gps_lon"], job["gps_alt"]
                    )
                    if code != 0:
                        self.q_log.put(f"   - Metadatos (JPG) avisó: {err or out}")

                    # Escribir metadatos (WEBP) si existe
                    if job["make_webp"]:
                        webp_real = job["outdir"] / f"{final_name}.webp"
                        if webp_real.exists():
                            code, out, err = write_metadata_full(
                                job["exiftool"], webp_real,
                                job["author"], meta["title"], meta["desc"],
                                job["copyright"], job["license"],
                                meta["keywords"], meta["alt"],
                                job["gps_lat"], job["gps_lon"], job["gps_alt"]
                            )
                            if code != 0:
                                self.q_log.put(f"   - Metadatos (WEBP) avisó: {err or out}")

                    # Renombrar tras meta con sufijo -meta (evitar colisión)
                    if job["rename_after_meta"]:
                        target = job["outdir"] / f"{final_name}-meta.jpg"
                        target = self._unique_path(target)
                        try:
                            if target.exists() and not job["overwrite"]:
                                raise RuntimeError(f"Ya existe {target.name}")
                            if target.exists():
                                target.unlink()
                            shutil.move(str(jpg_path), str(target))
                            jpg_path = target
                        except Exception as e:
                            self.q_log.put(f"   - Renombrado -meta falló: {e}")

                    # Original
                    if not job["keep_original"]:
                        try:
                            if src.exists(): src.unlink()
                        except Exception as e:
                            self.q_log.put(f"   - No pude borrar original: {e}")

                    ok += 1
                    self.q_log.put(f"   ✔ Listo: {final_name}.jpg")
                except Exception as e:
                    fail += 1
                    self.q_log.put(f"   ✖ Error: {e}")

                self.q_prog.put(("step", 1))

            self.q_log.put(f"=== Totales: OK={ok}  Errores={fail} ===")
            self.q_prog.put(("done", None))

        self.worker_thread = threading.Thread(target=worker, daemon=True)
        self.worker_thread.start()

    def _unique_path(self, path: Path) -> Path:
        if not path.exists(): return path
        stem, suf = path.stem, path.suffix
        i = 2
        while True:
            cand = path.with_name(f"{stem}_{i}{suf}")
            if not cand.exists(): return cand
            i += 1

    def _poll_queues(self):
        """Refresca log y progreso sin bloquear la UI."""
        try:
            while True:
                msg = self.q_log.get_nowait()
                self._log(msg)
        except queue.Empty:
            pass

        try:
            while True:
                t, val = self.q_prog.get_nowait()
                if t == "step":
                    self.progress.step(1)
                elif t == "done":
                    pass
        except queue.Empty:
            pass

        self.root.after(60, self._poll_queues)

# ---------------- main ----------------
def main():
    Tk = TkinterDnD.Tk if DND_AVAILABLE else tk.Tk
    root = Tk()
    style = ttk.Style()
    try:
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass
    App(root)
    root.mainloop()

if __name__ == "__main__":
    main()
