# Eratone masaustu uygulamasini derler.   Calistir:  powershell -ExecutionPolicy Bypass -File build_eratone.ps1
# Cikti: dist\Eratone\Eratone.exe  (klasorun tamami birlikte tasinmali; Python gerekmez)
# Ikon degistiyse once:  .venv\Scripts\python.exe scripts\make_icon.py
#
# GUVENLI DERLEME (2026-11-15): PyInstaller artik dist\Eratone'a DOGRUDAN yazmiyor. Iki kez, derleme sirasinda acik/acilan
# Eratone dosyalari kilitledi; PyInstaller eski klasoru yarim silip kaldi (cacert.pem gitti -> NASA'ya baglanilamadi,
# HTTP 500). Yeni akis:
#   1. build\dist_yeni\Eratone'a derle ve DOGRULA (arayuz dosyalari + cacert.pem).
#   2. dist\Eratone'u dist\Eratone_eski olarak YENIDEN ADLANDIR. Eratone aciksa Windows buna izin vermez -> eski paket
#      hic bozulmadan durur, yeni paket build\dist_yeni'de bekler; Eratone'u kapatip betigi tekrar calistir.
#   3. Yeni paketi dist\Eratone'a tasi, eskiyi sil.
#   -Yerlestir : derlemeden, build\dist_yeni'de bekleyen paketi dogrulayip yerine koyar (Eratone kapandiktan sonra).
# Eratone acikken de derlenebilir (eski pakete dokunulmaz); yalnizca son adim (yerine koyma) kapanmasini bekler.
param([switch]$Yerlestir)
$ErrorActionPreference = "Stop"
$py = ".\.venv\Scripts\python.exe"
$stage = "build\dist_yeni"
$newPkg = "$stage\Eratone"

$running = Get-Process -Name Eratone -ErrorAction SilentlyContinue
if ($running) { Write-Host "`nNot: Eratone acik (PID $($running.Id -join ', ')). Paket hazirlanir; yerine koymak icin kapanmasi gerekir." }

if (-not $Yerlestir) {
    & $py -m pip install -q -r requirements-dev.txt
    if (-not (Test-Path "assets\eratone.ico")) { & $py scripts\make_icon.py }

    $ErrorActionPreference = "Continue"
    & $py -m PyInstaller --noconfirm --clean --distpath $stage Eratone.spec
    $code = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    if ($code -ne 0) { Write-Host "`nDERLEME BASARISIZ: PyInstaller cikis kodu $code (dist\Eratone'a dokunulmadi)"; exit 1 }
}

if (-not (Test-Path "$newPkg\Eratone.exe")) { Write-Host "`nDERLEME BASARISIZ: $newPkg\Eratone.exe olusmadi"; exit 1 }
if (-not (Test-Path "$newPkg\_internal\certifi\cacert.pem")) { Write-Host "`nDERLEME BASARISIZ: pakette certifi\cacert.pem yok (NASA HTTPS calismaz)"; exit 1 }

# Paketteki arayuz dosyalari projedekilerle birebir ayni mi?
$bad = @()
foreach ($f in Get-ChildItem "frontend\static" -Recurse -File) {
    $rel = $f.FullName.Substring((Resolve-Path "frontend\static").Path.Length)
    $pkg = "$newPkg\_internal\frontend\static$rel"
    if (-not (Test-Path $pkg) -or (Get-FileHash $pkg).Hash -ne (Get-FileHash $f.FullName).Hash) { $bad += $rel }
}
if ($bad.Count) { Write-Host "`nDERLEME BASARISIZ: pakette eksik/eski dosya: $($bad -join ', ')"; exit 1 }

# Yer degistirme: once yeniden adlandir (kilitliyse burada durur, eski paket saglam kalir)
New-Item -ItemType Directory -Force "dist" | Out-Null
if (Test-Path "dist\Eratone_eski") { Remove-Item -Recurse -Force "dist\Eratone_eski" -ErrorAction SilentlyContinue }
if (Test-Path "dist\Eratone") {
    try { Rename-Item "dist\Eratone" "Eratone_eski" -ErrorAction Stop }
    catch {
        Write-Host "`nYENI PAKET HAZIR ama yerine konamadi: dist\Eratone kullanimda (Eratone acik olabilir)."
        Write-Host "Eski paket SAGLAM birakildi. Eratone'u kapatip:  powershell -ExecutionPolicy Bypass -File build_eratone.ps1 -Yerlestir"
        Write-Host "Yeni paket: $newPkg"
        exit 2
    }
}
Move-Item $newPkg "dist\Eratone"
Remove-Item -Recurse -Force "dist\Eratone_eski" -ErrorAction SilentlyContinue

$exe = "dist\Eratone\Eratone.exe"
$mb = [math]::Round(((Get-ChildItem "dist\Eratone" -Recurse -File | Measure-Object Length -Sum).Sum / 1MB), 1)
Write-Host "`nHazir: $exe  (klasor: $mb MB, arayuz dosyalari + cacert dogrulandi)"
