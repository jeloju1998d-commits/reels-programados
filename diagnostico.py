"""Diagnóstico del modo prueba SIN PUBLICAR NADA.

Solo crea «contenedores» de Instagram (borradores que caducan solos a las 24 h) y lee
datos. Este archivo no contiene ninguna llamada a media_publish: no puede publicar.

Idea: si Instagram lee de verdad trial_params, un valor inválido
(graduation_strategy="NO_EXISTE") o un trial_params vacío debería dar error. Si los
acepta sin quejarse, es que el parámetro no le llega o lo ignora.
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://graph.facebook.com/v27.0"
API_IG = "https://graph.instagram.com/v27.0"
SALIDA = Path(__file__).parent / "diagnostico.txt"
lineas = []


def log(texto):
    print(texto)
    lineas.append(texto)


def peticion(url, metodo="GET", form=None, json_cuerpo=None, tokens=()):
    cuerpo, cab = None, {}
    if form is not None:
        cuerpo = urllib.parse.urlencode(form).encode()
    if json_cuerpo is not None:
        cuerpo, cab = json.dumps(json_cuerpo).encode(), {"Content-Type": "application/json"}
    pet = urllib.request.Request(url, data=cuerpo, headers=cab, method=metodo)
    try:
        with urllib.request.urlopen(pet, timeout=120) as r:
            texto = r.read().decode()
            ok = True
    except urllib.error.HTTPError as e:
        texto = e.read().decode(errors="replace")
        ok = False
    for t in tokens:  # nunca escribir tokens en el informe
        if t:
            texto = texto.replace(t, "***")
    return ok, texto[:400]


def cuentas_facebook_completo(token_usuario):
    url = (f"{API}/me/accounts?fields=id,name,access_token,instagram_business_account{{id,username}}"
           f"&limit=100&access_token={token_usuario}")
    with urllib.request.urlopen(url, timeout=120) as r:
        datos = json.loads(r.read().decode())
    cuentas = {}
    for p in datos.get("data", []):
        ig = p.get("instagram_business_account") or {}
        if ig.get("username"):
            cuentas[ig["username"].lower()] = (ig["id"], p["access_token"], p.get("name"))
    return cuentas


def variantes(ig_id, token, host=API):
    """Crea contenedores reanudables (sin vídeo) con distintas formas de enviar trial_params."""
    base = {"media_type": "REELS", "upload_type": "resumable", "caption": "diagnostico (no se publica)"}
    pruebas = [
        ("sin trial_params (control)", "json", {}),
        ("JSON anidado, MANUAL (lo que usamos)", "json", {"trial_params": {"graduation_strategy": "MANUAL"}}),
        ("JSON anidado, valor INVÁLIDO", "json", {"trial_params": {"graduation_strategy": "NO_EXISTE"}}),
        ("JSON anidado, vacío {}", "json", {"trial_params": {}}),
        ("formulario, texto JSON MANUAL", "form", {"trial_params": json.dumps({"graduation_strategy": "MANUAL"})}),
        ("formulario, texto JSON INVÁLIDO", "form", {"trial_params": json.dumps({"graduation_strategy": "NO_EXISTE"})}),
        ("formulario, trial_params basura", "form", {"trial_params": "esto no es json"}),
        ("formulario, parámetro inventado", "form", {"parametro_que_no_existe": "1"}),
    ]
    for nombre, modo, extra in pruebas:
        datos = dict(base, **extra, access_token=token)
        if modo == "json":
            ok, t = peticion(f"{host}/{ig_id}/media", "POST", json_cuerpo=datos, tokens=[token])
        else:
            ok, t = peticion(f"{host}/{ig_id}/media", "POST", form=datos, tokens=[token])
        log(f"    [{ 'OK ' if ok else 'ERR'}] {nombre}: {t}")


def main():
    """Cuarta ronda: ensayo de carruseles e historias de la cola marcados como "ensayo".
    Usa publicar.py con ensayo=True: crea los borradores y para ANTES de media_publish."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    import publicar as pub
    log("=== DIAGNÓSTICO 4 (no publica nada): ensayo de carruseles e historias ===")
    for ficha in sorted((Path(__file__).parent / "cola").glob("*/publicacion.json")):
        datos = json.loads(ficha.read_text(encoding="utf-8"))
        if datos.get("estado") != "ensayo":
            continue
        try:
            _, detalle = pub.publicar(ficha.parent, datos, ensayo=True)
            log(f"ENSAYO {ficha.parent.name}: OK, Instagram acepta {detalle}; no publicado")
        except Exception as e:
            log(f"ENSAYO {ficha.parent.name}: ERROR {str(e)[:600]}")
    SALIDA.write_text("\n".join(lineas) + "\n", encoding="utf-8")


