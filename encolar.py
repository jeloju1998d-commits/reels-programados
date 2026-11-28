"""Mete una publicación terminada (reel, carrusel, imagen suelta o historias) en la cola.

Reel (lo de siempre):
  python encolar.py --video "FINAL.mp4" --portada "portada.jpg" --cuenta ambas ^
      --fecha "2026-11-18 19:30" --descripcion-archivo "leyenda.txt" --nombre musculo-seguro

Carrusel (2 a 20 imágenes o vídeos, en orden; 4:5 recomendado):
  python encolar.py --tipo carrusel --archivos s1.png s2.png s3.mp4 --cuenta ambas ^
      --fecha "2026-11-20 13:00" --descripcion-archivo "leyenda.txt" --nombre gemelos

Imagen suelta (1 sola foto en el feed; --tipo imagen --archivos foto.png ...).

Historias (una o varias, se publican seguidas en ese orden; 9:16, vídeos de 3 a 60 s):
  python encolar.py --tipo historia --archivos s1.png s2.png s3.png --cuenta jesuss.fitness ^
      --fecha "2026-11-20 10:00" --nombre hinchazon

Con --cuenta ambas crea dos entradas: jesuslopezfitness con los archivos originales y
jesuss.fitness con variantes (vídeo recodificado y 0,3 s más corto; imagen con un recorte
mínimo y otra compresión), --desfase-horas más tarde.
No sube nada: eso lo hace el «git push» posterior.
"""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

COLA = Path(__file__).parent / "cola"
CUENTAS = ("jesuslopezfitness", "jesuss.fitness")
RECORTE_VARIANTE = 0.3  # segundos que se quitan del final de los vídeos en la variante
VIDEO = {".mp4", ".mov", ".m4v"}
IMAGEN = {".jpg", ".jpeg", ".png", ".webp"}


def ffprobe(archivo):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(archivo)],
        capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def revisar_video(archivo, tipo):
    info = ffprobe(archivo)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    dur = float(info["format"]["duration"])
    avisos = []
    if v["codec_name"] not in ("h264", "hevc"):
        avisos.append(f"códec {v['codec_name']} (debe ser H264 o HEVC)")
    if int(v["width"]) > 1920:
        avisos.append(f"ancho {v['width']} px (máximo 1920)")
    maximo = 60 if tipo == "historia" else 900
    if not 3 <= dur <= maximo:
        avisos.append(f"duración {dur:.0f} s (entre 3 y {maximo} s)")
    if avisos:
        sys.exit(f"Instagram no aceptará {Path(archivo).name}: " + "; ".join(avisos))
    return dur


def revisar_imagen(archivo, tipo):
    s = ffprobe(archivo)["streams"][0]
    an, al = int(s["width"]), int(s["height"])
    prop = an / al
    if tipo in ("carrusel", "imagen") and not (0.8 - 0.01 <= prop <= 1.91):
        sys.exit(f"{Path(archivo).name} mide {an}×{al}: en carruseles la proporción va de 4:5 a 1,91:1")
    if tipo == "historia" and abs(prop - 9 / 16) > 0.02:
        print(f"Aviso: {Path(archivo).name} mide {an}×{al}; en historias lo ideal es 9:16")


def preparar_video(origen, destino, variante, dur):
    if variante:
        # Mismo contenido, archivo distinto: nueva codificación y final 0,3 s más corto
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(origen), "-t", f"{dur - RECORTE_VARIANTE:.3f}",
                        "-c:v", "libx264", "-crf", "19", "-preset", "medium", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
                        "-movflags", "+faststart", str(destino)], check=True)
    else:
        # Vídeo intacto; el audio se rehace solo si no cumple lo que pide Instagram (AAC, máx. 48 kHz)
        au = next((s for s in ffprobe(origen)["streams"] if s["codec_type"] == "audio"), None)
        audio_ok = au is None or (au["codec_name"] == "aac" and int(au.get("sample_rate", 0)) <= 48000)
        audio = ["-c:a", "copy"] if audio_ok else ["-c:a", "aac", "-ar", "48000", "-b:a", "192k"]
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(origen), "-c:v", "copy", *audio,
                        "-movflags", "+faststart", str(destino)], check=True)


def preparar_imagen(origen, destino, variante):
    """Instagram solo admite JPEG (sRGB, máx. 8 MB). La variante recorta 4 px y vuelve a escalar."""
    filtro = ["-vf", "crop=iw-4:ih-4,scale=iw+4:ih+4"] if variante else []
    calidad = "3" if variante else "2"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(origen), *filtro, "-frames:v", "1",
                    "-q:v", calidad, "-pix_fmt", "yuvj420p", str(destino)], check=True)
    if Path(destino).stat().st_size > 8e6:
        sys.exit(f"{Path(destino).name} pesa más de 8 MB, el máximo de Instagram para imágenes")


