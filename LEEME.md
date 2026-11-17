# Programados en Instagram

Esta carpeta es un repositorio **público** de GitHub: todo lo que hay aquí lo puede ver cualquiera.
Solo deben entrar vídeos finales, portadas y descripciones. Nunca tokens ni contraseñas.

## Cómo funciona

1. `encolar.py` copia un reel terminado a `cola/<fecha>_<cuenta>_<nombre>/` con su `publicacion.json`.
2. Se sube a GitHub (`git push`).
3. GitHub Actions ejecuta `publicar.py` cada 15 minutos (puede retrasarse algo) y publica lo que ya toque.
4. Al publicar, la ficha pasa a `"estado": "publicado"` con el enlace y se borra el vídeo del repositorio.

## Carruseles e historias

- Carrusel: `encolar.py --tipo carrusel --archivos s1.png s2.png ...` (2 a 20 imágenes o vídeos, 4:5 a 1,91:1).
- Historias: `encolar.py --tipo historia --archivos s1.png s2.png ...` (se publican seguidas en ese orden;
  9:16; vídeos de 3 a 60 s; sin stickers, enlaces ni música: todo tiene que ir dentro de la imagen).
- Las imágenes se convierten a JPG (lo único que admite Instagram). El modo prueba solo existe para reels.

## Las dos cuentas a la vez

`encolar.py --cuenta ambas` crea dos entradas: `jesuslopezfitness` con el vídeo original y `jesuss.fitness`
con una variante (recodificada y 0,3 s más corta por el final). `--desfase-horas N` retrasa la segunda cuenta.

## Limpieza del historial

Cada lunes a las 03:30 (UTC) GitHub rehace el historial con solo la versión actual, para que
los vídeos ya publicados dejen de ocupar sitio. Después, la copia de este ordenador se queda
desfasada: antes de tocar nada aquí, ejecutar `sincronizar.ps1`.

## publicacion.json

- `cuenta`: `jesuslopezfitness` o `jesuss.fitness`
- `fecha`: hora de Madrid, `AAAA-MM-DD HH:MM`
- `prueba`: `true` = reel de prueba (solo no seguidores)
- `graduacion`: `MANUAL` (lo pasas tú a seguidores desde la app) o `SS_PERFORMANCE` (pasa solo si funciona bien)
- `estado`: `pendiente`, `publicado` o `error`

Para cancelar un reel programado: borrar su carpeta de `cola/` y subir el cambio.
Si algo falla, la ficha queda en `error` con el motivo y GitHub manda un correo; no se reintenta solo.
Si pasan más de 12 h de la hora programada sin publicarse, ya no se publica.

## Secretos en GitHub (Settings → Secrets and variables → Actions)

- `IG_TOKEN`: token del «inicio de sesión unificado» de la app de Meta; un solo token puede cubrir las dos cuentas.
- Opcionales, si alguna cuenta necesita token propio: `IG_TOKEN_JESUSLOPEZFITNESS`, `IG_TOKEN_JESUSS_FITNESS`.

Para ver qué cuentas cubre el token sin publicar nada: Actions → Publicar reels programados → Run workflow → marcar «Solo comprobar».
