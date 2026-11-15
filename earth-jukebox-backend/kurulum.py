"""Eratone — tek komutla kurulum ve başlatma.

Kaynak koddan çalıştırmak isteyen ekip arkadaşları için:

    python kurulum.py              ortamı kur (ilk sefer birkaç dakika) ve Eratone'u aç
    python kurulum.py --kur        yalnızca kur/güncelle, açma
    python kurulum.py --tarayici   pencere yerine tarayıcıda aç (http://127.0.0.1:3000)
    python kurulum.py --test       kur + testleri çalıştır (internet gerekmez)
    python kurulum.py --exe        kur + Eratone.exe derle  → dist\\Eratone\\Eratone.exe

Paylaşım paketi hazırlamak için (uygulamayı geliştiren bilgisayarda):

    python kurulum.py --paketle    paylasim\\ klasörüne iki zip üretir:
                                   Eratone_uygulama_*.zip → Python gerekmez, Eratone.exe'ye çift tıklanır
                                   Eratone_kaynak_*.zip   → kaynak kod; açıp "python kurulum.py"

Eratone'a geçirilecek diğer seçenekler aynen iletilir (örn. --no-intro, --debug).

Ne yapar: Python sürümünü denetler, proje klasöründe .venv oluşturur, requirements.txt'i kurar ve
kurulumu işaretler. requirements dosyaları değişmediyse sonraki çalıştırmalarda kurulumu atlar.
Gerekenler: Windows 10/11, Python 3.10+ (64 bit), ilk kurulumda internet.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import os
import platform
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
WINDOWS = os.name == "nt"
VPY = VENV / ("Scripts/python.exe" if WINDOWS else "bin/python")
STAMP = VENV / ".eratone_kurulum"
MIN_PY = (3, 10)

# Kaynak paketine girmeyecekler (yeniden üretilebilir ya da kişisel)
SKIP_DIRS = {".venv", "build", "dist", "cache", "paylasim", "__pycache__", ".pytest_cache", ".git", ".idea", ".vscode"}
SKIP_FILES = {".env"}
SKIP_SUFFIXES = {".pyc", ".log"}

try:  # Türkçe karakterler her konsolda yazılabilsin
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except Exception:
    pass


def say(msg: str) -> None:
    print(f"[Eratone] {msg}", flush=True)


def fail(msg: str, code: int = 1) -> None:
    print(f"\n[Eratone] HATA: {msg}\n", file=sys.stderr, flush=True)
    sys.exit(code)


def run(cmd: list, **kw) -> int:
    return subprocess.call([str(c) for c in cmd], cwd=ROOT, **kw)


# ---------------- denetimler ----------------
def check_python() -> None:
    if sys.version_info < MIN_PY:
        fail(f"Python {MIN_PY[0]}.{MIN_PY[1]} veya üstü gerekli (bu: {platform.python_version()}). "
             "https://www.python.org/downloads/ adresinden kurun (kurulumda 'Add python.exe to PATH' işaretli olsun).")
    if struct.calcsize("P") * 8 != 64:
        fail("64 bit Python gerekli (bilimsel kütüphaneler 32 bit için paket sunmuyor).")


def check_webview2() -> None:
    """Pencere için Microsoft Edge WebView2 gerekir (Windows 11'de hazır gelir). Yalnızca uyarır."""
    if not WINDOWS:
        say("Not: Masaüstü penceresi Windows için hazırlandı; bu sistemde --tarayici seçeneğini kullanın.")
        return
    try:
        import winreg
        guid = r"{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
        keys = [(winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{guid}"),
                (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{guid}"),
                (winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\EdgeUpdate\Clients\{guid}")]
        for hive, key in keys:
            try:
                with winreg.OpenKey(hive, key) as k:
                    if winreg.QueryValueEx(k, "pv")[0] not in ("", "0.0.0.0"):
                        return
            except OSError:
                continue
        say("Uyarı: Microsoft Edge WebView2 Runtime bulunamadı. Pencere açılmazsa kurun: "
            "https://developer.microsoft.com/microsoft-edge/webview2/  (ya da --tarayici kullanın)")
    except Exception:
        pass


# ---------------- kurulum ----------------
def req_files(dev: bool) -> list[Path]:
    files = [ROOT / "requirements.txt"]
    if dev:
        files.append(ROOT / "requirements-dev.txt")
    return files


def stamp_value(dev: bool) -> str:
    h = hashlib.sha256(platform.python_version().encode())
    for f in req_files(dev):
        h.update(f.read_bytes())
    return h.hexdigest()


def installed_ok(dev: bool) -> bool:
    if not (VPY.exists() and STAMP.exists()):
        return False
    have = STAMP.read_text(encoding="utf-8").split()
    return stamp_value(dev) in have or (not dev and stamp_value(True) in have)


def install(dev: bool = False) -> None:
    check_python()
    if installed_ok(dev):
        say("Kurulum güncel.")
        return
    if not VPY.exists():
        say(f"Sanal ortam oluşturuluyor: {VENV}")
        if run([sys.executable, "-m", "venv", VENV]) != 0 or not VPY.exists():
            fail("Sanal ortam (.venv) oluşturulamadı.")
    target = "requirements-dev.txt" if dev else "requirements.txt"
    say(f"Paketler kuruluyor ({target}). İlk seferde birkaç dakika sürebilir...")
    if run([VPY, "-m", "pip", "install", "--disable-pip-version-check", "-r", ROOT / target]) != 0:
        fail("Paket kurulumu başarısız. İnternet bağlantısını kontrol edip tekrar deneyin.")
    say("Kurulum doğrulanıyor...")
    probe = "import app.main, app.audio, numpy, scipy.signal, sounddevice, webview; print('ok')"
    if run([VPY, "-c", probe], env={**os.environ, "ERATONE_NO_AUDIO": "1"}) != 0:
        fail("Paketler kuruldu ama uygulama yüklenemedi (yukarıdaki hata mesajına bakın).")
    STAMP.write_text(stamp_value(dev) + ("\n" + stamp_value(False) if dev else ""), encoding="utf-8")
    say("Kurulum tamam.")


# ---------------- paketleme ----------------
def _source_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            p = Path(dirpath) / name
            if name in SKIP_FILES or p.suffix in SKIP_SUFFIXES:
                continue
            yield p


EXE_README = """ERATONE — NASA uydu verisini dinle

ÇALIŞTIRMA
  1. Bu zip'i bir klasöre çıkarın (masaüstü olabilir).
  2. Eratone\\Eratone.exe dosyasına çift tıklayın.
  Python ya da başka bir kurulum gerekmez. İnternet gerekir (haritalar NASA GIBS'ten canlı gelir).

NOTLAR
  - Eratone klasörünü BÜTÜN olarak taşıyın; Eratone.exe tek başına çalışmaz (_internal klasörü gerekli).
  - Windows "bilinmeyen yayımcı" uyarısı verirse: "Ek bilgi" → "Yine de çalıştır".
  - Pencere açılmazsa Microsoft Edge WebView2 Runtime kurun (Windows 11'de hazır gelir):
    https://developer.microsoft.com/microsoft-edge/webview2/
  - Önbellek ve kayıtlar: %LOCALAPPDATA%\\Eratone  (log: logs\\eratone.log)
"""


def package() -> None:
    out = ROOT / "paylasim"
    out.mkdir(exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M")

    src_zip = out / f"Eratone_kaynak_{stamp}.zip"
    say(f"Kaynak paketi hazırlanıyor: {src_zip.name}")
    n = 0
    with zipfile.ZipFile(src_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in _source_files():
            z.write(p, Path("Eratone") / p.relative_to(ROOT))
            n += 1
    say(f"  {n} dosya, {src_zip.stat().st_size / 1024 / 1024:.1f} MB  → açıp 'python kurulum.py'")

    exe_dir = ROOT / "dist" / "Eratone"
    if not (exe_dir / "Eratone.exe").exists():
        say("Uyarı: dist\\Eratone\\Eratone.exe yok, uygulama paketi atlandı. Önce: python kurulum.py --exe")
        return
    if not (exe_dir / "_internal" / "certifi" / "cacert.pem").exists():
        fail("dist\\Eratone eksik görünüyor (cacert.pem yok: yarım kalmış derleme). Önce: python kurulum.py --exe")
    app_zip = out / f"Eratone_uygulama_{stamp}.zip"
    say(f"Uygulama paketi hazırlanıyor: {app_zip.name} (biraz sürer)")
    with zipfile.ZipFile(app_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr("BENIOKU.txt", EXE_README)
        for p in exe_dir.rglob("*"):
            if p.is_file():
                z.write(p, Path("Eratone") / p.relative_to(exe_dir))
    say(f"  {app_zip.stat().st_size / 1024 / 1024:.1f} MB  → açıp Eratone\\Eratone.exe")
    say(f"Hazır: {out}")


# ---------------- ana akış ----------------
def main(argv: list[str]) -> int:
    flags = {"--kur", "--tarayici", "--test", "--exe", "--paketle", "-h", "--help"}
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    passthrough = [a for a in argv if a not in flags]   # örn. --no-intro, --debug → eratone_app.py

    if "--paketle" in argv:
        package()
        return 0
    if "--exe" in argv:
        if not WINDOWS:
            fail("Eratone.exe yalnızca Windows'ta derlenebilir.")
        install(dev=True)
        return run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ROOT / "build_eratone.ps1"])
    if "--test" in argv:
        install(dev=True)
        return run([VPY, "-m", "pytest", "-q", "tests", "world-sound/tests"], env={**os.environ, "ERATONE_NO_AUDIO": "1"})

    install(dev=False)
    if "--kur" in argv:
        say("Başlatmak için: python kurulum.py")
        return 0
    if "--tarayici" in argv:
        say("Tarayıcıda açılıyor: http://127.0.0.1:3000  (kapatmak için bu pencerede Ctrl+C)")
        return run([VPY, "start.py", *passthrough])
    check_webview2()
    say("Eratone açılıyor... (pencere kapanınca bu komut da biter)")
    return run([VPY, "eratone_app.py", *passthrough])


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(130)
