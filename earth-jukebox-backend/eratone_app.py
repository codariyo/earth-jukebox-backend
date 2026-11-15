"""Eratone — masaüstü uygulaması (Eratone.exe bunu çalıştırır).

Tarayıcı açılmaz: arayüz kendi penceresinde (pywebview → Windows Edge WebView2) açılır.
Akış:
  1. Tek örnek kilidi (ikinci açılışta uyarı verip çıkar).
  2. FastAPI/uvicorn bu süreç içinde, arka plan iş parçacığında 127.0.0.1:<port> üzerinde başlar.
  3. Pencere önce koyu bir "başlatılıyor" ekranı gösterir; sunucu hazır olunca http://127.0.0.1:<port>/
     yüklenir. Arayüz bütün veriyi bu yerel host üzerinden /api/* ile çeker (tarayıcıdaki gibi HTTP).
  4. Pencere kapanınca sunucu durdurulur, süreç biter (arkada sunucu kalmaz).

Çalıştır (geliştirme):  python eratone_app.py            [--no-intro] [--debug]
  --no-intro  açılış animasyonunu atlar (eratone.html ?intro=0). Animasyon varsayılan; Three.js + dokular yerel
              (frontend/static/vendor/intro/), internet gerekmez.
  --debug  WebView2 geliştirici araçlarını açar (sağ tık → İncele)
Derle:  powershell -ExecutionPolicy Bypass -File build_eratone.ps1   → dist\\Eratone\\Eratone.exe
Bkz. CONTEXT.md bölüm 6b.
"""
import ctypes
import os
import shutil
import socket
import sys
import threading
import time
from pathlib import Path

APP_NAME = "Eratone"
FROZEN = getattr(sys, "frozen", False)
DATA_DIR = Path(os.getenv("LOCALAPPDATA") or Path.home()) / APP_NAME
# Açılış animasyonu artık VARSAYILAN (eratone.html kendisi açar, kendiliğinden oynar, bitince uygulamaya geçer).
# Kapatmak: --no-intro ya da ERATONE_INTRO=0  → adrese ?intro=0 eklenir.
NO_INTRO = "--no-intro" in sys.argv or os.getenv("ERATONE_INTRO") == "0"
DEBUG = "--debug" in sys.argv
HOST = "127.0.0.1"
# SABİT port: WebView2 localStorage'ı "origin"e (host:port) bağlar. Port her açılışta değişirse
# yazı boyutu gibi kayıtlı tercihler kaybolur. 3000 bilinçli olarak kullanılmıyor (geliştirme sunucusu).
PREFERRED_PORTS = range(38100, 38120)

BG = "#03050a"
LOADING_HTML = f"""<!doctype html><html><head><meta charset="utf-8"></head>
<body style="margin:0;height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;
background:radial-gradient(circle at 50% 45%,#091326 0%,{BG} 70%);color:#cbd5e1;font-family:'Segoe UI',sans-serif;
letter-spacing:.3em;user-select:none">
<div style="font-size:2.2rem;font-weight:500;color:#f8fafc">ERATONE</div>
<div style="margin-top:14px;font-size:.85rem;letter-spacing:.2em;opacity:.65">başlatılıyor…</div>
</body></html>"""


