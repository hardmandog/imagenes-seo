OPTIMIZADOR SEO – Guía rápida
=============================

Aplicación de escritorio (Tkinter) para optimizar imágenes en lote: convierte a sRGB, ajusta calidad/peso, genera versiones WEBP y escribe metadatos SEO/ACCESIBILIDAD mediante ExifTool.

Requisitos
----------
- Python 3.8+
- Pillow (`python -m pip install pillow`)
- ExifTool accesible en el sistema (ej.: `C:\\Tools\\exiftool.exe` en Windows o `exiftool` en PATH)
- Opcional: `tkinterdnd2` para arrastrar/soltar archivos o carpetas (`python -m pip install tkinterdnd2`)

Uso básico
----------
1. Ejecuta `python optimizador_seo2.py`.
2. Indica la ruta de ExifTool y la carpeta de salida.
3. Añade archivos o carpetas a la lista (arrastre si instalaste `tkinterdnd2`).
4. Ajusta calidad JPG/WEBP, dimensiones máximas y flags (convertir PNG→JPG, forzar fondo blanco, generar WEBP, limpiar metadatos, DPI 96, sobrescribir, etc.).
5. Completa los campos de metadatos (autor, título, descripción, alt text, palabras clave, derechos, licencias, GPS) y pulsa **Procesar**.

Funciones principales
---------------------
- Conversión a sRGB con preservación de alfa cuando se mantiene el formato con transparencia.
- Redimensionado opcional por ancho/alto máximo.
- Exportación en formato original o conversión a JPG, con WEBP adicional si se desea.
- Escritura de metadatos IPTC/XMP/EXIF y opcional limpieza de IA (`-all=`) y ajuste de DPI a 96.
- Renombrado opcional tras escribir metadatos y registro en vivo en la consola integrada.

Empaquetado (ejemplo)
---------------------
Para crear un ejecutable standalone se puede usar PyInstaller:
```
pyinstaller --noconfirm --onefile --windowed --name OPTIMIZADOR_SEO optimizador_seo2.py
```

Notas sobre ExifTool
--------------------
Si trabajas en Windows y prefieres la distribución portátil, coloca `exiftool(-k).exe` y la carpeta `exiftool_files` en algún directorio del PATH y cambia el nombre a `exiftool.exe`. Consulta más instrucciones en https://exiftool.org/install.html.
