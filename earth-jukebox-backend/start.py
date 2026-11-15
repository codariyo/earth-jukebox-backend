"""Eratone — API + arayüz tek sunucuda.

    python start.py              -> http://127.0.0.1:3000 (tarayıcı kendiliğinden açılır)
    python start.py --no-browser

FAZ 1 (2026-11-15): Arayüz artık NiceGUI değil, statik Eratone HTML'i
(frontend/static/eratone.html). Sunumu app/main.py yapar: GET / -> eratone.html,
/static/* -> frontend/static. /api/*, /docs aynı adreste çalışır, CORS gerekmez.
Masaüstü penceresinde açmak için: python eratone_app.py (ya da python kurulum.py).
"""
import sys
import threading
import time
import webbrowser

import uvicorn

from app.config import HOST, PORT
from app.main import app


def _open_browser() -> None:
    time.sleep(1.5)
    webbrowser.open(f"http://{HOST}:{PORT}/")


if __name__ == "__main__":
    print(f"\n[OK] Eratone: http://{HOST}:{PORT}/   (API dokümanı: /docs)\n")
    if "--no-browser" not in sys.argv:
        threading.Thread(target=_open_browser, daemon=True).start()
    # timeout_graceful_shutdown: Ctrl+C'de süren istekler 2 sn sonra iptal edilir, lifespan kapanışı
    # (önbellek temizliği) çalışır. Bkz. eratone_app.py Backend.
    uvicorn.run(app, host=HOST, port=PORT, timeout_graceful_shutdown=2)