# ---------------- G/Ç: penceresiz exe'de stdout/stderr yoktur ----------------
def _setup_io() -> None:
    """--windowed exe'de sys.stdout/stderr None olur; uvicorn loglaması ve app/logger.py print'leri
    çöker ya da kaybolur. Bunları %LOCALAPPDATA%\\Eratone\\logs\\eratone.log dosyasına yönlendir."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    log_dir = DATA_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "eratone.log"
    if log_file.exists() and log_file.stat().st_size > 5 * 1024 * 1024:  # 5 MB'ı geçerse sıfırla
        log_file.replace(log_dir / "eratone.old.log")
    stream = open(log_file, "a", encoding="utf-8", buffering=1)
    stream.write(f"\n===== {APP_NAME} açıldı {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def _message_box(text: str, title: str = APP_NAME, error: bool = True) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10 if error else 0x40)
    except Exception:
        print(f"[{title}] {text}", file=sys.stderr)


# ---------------- tek örnek ----------------
_mutex = None


def _single_instance() -> bool:
    """Windows adlandırılmış mutex: ikinci kopya açılırsa False döner."""
    global _mutex
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        _mutex = k32.CreateMutexW(None, False, "Local\\EratoneDesktopApp")
        return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS
    except Exception:
        return True  # Windows dışı / beklenmedik durum: engelleme


# ---------------- sunucu ----------------
def _free_port() -> int:
    for port in PREFERRED_PORTS:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((HOST, port))
                return port
            except OSError:
                continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:  # hepsi doluysa rastgele
        s.bind((HOST, 0))
        return s.getsockname()[1]


class Backend:
    def __init__(self) -> None:
        import uvicorn

        from app.main import app

        self.port = _free_port()
        params = (["intro=0"] if NO_INTRO else []) + ([os.environ["ERATONE_QUERY"]] if os.getenv("ERATONE_QUERY") else [])
        # ERATONE_QUERY: yalnızca geliştirme/test (örn. "ej=1&pov=39,35,0.45" → eratone-data.js test kancası)
        self.url = f"http://{HOST}:{self.port}/" + ("?" + "&".join(params) if params else "")
        # access_log=False: ses durumu (/api/audio/state) sık sorgulanıyor, her istek satırı log dosyasını şişirirdi
        # timeout_graceful_shutdown=2: pencere kapanınca süren NASA istekleri 2 sn sonra iptal edilir. Bu olmadan uvicorn
        # "Waiting for background tasks" diye sonsuz bekliyor, stop() zaman aşımına uğruyor ve lifespan kapanışı
        # (ses kartını bırakma + önbellek temizliği) HİÇ çalışmıyordu (exe log'unda doğrulandı, 2026-11-15).
        self.server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=self.port, log_level="info", access_log=False,
                                                    timeout_graceful_shutdown=2))
        self.thread = threading.Thread(target=self.server.run, name="uvicorn", daemon=True)

    def start(self, timeout: float = 30.0) -> bool:
        self.thread.start()
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.server.started:
                return True
            if not self.thread.is_alive():
                return False
            time.sleep(0.05)
        return False

    def stop(self) -> None:
        self.server.should_exit = True
        if self.thread.is_alive():
            self.thread.join(timeout=15)   # 2 sn iptal + ses kapanışı + önbellek temizliği (ilk sefer ~700 dosya)


# ---------------- uygulama ----------------
def main() -> int:
    _setup_io()
    if FROZEN:
        # exe önbelleği kullanıcı klasöründe (app/config.py CACHE_DIR'i ortamdan okur).
        # Geliştirmede (python eratone_app.py) projedeki cache/ klasörü kullanılmaya devam eder.
        os.environ.setdefault("CACHE_DIR", str(DATA_DIR / "cache"))

    if not _single_instance():
        _message_box("Eratone zaten açık.", error=False)
        return 0

    # Seslendirme tıklama beklemeden konuşabilsin (açılış ekranı + uygulamaya geçiş): WebView2 varsayılanında
    # kullanıcı etkileşimi olmadan audio.play() ENGELLENİR (NotAllowedError; gizli pencerede ölçüldü). Bu ortam
    # değişkeni pywebview'in kendi argümanının YERİNE geçer → onun argümanı (ElasticOverscroll) da eklenir.
    extra = "--disable-features=ElasticOverscroll --autoplay-policy=no-user-gesture-required"
    prev = os.environ.get("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "")
    if "--autoplay-policy" not in prev:
        os.environ["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = (prev + " " + extra).strip()

    # WebView2'nin HTTP disk önbelleği: eskiden harita görüntüleri buraya da yazılıyordu (~287 MB).
    # Artık /api yanıtları "no-store" (app/main.py); kalan eski kopyalar pencere açılmadan silinir.
    # Burada silinir, kapanışta değil: o an WebView2 süreci dosyaları hâlâ kilitli tutabiliyor.
    # localStorage (yazı boyutu vb. tercihler) "Local Storage" klasöründedir, ona dokunulmaz.
    shutil.rmtree(DATA_DIR / "webview" / "EBWebView" / "Default" / "Cache", ignore_errors=True)

    try:
        import webview
    except Exception as exc:
        _message_box(f"Pencere bileşeni yüklenemedi:\n{exc}")
        return 1

    backend = Backend()
    window = webview.create_window(
        APP_NAME, html=LOADING_HTML, width=1440, height=900, min_size=(1024, 700),
        background_color=BG, maximized=True, text_select=True,
    )

    def boot() -> None:  # pywebview kendi iş parçacığında çağırır
        if backend.start():
            print(f"[OK] {APP_NAME} sunucusu: {backend.url}", flush=True)
            window.load_url(backend.url)
        else:
            window.load_html(
                f"<body style='background:{BG};color:#fb7185;font-family:Segoe UI;padding:40px'>"
                f"<h2>Sunucu başlatılamadı</h2><p>Port {backend.port}. Ayrıntı: "
                f"{DATA_DIR / 'logs' / 'eratone.log'}</p></body>"
            )

    try:
        webview.start(
            boot, gui="edgechromium", debug=DEBUG,
            private_mode=False, storage_path=str(DATA_DIR / "webview"),
        )
    except Exception as exc:
        _message_box(
            "Eratone penceresi açılamadı. Microsoft Edge WebView2 Runtime kurulu olmalı:\n"
            "https://developer.microsoft.com/microsoft-edge/webview2/\n\n"
            f"Ayrıntı: {type(exc).__name__}: {exc}"
        )
        return 1
    finally:
        backend.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
