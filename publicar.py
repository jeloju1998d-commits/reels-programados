"""Publica en Instagram los reels de la carpeta cola/ cuya hora ya ha llegado.

Lo ejecuta GitHub Actions (cron cada 15 min; en la práctica ~1 vez por hora). Solo usa la biblioteca estándar.
Cada reel es una carpeta dentro de cola/ con:
  video.mp4, portada.jpg (opcional) y publicacion.json

Variables de entorno:
  IG_FB_TOKEN         token de usuario de Facebook de larga duración (inicio de sesión de Facebook);
                      se publica con el token de la página vinculada a cada cuenta de Instagram
  COMPROBAR=1         solo comprueba qué cuentas cubre el token, sin publicar
  GITHUB_REPOSITORY, GITHUB_SHA   los pone GitHub (para la URL de la portada)
  SIMULAR=1           no publica nada, solo dice lo que haría
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

API = "https://graph.facebook.com/v27.0"
SUBIDA = "https://rupload.facebook.com/ig-api-upload/v27.0"
ZONA = ZoneInfo("Europe/Madrid")
COLA = Path(__file__).parent / "cola"
MAX_RETRASO = timedelta(hours=12)  # si llega más tarde que esto, no se publica
SIMULAR = os.environ.get("SIMULAR", "") in ("1", "true")
# Reintentos de historias y carruseles (22/11/2026: el 21/11 Instagram dio 2207006,
# «no se encuentra el contenido multimedia», en la 2.ª historia de una secuencia)
REINTENTOS = 3          # intentos por historia o carrusel en una misma ejecución, con contenedor nuevo
PAUSA_REINTENTO = 20    # segundos entre intento e intento
PAUSA_HISTORIAS = 10    # segundos entre una historia y la siguiente
MAX_EJECUCIONES = 3     # ejecuciones seguidas con fallo antes de dejarlo en «error»
AVISOS = Path(__file__).parent / "avisos.txt"


def aviso(carpeta, texto):
    """Deja el fallo a la vista: en avisos.txt (lo lee el Diario cada mañana) y como error
    del resumen de la ejecución en GitHub."""
    linea = f"{datetime.now(ZONA).strftime('%Y-%m-%d %H:%M')} · {carpeta} · {texto}"
    with AVISOS.open("a", encoding="utf-8") as f:
        f.write(linea + "\n")
    print(f"::error title=Fallo al publicar {carpeta}::{texto[:300]}")


def llamar(url, datos=None, cabeceras=None, cuerpo=None, metodo=None):
    if datos is not None:
        cuerpo = urllib.parse.urlencode(datos).encode()
    pet = urllib.request.Request(url, data=cuerpo, headers=cabeceras or {}, method=metodo)
    try:
        with urllib.request.urlopen(pet, timeout=600) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        texto = e.read().decode(errors="replace")
        raise RuntimeError(f"Instagram respondió {e.code}: {texto}") from None


def llamar_json(url, cuerpo):
    """POST con cuerpo JSON (así vienen los ejemplos de Meta para trial_params)."""
    return llamar(url, cuerpo=json.dumps(cuerpo).encode(), metodo="POST",
                  cabeceras={"Content-Type": "application/json"})


def cuentas_facebook(token_usuario):
    """Con el token de usuario de Facebook (inicio de sesión de Facebook): las cuentas de
    Instagram vinculadas a sus páginas, con el token de cada página. {usuario: (ig_id, token_pagina)}"""
    r = llamar(f"{API}/me/accounts?fields=id,name,access_token,"
               f"instagram_business_account{{id,username}}&limit=100&access_token={token_usuario}")
    cuentas = {}
    for p in r.get("data", []):
        ig = p.get("instagram_business_account")
        if not ig:  # por si el campo anidado no viene: preguntar a la página
            ig = llamar(f"{API}/{p['id']}?fields=instagram_business_account{{id,username}}"
                        f"&access_token={p['access_token']}").get("instagram_business_account")
        if ig and ig.get("username"):
            cuentas[ig["username"].lower()] = (ig["id"], p["access_token"])
    return cuentas


def conexion(cuenta):
    """Devuelve (ig_id, token) de la cuenta usando el inicio de sesión de Facebook (IG_FB_TOKEN).
    El token unificado ya no se usa: con él Instagram ignora el modo prueba (17/11/2026)."""
    token = os.environ.get("IG_FB_TOKEN", "").strip()
    if not token:
        raise RuntimeError("Falta el secreto IG_FB_TOKEN (inicio de sesión de Facebook) en GitHub")
    cuentas = cuentas_facebook(token)
    if cuenta.lower() not in cuentas:
        raise RuntimeError(f"El token no cubre @{cuenta}; cubre: {', '.join(cuentas) or 'ninguna'}")
    return cuentas[cuenta.lower()]


def sigue_pendiente(carpeta):
    """Mira en GitHub (rama main, en este momento) que la entrada siga pendiente:
    así una ejecución vieja o una pausa de última hora no publican de más."""
    if not os.environ.get("GITHUB_ACTIONS"):
        return True
    try:
        subprocess.run(["git", "fetch", "-q", "origin", "main"], check=True, timeout=120)
        r = subprocess.run(["git", "show", f"origin/main:cola/{carpeta.name}/publicacion.json"],
                           capture_output=True, text=True, encoding="utf-8", check=True, timeout=60)
        return json.loads(r.stdout).get("estado") == "pendiente"
    except Exception as e:
        print(f"  no pude confirmar el estado en GitHub ({e}); por seguridad no se publica")
        return False


def url_publica(carpeta, nombre):
    """Enlace público al archivo en GitHub, fijado a la versión que se está ejecutando
    (la de main en este momento, que es la que tiene los archivos de la cola)."""
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        return ""
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                             check=True, timeout=30).stdout.strip()
    except Exception:
        sha = os.environ.get("GITHUB_SHA", "")
    ruta = urllib.parse.quote(f"cola/{carpeta.name}/{nombre}")
    return f"https://raw.githubusercontent.com/{repo}/{sha}/{ruta}"


def esperar(contenedor, token, que="el archivo"):
    pausas = [2, 3, 5, 10] + [20] * 40  # rápido al principio (las imágenes tardan poco); hasta ~13 min
    for pausa in pausas:
        estado = llamar(f"{API}/{contenedor}?fields=status_code,status&access_token={token}")
        if estado.get("status_code") == "FINISHED":
            return
        if estado.get("status_code") in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram rechazó {que}: {estado}")
        print(f"    {que}: {estado.get('status_code')} {estado.get('status', '')}"[:200])
        time.sleep(pausa)
    raise RuntimeError(f"Instagram no terminó de procesar {que} a tiempo")


def publicar_contenedor(ig_id, token, contenedor, carpeta, descripcion):
    """Los frenos de siempre y, si todo está bien, publicar. Devuelve (media_id, enlace)."""
    if not sigue_pendiente(carpeta):
        raise Pausado()
    ya = ya_publicado(ig_id, token, descripcion)
    if ya:
        raise YaPublicado(ya)
    media = llamar(f"{API}/{ig_id}/media_publish",
                   datos={"creation_id": contenedor, "access_token": token})["id"]
    try:
        enlace = llamar(f"{API}/{media}?fields=permalink&access_token={token}").get("permalink", "")
    except RuntimeError:
        enlace = ""
    return media, enlace


def es_reintentable(e):
    """Errores de Instagram que se arreglan creando el contenedor de nuevo: 2207006 (no encuentra
    el contenido), 2207027 (aún no está listo) o los que él mismo marca como pasajeros."""
    texto = str(e).replace(" ", "")
    return any(c in texto for c in ("2207006", "2207027", '"is_transient":true'))


def con_reintentos(paso, que):
    """Ejecuta paso() (crear contenedor, esperar y publicar) hasta REINTENTOS veces."""
    for intento in range(1, REINTENTOS + 1):
        try:
            return paso()
        except (Pausado, YaPublicado):
            raise
        except RuntimeError as e:
            if not es_reintentable(e) or intento == REINTENTOS:
                raise
            print(f"  {que}: Instagram falló ({str(e)[:160]}); intento {intento + 1} de "
                  f"{REINTENTOS} con un contenedor nuevo dentro de {PAUSA_REINTENTO} s")
            time.sleep(PAUSA_REINTENTO)


def publicar(carpeta, datos, ensayo=False, ficha=None):
    tipo = datos.get("tipo", "reel")
    if tipo == "carrusel":
        return publicar_carrusel(carpeta, datos, ensayo)
    if tipo == "imagen":
        return publicar_imagen(carpeta, datos, ensayo)
    if tipo == "historia":
        return publicar_historias(carpeta, datos, ensayo, ficha)
    return publicar_reel(carpeta, datos, ensayo)


def publicar_imagen(carpeta, datos, ensayo=False):
    """Una sola foto en el feed (28/11/2026: los posts de cambios de clientes llevan 1 imagen)."""
    ig_id, token = conexion(datos["cuenta"])
    return con_reintentos(lambda: _imagen(carpeta, datos, ensayo, ig_id, token), "la imagen")


def _imagen(carpeta, datos, ensayo, ig_id, token):
    nombre = datos["archivos"][0]
    url = url_publica(carpeta, nombre)
    if not url:
        raise RuntimeError("Sin enlace público a los archivos (solo funciona en GitHub)")
    contenedor = llamar_json(f"{API}/{ig_id}/media", {
        "image_url": url, "caption": datos.get("descripcion", ""), "access_token": token})["id"]
    esperar(contenedor, token, nombre)
    if ensayo:
        return contenedor, "1 imagen"
    return publicar_contenedor(ig_id, token, contenedor, carpeta, datos.get("descripcion", ""))


def publicar_carrusel(carpeta, datos, ensayo=False):
    ig_id, token = conexion(datos["cuenta"])
    return con_reintentos(lambda: _carrusel(carpeta, datos, ensayo, ig_id, token), "el carrusel")


def _carrusel(carpeta, datos, ensayo, ig_id, token):
    hijos = []
    for nombre in datos["archivos"]:
        url = url_publica(carpeta, nombre)
        if not url:
            raise RuntimeError("Sin enlace público a los archivos (solo funciona en GitHub)")
        campos = {"is_carousel_item": True, "access_token": token}
        if nombre.endswith(".mp4"):
            campos.update(media_type="VIDEO", video_url=url)
        else:
            campos["image_url"] = url
        hijos.append(llamar_json(f"{API}/{ig_id}/media", campos)["id"])
    for nombre, hijo in zip(datos["archivos"], hijos):  # se procesan a la vez; aquí solo se espera
        esperar(hijo, token, nombre)
        print(f"  diapositiva {nombre} lista ({hijo})")
    padre = llamar_json(f"{API}/{ig_id}/media", {
        "media_type": "CAROUSEL", "children": ",".join(hijos),
        "caption": datos.get("descripcion", ""), "access_token": token})["id"]
    esperar(padre, token, "el carrusel")
    if ensayo:
        return padre, f"{len(hijos)} diapositivas"
    return publicar_contenedor(ig_id, token, padre, carpeta, datos.get("descripcion", ""))


def publicar_historias(carpeta, datos, ensayo=False, ficha=None):
    """Una historia por archivo, en orden. Va apuntando cada una al publicarla: si algo falla
    a mitad, las ya publicadas no se repiten."""
    ig_id, token = conexion(datos["cuenta"])
    hechas = {h["archivo"] for h in datos.get("publicadas", [])}
    primera = True
    for nombre in datos["archivos"]:
        if nombre in hechas:
            continue
        url = url_publica(carpeta, nombre)
        if not url:
            raise RuntimeError("Sin enlace público a los archivos (solo funciona en GitHub)")
        if not primera and not ensayo:
            time.sleep(PAUSA_HISTORIAS)  # que Instagram no reciba las historias seguidas
        primera = False

        def una(nombre=nombre, url=url):
            campos = {"media_type": "STORIES", "access_token": token}
            campos["video_url" if nombre.endswith(".mp4") else "image_url"] = url
            cont = llamar_json(f"{API}/{ig_id}/media", campos)["id"]
            esperar(cont, token, nombre)
            if ensayo:
                print(f"  historia {nombre} lista ({cont}); no se publica")
                return None
            return publicar_contenedor(ig_id, token, cont, carpeta, "")

        hecho = con_reintentos(una, f"historia {nombre}")
        if ensayo:
            continue
        media, enlace = hecho
        datos.setdefault("publicadas", []).append({"archivo": nombre, "media_id": media})
        if ficha:
            ficha.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  historia {nombre} publicada ({media})")
    if ensayo:
        return "", f"{len(datos['archivos'])} historias"
    return datos["publicadas"][-1]["media_id"] if datos.get("publicadas") else "", ""


def publicar_reel(carpeta, datos, ensayo=False):
    video = carpeta / "video.mp4"
    if not video.exists():
        raise RuntimeError("No está video.mp4")

    ig_id, token = conexion(datos["cuenta"])

    campos = {
        "media_type": "REELS",
        "upload_type": "resumable",
        "caption": datos.get("descripcion", ""),
        "access_token": token,
    }
    if datos.get("prueba", True):
        campos["trial_params"] = {"graduation_strategy": datos.get("graduacion", "MANUAL")}
    portada = carpeta / "portada.jpg"
    if portada.exists() and url_publica(carpeta, "portada.jpg"):
        campos["cover_url"] = url_publica(carpeta, "portada.jpg")

    contenedor = llamar_json(f"{API}/{ig_id}/media", campos)["id"]
    print(f"  contenedor {contenedor}; subiendo {video.stat().st_size / 1e6:.1f} MB")
    try:
        llamar(f"{SUBIDA}/{contenedor}", cuerpo=video.read_bytes(), metodo="POST", cabeceras={
            "Authorization": f"OAuth {token}",
            "offset": "0",
            "file_size": str(video.stat().st_size),
            "Content-Type": "application/octet-stream",
        })
        print("  subida directa correcta")
    except RuntimeError as e:
        # Vía alternativa: que Instagram descargue el vídeo del repositorio público
        url = url_publica(carpeta, "video.mp4")
        if not url:
            raise
        print(f"  la subida directa falló ({e}); pruebo por URL")
        campos.pop("upload_type")
        campos["video_url"] = url
        contenedor = llamar_json(f"{API}/{ig_id}/media", campos)["id"]
        print(f"  contenedor {contenedor} por URL")

    esperar(contenedor, token, "el vídeo")
    if ensayo:  # el contenedor sin publicar caduca solo a las 24 h
        return contenedor, "por URL" if "video_url" in campos else "subida directa"
    return publicar_contenedor(ig_id, token, contenedor, carpeta, datos.get("descripcion", ""))


class Pausado(Exception):
    """La entrada dejó de estar pendiente en GitHub mientras se preparaba."""


class YaPublicado(Exception):
    """En esa cuenta ya hay una publicación reciente con la misma descripción."""


def ya_publicado(ig_id, token, descripcion):
    """Segundo freno contra duplicados: mira las últimas publicaciones de la cuenta y, si en
    los últimos 3 días ya hay una con la misma descripción, devuelve su enlace."""
    if not descripcion.strip():
        return ""
    r = llamar(f"{API}/{ig_id}/media?fields=caption,timestamp,permalink&limit=25&access_token={token}")
    limite = datetime.now(ZONA) - timedelta(days=3)
    for m in r.get("data", []):
        cuando = datetime.strptime(m["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
        if cuando >= limite and (m.get("caption") or "").strip() == descripcion.strip():
            return m.get("permalink") or m.get("id", "")
    return ""


def comprobar():
    """Dice qué cuentas cubre el token de Facebook, sin publicar nada ni mostrar tokens."""
    lineas = [f"Comprobación del {datetime.now(ZONA):%Y-%m-%d %H:%M}"]
    token = os.environ.get("IG_FB_TOKEN", "").strip()
    if not token:
        lineas.append("IG_FB_TOKEN: vacío")
    else:
        try:
            yo = llamar(f"{API}/me?fields=id,name&access_token={token}")
            lineas.append(f"IG_FB_TOKEN: usuario de Facebook OK ({yo.get('name', '')})")
            dbg = llamar(f"{API}/me/permissions?access_token={token}")
            concedidos = sorted(p["permission"] for p in dbg.get("data", []) if p.get("status") == "granted")
            lineas.append(f"Permisos: {', '.join(concedidos)}")
            for usuario, (ig_id, _) in cuentas_facebook(token).items():
                lineas.append(f"Cubre @{usuario} (id {ig_id})")
        except Exception as e:
            lineas.append(f"IG_FB_TOKEN: ERROR {str(e).replace(token, '***')[:500]}")
    if os.environ.get("ENSAYAR", "") in ("1", "true"):
        # Ensayo: sube y deja listo cada reel pendiente, pero NO lo publica
        for ficha in sorted(COLA.glob("*/publicacion.json")):
            datos = json.loads(ficha.read_text(encoding="utf-8"))
            if datos.get("estado", "pendiente") != "pendiente":
                continue
            try:
                _, via = publicar(ficha.parent, datos, ensayo=True)
                modo = "modo prueba" if datos.get("prueba", True) else "normal"
                lineas.append(f"ENSAYO {ficha.parent.name}: OK, Instagram acepta el vídeo ({modo}, {via}); no publicado")
            except Exception as e:
                lineas.append(f"ENSAYO {ficha.parent.name}: ERROR {str(e)[:500]}")
    print("\n".join(lineas))
    (Path(__file__).parent / "comprobacion.txt").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    sys.exit(0)


def comprobar_modo(cuenta, media):
    """Tras publicar un reel, mira si Instagram respetó el modo prueba. Los reels de prueba
    vuelven con is_shared_to_feed=false; el que salió normal el 20/11 (keto), con true.
    Devuelve "prueba", "normal" o "" si no se pudo leer."""
    for pausa in (0, 10, 30):
        time.sleep(pausa)
        try:
            _, token = conexion(cuenta)
            r = llamar(f"{API}/{media}?fields=is_shared_to_feed&access_token={token}")
        except Exception as e:
            print(f"  no pude comprobar el modo ({str(e)[:200]})")
            continue
        if "is_shared_to_feed" in r:
            return "normal" if r["is_shared_to_feed"] else "prueba"
    return ""


def main():
    if os.environ.get("COMPROBAR", "") in ("1", "true"):
        comprobar()
    ahora = datetime.now(ZONA)
    fallos = 0
    for ficha in sorted(COLA.glob("*/publicacion.json")):
        carpeta = ficha.parent
        datos = json.loads(ficha.read_text(encoding="utf-8"))
        if datos.get("estado", "pendiente") != "pendiente":
            continue
        cuando = datetime.strptime(datos["fecha"], "%Y-%m-%d %H:%M").replace(tzinfo=ZONA)
        if cuando > ahora:
            print(f"{carpeta.name}: programado para {datos['fecha']}, aún no toca")
            continue

        tipo = datos.get("tipo", "reel")
        modo = ("prueba" if datos.get("prueba", True) else "normal") if tipo == "reel" else tipo
        print(f"{carpeta.name}: toca publicar en @{datos['cuenta']} ({modo})")
        if SIMULAR:
            print("  SIMULACIÓN: no se publica")
            continue
        if ahora - cuando > MAX_RETRASO:
            fallos += 1
            texto = "Han pasado más de 12 h desde la hora programada; no se publica"
            if datos.get("ultimo_error"):
                texto += f" (último error: {datos['ultimo_error'][:200]})"
            datos.update(estado="error", error=texto)
            aviso(carpeta.name, texto)
            print(f"  ERROR: {texto}")
            ficha.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            continue
        try:
            media, enlace = publicar(carpeta, datos, ficha=ficha)
            datos.update(estado="publicado", media_id=media, enlace=enlace,
                         publicado_el=datetime.now(ZONA).strftime("%Y-%m-%d %H:%M"))
            for f in carpeta.iterdir():  # los archivos ya no hacen falta en el repositorio
                if f.suffix.lower() in (".mp4", ".jpg"):
                    f.unlink()
            print(f"  publicado: {enlace or media}")
            if tipo == "reel" and datos.get("prueba", True):
                real = comprobar_modo(datos["cuenta"], media)
                datos["modo_real"] = real or "sin comprobar"
                if real == "normal":
                    fallos += 1  # el flujo sale en rojo y GitHub avisa por correo
                    datos["aviso"] = "Instagram lo publicó en NORMAL aunque se pidió modo prueba"
                    aviso(carpeta.name, datos["aviso"])
                    print("  AVISO: Instagram ignoró el modo prueba; el reel ha salido en normal")
                else:
                    print(f"  modo comprobado: {datos['modo_real']}")
        except Pausado:
            print("  ya no está pendiente en GitHub (pausado o publicado): no se publica")
            continue
        except YaPublicado as e:
            datos.update(estado="publicado", enlace=str(e),
                         nota="ya estaba publicado en la cuenta; no se ha vuelto a publicar")
            print(f"  ya estaba publicado ({e}): no se publica otra vez")
        except Exception as e:
            fallos += 1  # el flujo sale en rojo y GitHub manda el correo de fallo
            seguidos = datos.get("fallos_seguidos", 0) + 1
            if tipo in ("historia", "carrusel", "imagen") and seguidos < MAX_EJECUCIONES:
                # Historias y carruseles: sigue pendiente y se reintenta en la próxima ejecución
                # (las historias ya publicadas están apuntadas y no se repiten)
                datos.update(fallos_seguidos=seguidos, ultimo_error=str(e))
                texto = (f"falló (intento {seguidos} de {MAX_EJECUCIONES}); se reintenta en la "
                         f"próxima ejecución. {str(e)[:300]}")
            else:  # reels (no se reintentan solos) o historias/carruseles tras MAX_EJECUCIONES
                datos.update(estado="error", error=str(e), fallos_seguidos=seguidos)
                texto = f"ERROR, no se reintenta más: {str(e)[:300]}"
            aviso(carpeta.name, texto)
            print(f"  ERROR: {texto}")
        ficha.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()