def main_ronda3():
    """Tercera ronda: comparar todo lo que la API dice de las dos cuentas."""
    log("=== DIAGNÓSTICO 3 (no publica nada): comparación de cuentas ===")
    fb = os.environ.get("IG_FB_TOKEN", "").strip()
    secretos = [fb] + [os.environ.get(n, "") for n in os.environ if n.startswith("IG_TOKEN")]
    cuentas = cuentas_facebook_completo(fb)
    campos = ["username", "name", "followers_count", "follows_count", "media_count", "biography", "website",
              "profile_picture_url", "ig_id", "account_type", "is_published", "has_profile_pic",
              "shopping_product_tag_eligibility", "is_eligible_for_trial_reels", "trial_reels_eligibility",
              "can_create_trial_reels", "recommendation_eligibility", "is_private", "legacy_instagram_user_id"]
    for usuario, (ig_id, token_pag, pagina) in sorted(cuentas.items()):
        log(f"\n## @{usuario} (página vinculada «{pagina}», id {ig_id})")
        for c in campos:
            ok, t = peticion(f"{API}/{ig_id}?fields={c}&access_token={token_pag}", tokens=secretos)
            if ok:
                try:
                    v = json.loads(t).get(c)
                except Exception:
                    v = t
                if c in ("biography", "profile_picture_url") and v:
                    v = f"(sí, {len(str(v))} caracteres)"
                log(f"  {c}: {v}")
            else:
                msg = json.loads(t)["error"]["message"] if t.startswith("{") else t
                log(f"  {c}: — ({msg[:90]})")
        ok, t = peticion(f"{API}/{ig_id}/content_publishing_limit?fields=config,quota_usage&access_token={token_pag}",
                         tokens=secretos)
        log(f"  cupo de publicación: {t}")
        # Lo que dice la conexión de Instagram (Business Login) si está disponible
        tok_ig = os.environ.get("IG_TOKEN_" + usuario.replace(".", "_").upper(), "").strip()
        if tok_ig:
            ok, t = peticion(f"{API}/{ig_id}?fields=username&access_token={tok_ig}", tokens=secretos)
            log(f"  token unificado ve la cuenta: {'sí' if ok else 'no'}")
    SALIDA.write_text("\n".join(lineas) + "\n", encoding="utf-8")


def main_ronda2():
    """Segunda ronda: ¿el reel de prueba de las 09:56 aparece en la cuadrícula de la cuenta?"""
    log("=== DIAGNÓSTICO 2 (no publica nada): reels publicados hoy ===")
    fb = os.environ.get("IG_FB_TOKEN", "").strip()
    secretos = [fb] + [os.environ.get(n, "") for n in os.environ if n.startswith("IG_TOKEN")]
    cuentas = cuentas_facebook_completo(fb)
    campos = "id,timestamp,media_type,media_product_type,is_shared_to_feed,permalink,shortcode"
    for usuario, (ig_id, token_pag, pagina) in sorted(cuentas.items()):
        log(f"\n## @{usuario}: últimas 8 de /media (lo que sale en el perfil)")
        with urllib.request.urlopen(f"{API}/{ig_id}/media?fields={campos}&limit=8&access_token={token_pag}",
                                    timeout=60) as r:
            for m in json.loads(r.read().decode()).get("data", []):
                log(f"  {m.get('timestamp')} {m.get('permalink')} tipo={m.get('media_product_type')} "
                    f"en_cuadricula={m.get('is_shared_to_feed')}")
    jsf = cuentas.get("jesuss.fitness")
    jlf = cuentas.get("jesuslopezfitness")
    for nombre, cuenta, media_id in (
            ("prueba 09:56 jesuss.fitness (inicio de sesión de Facebook)", jsf, "18668233627004069"),
            ("ChatGPT 09:26 jesuslopezfitness (unificado)", jlf, "17993511041862258"),
            ("Tu reloj 09:28 jesuss.fitness (unificado)", jsf, "18416395645089248")):
        if not cuenta:
            continue
        ok, t = peticion(f"{API}/{media_id}?fields={campos}&access_token={cuenta[1]}", tokens=secretos)
        log(f"\n{nombre}:\n  {'OK ' if ok else 'ERR'} {t}")
    SALIDA.write_text("\n".join(lineas) + "\n", encoding="utf-8")


