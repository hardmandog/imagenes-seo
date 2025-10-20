import os, re, sys, subprocess, tkinter as tk
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageTk

# --- Drag & Drop opcional ---
HAS_DND = True
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES  # pip install tkinterdnd2
except Exception:
    HAS_DND = False

AUTHOR = "DECOTECH"
WEBP_QUALITY = 80
VALID_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
THUMB_SIZE = (64, 64)

def get_exiftool_cmd():
    base = os.path.dirname(os.path.abspath(sys.argv[0]))
    exe = os.path.join(base, "exiftool.exe")
    return exe if os.path.exists(exe) else "exiftool"

EXIFTOOL = get_exiftool_cmd()

def normalize_drop_list(data: str):
    if not data: return []
    items = re.findall(r'\{[^}]+\}|[^\s]+', data)
    return [p.strip("{}") for p in items]

def is_valid_image(path): return os.path.splitext(path)[1].lower() in VALID_EXTS
def basename_noext(p):   return os.path.splitext(os.path.basename(p))[0]
def ext_lower(p):        return os.path.splitext(p)[1].lower()

def convert_to_webp(input_path, output_basename=None):
    """Convierte a WEBP usando un archivo temporal para no dejar archivos corruptos."""
    img = Image.open(input_path).convert("RGB")
    out_dir = os.path.dirname(input_path)
    name = output_basename or basename_noext(input_path)
    final_path = os.path.join(out_dir, name + ".webp")
    tmp_path = final_path + ".tmp"
    img.save(tmp_path, "WEBP", quality=WEBP_QUALITY, optimize=True)
    os.replace(tmp_path, final_path)  # atómico
    return final_path

def exiftool_run(args):
    r = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    return r.stdout.strip()

def exiftool_clean_all(path):
    exiftool_run([EXIFTOOL, "-overwrite_original", "-all=", path])

def exiftool_write_title(path, title_text, author=None):
    cmd = [EXIFTOOL, "-overwrite_original", f"-Title={title_text}"]  # SOLO Title
    if author: cmd.append(f"-Author={author}")
    exiftool_run(cmd + [path])

def exiftool_write_gps(path, lat, lon):
    exiftool_run([EXIFTOOL, "-overwrite_original",
                  f"-GPSLatitude={lat}", f"-GPSLongitude={lon}", path])

BaseTk = TkinterDnD.Tk if HAS_DND else tk.Tk

