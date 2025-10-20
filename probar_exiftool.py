import subprocess
import os
from PIL import Image

ruta_imagen_original = "origen.png"
ruta_jpg = "test_convertido.jpg"

# 1. Convertir a JPG desde PNG
img = Image.open(ruta_imagen_original).convert("RGB")
img.save(ruta_jpg)
img.close()

# 2. Insertar metadatos
autor = "DECOTECH"
descripcion = "Caja de cartón prueba"
lat = -12.0464
lon = -77.0428

comando = f'exiftool.exe -Artist="{autor}" -ImageDescription="{descripcion}" -GPSLatitude={abs(lat)} -GPSLatitudeRef={"S" if lat < 0 else "N"} -GPSLongitude={abs(lon)} -GPSLongitudeRef={"W" if lon < 0 else "E"} -overwrite_original "{ruta_jpg}"'
print("🧠 Ejecutando:", comando)

resultado = subprocess.run(comando, shell=True, capture_output=True, text=True)

print("---- STDOUT ----")
print(resultado.stdout)
print("---- STDERR ----")
print(resultado.stderr)