def encolar(a, cuenta, cuando, descripcion, archivos, variante):
    carpeta = COLA / f"{cuando:%Y-%m-%d_%H%M}_{cuenta.replace('.', '-')}_{a.nombre}"
    if carpeta.exists():
        sys.exit(f"Ya existe {carpeta.name}")
    carpeta.mkdir(parents=True)
    nombres = []
    for i, (origen, dur) in enumerate(archivos, 1):
        es_video = Path(origen).suffix.lower() in VIDEO
        if a.tipo == "reel":
            nombre = "video.mp4"
        else:
            nombre = f"{i:02d}.{'mp4' if es_video else 'jpg'}"
        destino = carpeta / nombre
        if es_video:
            preparar_video(origen, destino, variante, dur)
        else:
            preparar_imagen(origen, destino, variante)
        if destino.stat().st_size > 95e6:
            sys.exit(f"{nombre} pesa {destino.stat().st_size / 1e6:.0f} MB; GitHub no admite más de 100 MB por archivo")
        nombres.append(nombre)
    if a.tipo == "reel" and a.portada:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a.portada, "-frames:v", "1",
                        "-q:v", "2", "-pix_fmt", "yuvj420p", str(carpeta / "portada.jpg")], check=True)

    ficha = {"tipo": a.tipo, "cuenta": cuenta, "fecha": f"{cuando:%Y-%m-%d %H:%M}"}
    if a.tipo == "reel":
        ficha.update(prueba=not a.normal, graduacion=a.graduacion)
    else:
        ficha["archivos"] = nombres
    if a.tipo != "historia":
        ficha["descripcion"] = descripcion
    ficha["estado"] = "pendiente"
    (carpeta / "publicacion.json").write_text(json.dumps(ficha, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    mb = sum(p.stat().st_size for p in carpeta.iterdir()) / 1e6
    modo = ("modo prueba" if ficha.get("prueba") else "normal") if a.tipo == "reel" else f"{len(nombres)} archivos"
    print(f"En cola: {carpeta.name} ({a.tipo}, {mb:.1f} MB, {'variante, ' if variante else ''}{modo})")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tipo", default="reel", choices=("reel", "carrusel", "historia", "imagen"))
    p.add_argument("--video", help="reel: el vídeo")
    p.add_argument("--archivos", nargs="+", help="carrusel o historias: imágenes/vídeos en orden")
    p.add_argument("--portada")
    p.add_argument("--cuenta", required=True, choices=CUENTAS + ("ambas",))
    p.add_argument("--fecha", required=True, help='hora de Madrid, "AAAA-MM-DD HH:MM"')
    p.add_argument("--desfase-horas", type=float, default=0,
                   help="con --cuenta ambas: horas de retraso de jesuss.fitness")
    p.add_argument("--variante", action="store_true",
                   help="con una sola cuenta: usar las variantes en vez de los originales")
    p.add_argument("--descripcion", default="")
    p.add_argument("--descripcion-archivo")
    p.add_argument("--nombre", required=True, help="nombre corto, sin espacios ni tildes")
    p.add_argument("--normal", action="store_true", help="reel: publicar normal, no en modo prueba")
    p.add_argument("--graduacion", default="MANUAL", choices=("MANUAL", "SS_PERFORMANCE"))
    a = p.parse_args()

    cuando = datetime.strptime(a.fecha, "%Y-%m-%d %H:%M")
    if not re.fullmatch(r"[a-z0-9-]+", a.nombre):
        sys.exit("El nombre solo puede llevar minúsculas, números y guiones")
    descripcion = a.descripcion
    if a.descripcion_archivo:
        descripcion = Path(a.descripcion_archivo).read_text(encoding="utf-8").strip()
    if len(descripcion) > 2200:
        sys.exit(f"La descripción tiene {len(descripcion)} caracteres; el máximo es 2200")

    if a.tipo == "reel":
        if not a.video:
            sys.exit("Para un reel hace falta --video")
        origenes = [a.video]
    else:
        if not a.archivos:
            sys.exit("Para carrusel o historias hace falta --archivos")
        origenes = a.archivos
        if a.tipo == "carrusel" and not 2 <= len(origenes) <= 20:
            sys.exit("Un carrusel lleva de 2 a 20 archivos")
        if a.tipo == "imagen" and len(origenes) != 1:
            sys.exit("Una imagen suelta lleva exactamente 1 archivo")
    archivos = []
    for o in origenes:
        ext = Path(o).suffix.lower()
        if ext in VIDEO:
            archivos.append((o, revisar_video(o, a.tipo)))
        elif ext in IMAGEN and a.tipo != "reel":
            revisar_imagen(o, a.tipo)
            archivos.append((o, 0))
        else:
            sys.exit(f"No sé qué hacer con {Path(o).name}")

    if a.cuenta == "ambas":
        encolar(a, CUENTAS[0], cuando, descripcion, archivos, variante=False)
        encolar(a, CUENTAS[1], cuando + timedelta(hours=a.desfase_horas), descripcion, archivos, variante=True)
    else:
        encolar(a, a.cuenta, cuando, descripcion, archivos, variante=a.variante)


if __name__ == "__main__":
    main()
