"""Mete un reel terminado en la cola de publicación.

Ejemplo (las dos cuentas, que es lo habitual):
  python encolar.py --video "ruta\\FINAL.mp4" --portada "ruta\\portada.jpg" ^
      --cuenta ambas --fecha "2026-11-18 19:30" ^
      --descripcion-archivo "ruta\\leyenda.txt" --nombre musculo-seguro-de-vida

Con --cuenta ambas crea dos entradas: jesuslopezfitness lleva el vídeo original
y jesuss.fitness una variante (recodificada y unas décimas más corta por el
final), publicada --desfase-horas más tarde.

Copia el vídeo (con el arranque rápido que pide Instagram), convierte la
portada a JPG y escribe publicacion.json. No sube nada: eso lo hace el
«git push» posterior.
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
RECORTE_VARIANTE = 0.3  # segundos que se quitan del final en la variante


def ffprobe(video):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(video)],
        capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def encolar(a, cuenta, cuando, descripcion, dur, variante):
    carpeta = COLA / f"{cuando:%Y-%m-%d_%H%M}_{cuenta.replace('.', '-')}_{a.nombre}"
    if carpeta.exists():
        sys.exit(f"Ya existe {carpeta.name}")
    carpeta.mkdir(parents=True)
    destino = str(carpeta / "video.mp4")

    if variante:
        # Mismo reel, archivo distinto: nueva codificación y final 0,3 s más corto
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a.video, "-t", f"{dur - RECORTE_VARIANTE:.3f}",
                        "-c:v", "libx264", "-crf", "19", "-preset", "medium", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
                        "-movflags", "+faststart", destino], check=True)
    else:
        # Vídeo intacto; el audio se rehace solo si no cumple lo que pide Instagram (AAC, máx. 48 kHz)
        au = next((s for s in ffprobe(a.video)["streams"] if s["codec_type"] == "audio"), None)
        audio_ok = au is None or (au["codec_name"] == "aac" and int(au.get("sample_rate", 0)) <= 48000)
        audio = ["-c:a", "copy"] if audio_ok else ["-c:a", "aac", "-ar", "48000", "-b:a", "192k"]
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a.video, "-c:v", "copy", *audio,
                        "-movflags", "+faststart", destino], check=True)
    mb = Path(destino).stat().st_size / 1e6
    if mb > 95:
        sys.exit(f"El vídeo pesa {mb:.0f} MB; GitHub no admite más de 100 MB por archivo")
    if a.portada:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", a.portada, "-frames:v", "1",
                        "-q:v", "2", "-pix_fmt", "yuvj420p", str(carpeta / "portada.jpg")], check=True)

    ficha = {
        "cuenta": cuenta,
        "fecha": f"{cuando:%Y-%m-%d %H:%M}",
        "prueba": not a.normal,
        "graduacion": a.graduacion,
        "descripcion": descripcion,
        "estado": "pendiente",
    }
    (carpeta / "publicacion.json").write_text(
        json.dumps(ficha, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"En cola: {carpeta.name} ({mb:.1f} MB, {'variante, ' if variante else ''}"
          f"{'modo prueba' if ficha['prueba'] else 'normal'})")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--video", required=True)
    p.add_argument("--portada")
    p.add_argument("--cuenta", required=True, choices=CUENTAS + ("ambas",))
    p.add_argument("--fecha", required=True, help='hora de Madrid, "AAAA-MM-DD HH:MM"')
    p.add_argument("--desfase-horas", type=float, default=0,
                   help="con --cuenta ambas: horas de retraso de jesuss.fitness")
    p.add_argument("--variante", action="store_true",
                   help="con una sola cuenta: usar el vídeo variante en vez del original")
    p.add_argument("--descripcion", default="")
    p.add_argument("--descripcion-archivo")
    p.add_argument("--nombre", required=True, help="nombre corto, sin espacios ni tildes")
    p.add_argument("--normal", action="store_true", help="publicar normal, no en modo prueba")
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

    info = ffprobe(a.video)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    dur = float(info["format"]["duration"])
    avisos = []
    if v["codec_name"] not in ("h264", "hevc"):
        avisos.append(f"códec {v['codec_name']} (debe ser H264 o HEVC)")
    if int(v["width"]) > 1920:
        avisos.append(f"ancho {v['width']} px (máximo 1920)")
    if not 3 <= dur <= 900:
        avisos.append(f"duración {dur:.0f} s (entre 3 s y 15 min)")
    if avisos:
        sys.exit("Instagram no aceptará este vídeo: " + "; ".join(avisos))

    if a.cuenta == "ambas":
        encolar(a, CUENTAS[0], cuando, descripcion, dur, variante=False)
        encolar(a, CUENTAS[1], cuando + timedelta(hours=a.desfase_horas), descripcion, dur, variante=True)
    else:
        encolar(a, a.cuenta, cuando, descripcion, dur, variante=a.variante)


if __name__ == "__main__":
    main()
