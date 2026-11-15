"""Harita önbelleği temizliği (gibs_api.prune_map_cache) — ağ kullanmaz."""
import os
import time

from app import gibs_api


def _put(path, data=b"x" * 10, age=0.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if age:
        t = time.time() - age
        os.utime(path, (t, t))
    return path


def test_klasor_duzeni(tmp_path, monkeypatch):
    monkeypatch.setattr(gibs_api, "CACHE_DIR", str(tmp_path))
    p = gibs_api._map_cache_path("wms", "u", "png", ["MODIS_Terra_NDVI_8Day"], "2026-11-01")
    assert p.parent == tmp_path / "wms" / "MODIS_Terra_NDVI_8Day" / "2026-11-01"
    s = gibs_api._map_cache_path("wms", "u", "png", ["Coastlines_15m"], None)
    assert s.parent.name == gibs_api.STATIC_DIR


def test_yalnizca_en_yeni_tarih_kalir(tmp_path, monkeypatch):
    monkeypatch.setattr(gibs_api, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(gibs_api, "_SESSION_START", time.time() - 60)
    wms = tmp_path / "wms"
    eski1 = _put(wms / "IMERG" / "2025-01-01" / "a.png")
    eski2 = _put(wms / "IMERG" / "2026-11-13" / "b.png")
    yeni = _put(wms / "IMERG" / "2026-11-14" / "c.png")
    yeni_bolge = _put(wms / "IMERG" / "2026-11-14" / "d.png")
    baska_katman = _put(wms / "MERRA2" / "1990-05-01" / "e.png")      # tek tarihi var -> kalır
    taban_kullanildi = _put(wms / "BlueMarble" / gibs_api.STATIC_DIR / "f.png")
    taban_eski = _put(wms / "BlueMarble" / gibs_api.STATIC_DIR / "g.png", age=3600)
    eski_duzen = _put(wms / "0123abcd.png")                               # Faz 0-5 düz dosyası
    renk = _put(tmp_path / "colormaps" / "x.xml")                         # haritalar dışı: dokunulmaz
    metin = _put(tmp_path / "text" / "cap.xml", age=10 * 86400)

    res = gibs_api.prune_map_cache()

    for f in (eski1, eski2, taban_eski, eski_duzen):
        assert not f.exists(), f
    for f in (yeni, yeni_bolge, baska_katman, taban_kullanildi, renk, metin):
        assert f.exists(), f
    assert not (wms / "IMERG" / "2025-01-01").exists()      # boşalan klasör de gider
    assert res["removed"] == 4


class _Resp:
    def __init__(self, status, body=b"\x89PNG..."):
        self.status_code = status
        self.content = body
        self.headers = {"content-type": "image/png" if status == 200 else "text/xml"}
        self.text = "" if status == 200 else "<err/>"


def test_ayni_goruntu_tek_indirme(tmp_path, monkeypatch):
    """Ön-yükleme + ekrandaki kare aynı anda isterse NASA'ya tek istek gider."""
    import asyncio
    monkeypatch.setattr(gibs_api, "CACHE_DIR", str(tmp_path))
    calls = []

    async def fake_get(url, params, label):
        calls.append(url)
        await asyncio.sleep(0.05)
        return _Resp(200)
    monkeypatch.setattr(gibs_api, "_get", fake_get)

    async def run():
        a, b = await asyncio.gather(*(gibs_api.wms_getmap(["L"], (-180, -90, 180, 90), 64, 32, "2025-02-08") for _ in range(2)))
        return a, b
    a, b = asyncio.run(run())
    assert a == b and len(calls) == 1
    assert not gibs_api._inflight
    asyncio.run(run())                     # ikinci sefer diskten
    assert len(calls) == 1


def test_gibs_5xx_tekrar_denenir(monkeypatch):
    import asyncio
    seq = [_Resp(504), _Resp(200)]

    class FakeClient:
        is_closed = False
        async def get(self, url, params=None):
            return seq.pop(0)
    monkeypatch.setattr(gibs_api, "get_client", lambda: FakeClient())
    real_sleep = asyncio.sleep
    monkeypatch.setattr(asyncio, "sleep", lambda s: real_sleep(0))   # bekleme süresini atla
    resp = asyncio.run(gibs_api._get("https://x", None, "test"))
    assert resp.status_code == 200 and not seq


def test_bos_onbellek(tmp_path, monkeypatch):
    monkeypatch.setattr(gibs_api, "CACHE_DIR", str(tmp_path / "yok"))
    assert gibs_api.prune_map_cache() == {"removed": 0, "freed_mb": 0.0}