class App(BaseTk):
    def __init__(self):
        super().__init__()
        self.title("Optimizador de Imágenes SEO - DECOTECH (build panes + parche)")
        self.geometry("960x620")
        self.minsize(900, 580)
        self.config(padx=8, pady=8)

        self.thumb_cache = {}
        self.item_path = {}

        # ---- Paned window (3 zonas) ----
        paned = ttk.Panedwindow(self, orient="vertical")
        paned.pack(fill="both", expand=True)

        # ZONA 1: Drop/select
        top = ttk.Frame(paned, padding=8)
        paned.add(top, weight=0)
        ttk.Label(top, text="Arrastra imágenes o usa el botón (JPG/JPEG/PNG/WEBP).",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w")
        drop = ttk.Frame(top, relief="solid", padding=12)
        drop.pack(fill="x", pady=(6, 2))
        if HAS_DND:
            drop.drop_target_register(DND_FILES)
            drop.dnd_bind("<<Drop>>", self.on_drop)
            ttk.Label(drop, text="📂 Arrastra aquí tus imágenes").pack()
        else:
            ttk.Label(drop, text="(Instala 'tkinterdnd2' para arrastrar y soltar)").pack()
        ttk.Button(drop, text="Seleccionar imágenes…", command=self.add_images).pack(pady=4)

        bar = ttk.Frame(top)
        bar.pack(fill="x", pady=(4, 0))
        ttk.Button(bar, text="Quitar seleccionados", command=self.remove_selected).pack(side="left")
        ttk.Button(bar, text="Limpiar todo", command=self.clear_all).pack(side="left", padx=6)

        # ZONA 2: Tabla
        mid = ttk.Frame(paned, padding=(0,6))
        paned.add(mid, weight=3)
        style = ttk.Style(self); style.configure("Treeview", rowheight=72)
        cols = ("original", "nuevo")
        self.tree = ttk.Treeview(mid, columns=cols, show="tree headings")
        self.tree.heading("#0", text="Miniatura")
        self.tree.heading("original", text="Nombre original")
        self.tree.heading("nuevo", text="Nuevo nombre (editable)")
        self.tree.column("#0", width=90, anchor="center")
        self.tree.column("original", width=380, anchor="w")
        self.tree.column("nuevo", width=380, anchor="w")
        self.tree.pack(fill="both", expand=True, side="left")
        self.tree.bind("<Double-1>", self.start_edit_cell)

        vsb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")

        # ZONA 3: Opciones + Acciones + Log
        bottom = ttk.Frame(paned, padding=8, relief="solid")
        paned.add(bottom, weight=0)

        # ---- OPCIONES ----
        opts = ttk.Frame(bottom)
        opts.pack(fill="x")

        self.var_convert = tk.BooleanVar(value=True)   # Convertir a WEBP
        self.var_title   = tk.BooleanVar(value=True)   # Escribir Title
        self.var_gps     = tk.BooleanVar(value=False)  # Escribir GPS
        self.var_delete  = tk.BooleanVar(value=False)  # Eliminar original (parche aplicado)
        self.var_clean   = tk.BooleanVar(value=False)  # Limpiar TODO antes de guardar

        ttk.Checkbutton(opts, text="Convertir a WEBP", variable=self.var_convert).grid(row=0, column=0, sticky="w", padx=6, pady=2)
        ttk.Checkbutton(opts, text="Cambiar metadatos: Título", variable=self.var_title).grid(row=0, column=1, sticky="w", padx=6, pady=2)
        ttk.Checkbutton(opts, text="Eliminar original", variable=self.var_delete).grid(row=0, column=2, sticky="w", padx=6, pady=2)
        ttk.Checkbutton(opts, text="Limpiar TODOS los metadatos", variable=self.var_clean).grid(row=0, column=3, sticky="w", padx=6, pady=2)

        ttk.Checkbutton(opts, text="Escribir GPS", variable=self.var_gps, command=self.toggle_gps).grid(row=1, column=0, sticky="w", padx=6, pady=2)
        ttk.Label(opts, text="Lat:").grid(row=1, column=1, sticky="e")
        self.entry_lat = ttk.Entry(opts, width=12, state="disabled"); self.entry_lat.insert(0, "-12.0464"); self.entry_lat.grid(row=1, column=2, sticky="w")
        ttk.Label(opts, text="Lon:").grid(row=1, column=3, sticky="e")
        self.entry_lon = ttk.Entry(opts, width=12, state="disabled"); self.entry_lon.insert(0, "-77.0428"); self.entry_lon.grid(row=1, column=4, sticky="w")

        # ---- Acciones ----
        actions = ttk.Frame(bottom)
        actions.pack(fill="x", pady=(6,4))
        ttk.Button(actions, text="Procesar", command=self.process_all).pack(side="left")
        ttk.Button(actions, text="Limpiar metadatos (seleccionados)", command=self.clean_selected).pack(side="left", padx=8)

        # ---- Log ----
        ttk.Label(bottom, text="Log").pack(anchor="w")
        self.logbox = tk.Text(bottom, height=5, wrap="word")
        self.logbox.pack(fill="x")
        self.progress = ttk.Progressbar(bottom, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(4,0))

        self.after(200, self.check_exiftool)
        self.edit_entry = self.edit_item = self.edit_column = None

    # ---------- helpers ----------
    def log(self, msg):
        self.logbox.insert("end", msg + "\n"); self.logbox.see("end"); self.update_idletasks()

    def check_exiftool(self):
        try:
            subprocess.run([EXIFTOOL, "-ver"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=4)
        except Exception:
            self.log("❌ ExifTool no encontrado. Coloca exiftool.exe junto al .py o en el PATH.")
        else:
            self.log("✔ ExifTool detectado.")

    def toggle_gps(self):
        state = "normal" if self.var_gps.get() else "disabled"
        self.entry_lat.config(state=state); self.entry_lon.config(state=state)

    def load_thumbnail(self, path):
        if path in self.thumb_cache: return self.thumb_cache[path]
        try:
            img = Image.open(path); img.thumbnail(THUMB_SIZE)
            pic = ImageTk.PhotoImage(img); self.thumb_cache[path] = pic
            return pic
        except Exception:
            return None

    # ---------- lista ----------
    def add_paths(self, paths):
        added, existing = 0, set(self.item_path.values())
        for p in paths:
            if os.path.isfile(p) and is_valid_image(p) and p not in existing:
                iid = self.tree.insert("", "end", text="", image=self.load_thumbnail(p),
                                       values=(os.path.basename(p), ""))  # col1 original, col2 nuevo
                self.item_path[iid] = p; added += 1
        if added == 0 and paths:
            messagebox.showinfo("Agregar", "No se añadieron nuevas imágenes válidas.")

    def add_images(self):
        self.add_paths(filedialog.askopenfilenames(filetypes=[("Imágenes", "*.jpg *.jpeg *.png *.webp")]))

    def on_drop(self, event):
        self.add_paths(normalize_drop_list(event.data))

    def remove_selected(self):
        for iid in self.tree.selection():
            self.tree.delete(iid); self.item_path.pop(iid, None)

    def clear_all(self):
        self.tree.delete(*self.tree.get_children()); self.item_path.clear(); self.thumb_cache.clear()
        self.log("🧹 Lista limpiada.")

    # ---------- edición celda 'nuevo' ----------
    def start_edit_cell(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell": return
        if self.tree.identify_column(event.x) != "#2": return
        item = self.tree.identify_row(event.y); bbox = self.tree.bbox(item, column="#2")
        if not item or not bbox: return
        x, y, w, h = bbox
        val = self.tree.set(item, "nuevo")
        self.edit_item, self.edit_column = item, "nuevo"
        self.edit_entry = ttk.Entry(self.tree); self.edit_entry.place(x=x, y=y, width=w, height=h)
        self.edit_entry.insert(0, val); self.edit_entry.focus()
        self.edit_entry.bind("<Return>", self.finish_edit_cell)
        self.edit_entry.bind("<Escape>", self.cancel_edit_cell)
        self.edit_entry.bind("<FocusOut>", self.finish_edit_cell)

    def finish_edit_cell(self, *_):
        if self.edit_entry and self.edit_item:
            self.tree.set(self.edit_item, self.edit_column, self.edit_entry.get().strip())
            self.edit_entry.destroy(); self.edit_entry = self.edit_item = self.edit_column = None

    def cancel_edit_cell(self, *_):
        if self.edit_entry:
            self.edit_entry.destroy(); self.edit_entry = self.edit_item = self.edit_column = None

    # ---------- procesamiento (con PARCHE de borrado seguro) ----------
    def process_all(self):
        items = self.tree.get_children()
        if not items:
            messagebox.showwarning("Sin archivos", "Agrega imágenes primero."); return

        do_convert  = self.var_convert.get()
        do_title    = self.var_title.get()
        do_gps      = self.var_gps.get()
        do_delete   = self.var_delete.get()
        do_clean    = self.var_clean.get()
        lat = self.entry_lat.get().strip() if do_gps else None
        lon = self.entry_lon.get().strip() if do_gps else None

        total = len(items); self.progress["value"]=0; self.progress["maximum"]=total
        self.log("=== Inicio ===")

        for i, iid in enumerate(items, start=1):
            src = self.item_path.get(iid)
            if not src or not os.path.exists(src):
                self.log("⚠️ Archivo no encontrado, se omite."); self.progress["value"]=i; continue

            new_name = self.tree.set(iid, "nuevo").strip()
            base = new_name if new_name else basename_noext(src)
            src_ext = ext_lower(src)

            try:
                # --- 1) Determinar salida
                created_new_file = False
                renamed = False

                if do_convert:
                    target = convert_to_webp(src, base)
                    created_new_file = True
                else:
                    target = src
                    if new_name:
                        new_full = os.path.join(os.path.dirname(src), base + src_ext)
                        if new_full != src:
                            os.rename(src, new_full)
                            target = new_full
                            renamed = True  # ya no hay "original", se movió

                # --- 2) Limpiar metadatos si procede
                if do_clean:
                    exiftool_clean_all(target)

                # --- 3) Escribir metadatos seleccionados
                if do_title:
                    exiftool_write_title(target, base, author=AUTHOR)
                if do_gps and lat and lon:
                    exiftool_write_gps(target, lat, lon)

                # --- 4) BORRAR ORIGINAL (PARCHE: solo si hay NUEVO archivo distinto)
                if do_delete:
                    if created_new_file and (target != src) and os.path.exists(target) and os.path.getsize(target) > 0:
                        try:
                            os.remove(src)
                        except Exception as e:
                            self.log(f"⚠️ No se pudo borrar original: {e}")
                    # si solo fue renombrado, no hay nada que borrar

                # --- 5) Actualizar fila (ruta/nombre/miniatura)
                self.item_path[iid] = target
                self.tree.set(iid, "original", os.path.basename(target))
                self.tree.item(iid, image=self.load_thumbnail(target), text="")

                self.log(f"✅ {i}/{total} → {os.path.basename(target)}")
            except Exception as e:
                self.log(f"❌ {i}/{total} ERROR: {e}")

            self.progress["value"]=i; self.update_idletasks()

        self.log("=== Fin ===")

    def clean_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Limpieza", "Selecciona filas en la tabla."); return
        if not messagebox.askyesno("Confirmar", "Se limpiarán TODOS los metadatos de los archivos seleccionados."):
            return
        for iid in sel:
            path = self.item_path.get(iid)
            if not path or not os.path.exists(path): continue
            try:
                exiftool_clean_all(path)
                self.tree.item(iid, image=self.load_thumbnail(path), text="")
                self.log(f"🧹 Limpio: {os.path.basename(path)}")
            except Exception as e:
                self.log(f"❌ Error limpiando {path}: {e}")

if __name__ == "__main__":
    app = App()
    app.mainloop()