def main_ronda1():
    log("=== DIAGNÓSTICO (no publica nada) ===")
    fb = os.environ.get("IG_FB_TOKEN", "").strip()
    secretos = [fb] + [os.environ.get(n, "") for n in os.environ if n.startswith("IG_TOKEN")]

    if fb:
        try:
            cuentas = cuentas_facebook_completo(fb)
        except Exception as e:
            cuentas = {}
            log(f"No pude leer las páginas: {str(e)[:200]}")
        for usuario, (ig_id, token_pag, pagina) in sorted(cuentas.items()):
            log(f"\n## @{usuario} · inicio de sesión de Facebook (página «{pagina}»)")
            ok, t = peticion(f"{API}/{ig_id}?fields=username,followers_count,media_count&access_token={token_pag}",
                             tokens=secretos)
            log(f"  cuenta: {t}")
            ok, t = peticion(f"{API}/{ig_id}/content_publishing_limit?fields=config,quota_usage&access_token={token_pag}",
                             tokens=secretos)
            log(f"  límite de publicación: {t}")
            log("  variantes de trial_params con token de PÁGINA:")
            variantes(ig_id, token_pag)
            log("  variantes de trial_params con token de USUARIO:")
            variantes(ig_id, fb)
            # Lo que Instagram dice de los reels publicados hoy en esa cuenta
            ok, t = peticion(f"{API}/{ig_id}/media?fields=id,timestamp,media_product_type,is_shared_to_feed,"
                             f"permalink&limit=4&access_token={token_pag}", tokens=secretos)
            log(f"  últimas publicaciones: {t}")
            try:
                with urllib.request.urlopen(f"{API}/{ig_id}/media?fields=id&limit=1&access_token={token_pag}",
                                            timeout=60) as r:
                    ultimas = json.loads(r.read().decode()).get("data", [])
            except Exception:
                ultimas = []
            for m in ultimas[:1]:
                for campo in ("is_trial", "trial_params", "is_trial_reel", "trial_reel_status",
                              "graduation_strategy", "media_product_type", "boost_eligibility_info"):
                    ok, t = peticion(f"{API}/{m['id']}?fields={campo}&access_token={token_pag}", tokens=secretos)
                    log(f"  campo «{campo}» del último reel: {'OK ' if ok else 'ERR'} {t}")

    # Comparación con los tokens del inicio de sesión unificado (los de antes)
    for nombre in sorted(n for n in os.environ if n.startswith("IG_TOKEN_")):
        tok = os.environ[nombre].strip()
        if not tok:
            continue
        ok, t = peticion(f"{API}/me/assigned_instagram_accounts?fields=id,username&access_token={tok}", tokens=secretos)
        try:
            ig = json.loads(t)["data"][0]
        except Exception:
            log(f"\n## {nombre}: no se pudo leer la cuenta ({t[:150]})")
            continue
        log(f"\n## @{ig['username']} · inicio de sesión unificado ({nombre})")
        variantes(ig["id"], tok)

    SALIDA.write_text("\n".join(lineas) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
