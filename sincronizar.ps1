# Deja la copia local igual que GitHub. Hace falta después de cada limpieza semanal
# del historial (la copia local se queda con el historial antiguo y no podría subir cambios).
# Si hay cambios locales sin subir, se detiene y no toca nada.
$git = "C:\Program Files\Git\cmd\git.exe"
Set-Location $PSScriptRoot
if (& $git status --porcelain) { Write-Output "Hay cambios locales sin subir: no se sincroniza."; exit 1 }
& $git fetch -q origin
& $git reset -q --hard origin/main
& $git reflog expire --expire=now --all
& $git gc -q --prune=now
Write-Output ("Sincronizado: " + (& $git log --oneline -1))
