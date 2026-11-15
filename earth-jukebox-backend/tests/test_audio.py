"""Ses köprüsü (app/audio.py ↔ world-sound) testleri. İnternet ve ses kartı GEREKMEZ.

NASA isteği yerine sahte bir katman görüntüsü verilir; ERATONE_NO_AUDIO=1 ile ses kartı açılmaz,
ses render_offline() ile bellekte üretilir.
"""
import asyncio
import io
import os
from datetime import date

import numpy as np
import pytest
from PIL import Image

os.environ["ERATONE_NO_AUDIO"] = "1"

pytest.importorskip("scipy")
from app import audio, maps  # noqa: E402


def _png(rgb, w=256, h=128, alpha=255):
    a = np.zeros((h, w, 4), np.uint8)
    a[..., :3] = rgb
    a[..., 3] = alpha
    buf = io.BytesIO()
    Image.fromarray(a, "RGBA").save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture()
def bridge(monkeypatch):
    b = audio.AudioBridge()
    calls = []

    async def fake_snap(theme, day):
        return day, None

    async def fake_fetch(theme, bbox, w, h, day):
        calls.append((theme["layer"], tuple(bbox), w, h, day))
        img = np.zeros((h, w, 4), np.uint8)
        img[..., 3] = 255
        img[:, : w // 2, :3] = (255, 0, 0)      # batı yarısı kırmızı (tiz)
        img[:, w // 2:, :3] = (0, 0, 255)       # doğu yarısı mavi (pes)
        buf = io.BytesIO()
        Image.fromarray(img, "RGBA").save(buf, "PNG")
        return buf.getvalue()

    monkeypatch.setattr(maps, "snap_date", fake_snap)
    monkeypatch.setattr(maps, "fetch_layer", fake_fetch)
    b.calls = calls
    yield b
    b.close()


def test_source_uses_app_layer_not_worldsound_nasa(bridge):
    r = asyncio.run(bridge.load_source("sicaklik", date(2026, 7, 1), (-180, -90, 180, 90)))
    assert r["ok"] and r["layer"] == "MODIS_Terra_Land_Surface_Temp_Day"
    assert bridge.calls and bridge.calls[0][2] == audio.SOURCE_WIDTH          # uygulamanın fetch_layer'ı
    assert bridge._son.map.meta["source"] == "eratone"                       # worldsound NasaGibsSource değil
    assert not bridge.audio_out                                               # ERATONE_NO_AUDIO: kart açılmadı


def test_instruments_eq_and_mapping(bridge):
    son = bridge.sonifier()
    assert not any(i.enabled for i in son.instruments), "başlangıçta hepsi kapalı (arayüz durumu gönderir)"
    assert bridge.set_instrument("acoustic_guitar", True, 0.6)["key"] == "aguitar"
    assert son.instruments["aguitar"].enabled and son.instruments["aguitar"].volume == pytest.approx(0.6)
    assert not bridge.set_instrument("drums", True, None)["ok"]
    assert bridge.set_eq("treble", 5)["db"] == 5
    assert bridge.set_eq("treble", 40)["db"] == 12, "worldsound ±12 dB'de sınırlar"
    assert not bridge.set_eq("sub", 1)["ok"]


def test_view_changes_notes_and_plays(bridge):
    asyncio.run(bridge.load_source("sicaklik", date(2026, 7, 1), (-180, -90, 180, 90)))
    bridge.set_instrument("piano", True, 0.8)
    son = bridge.sonifier()
    hi, lo = son.mapper.available_notes[-1], son.mapper.available_notes[0]

    bridge.set_view(-170, -60, -20, 60)                                       # batı: kırmızı
    son.rescan(sync=True)
    assert set(np.unique(son.grid.notes)) == {hi}
    bridge.set_view(20, -60, 170, 60)                                         # doğu: mavi
    son.rescan(sync=True)
    assert set(np.unique(son.grid.notes)) == {lo}

    assert bridge.play(True)["playing"]
    out = son.render_offline(0.6)
    st = bridge.state()
    assert np.max(np.abs(out)) > 0.01 and st["playing"] and st["notes"], st
    assert bridge.play(False)["playing"] is False


def test_region_change_restarts_scan_and_keeps_playing(bridge):
    """HATA (2026-11-15): 3D'de bölge seçince yalnız görünüm değişiyor, tarama kaldığı yerden sürüyordu;
    döngü kapalıyken birkaç sn sonra bitip müzik kesiliyordu. restart=True → yeni bölgenin başından baştan tur."""
    asyncio.run(bridge.load_source("sicaklik", date(2026, 7, 1), (-180, -90, 180, 90)))
    bridge.set_instrument("piano", True, 0.8)
    son = bridge.sonifier()
    son.sequencer.loop = False
    son.set_scan_speed(20)                                   # 64 sütun = 3,2 sn
    bridge.play(True)
    son.render_offline(2.8)                                  # turun ~%87'si bitti
    assert son.scan_position > 0.8
    bridge.set_view(20, -60, 170, 60)                        # zoom/kaydırma gibi: kaldığı yerden sürer
    son.rescan(sync=True)
    son.render_offline(0.05)
    assert son.scan_position > 0.8
    bridge.set_view(-170, -60, -20, 60, restart=True)        # bölge değişti: baştan
    son.rescan(sync=True)
    son.render_offline(0.05)
    assert son.scan_position < 0.1, son.scan_position
    son.render_offline(1.5)                                  # eski davranışta tur biterdi; şimdi çalıyor
    assert son.is_playing and son.sequencer.sounding


def test_view_is_kept_across_source_reload(bridge):
    bridge.set_view(20, -60, 170, 60)
    asyncio.run(bridge.load_source("sicaklik", date(2026, 7, 1), (-180, -90, 180, 90)))
    son = bridge.sonifier()
    son.rescan(sync=True)
    assert set(np.unique(son.grid.notes)) == {son.mapper.available_notes[0]}, "yeni tarih/tema: görünüm korunmalı"


def test_diverging_themes(bridge):
    asyncio.run(bridge.load_source("okyanus_akinti", date(2024, 7, 1), (-180, -90, 180, 90)))
    assert bridge._son.mapper.diverging is True
    asyncio.run(bridge.load_source("sicaklik", date(2026, 7, 1), (-180, -90, 180, 90)))
    assert bridge._son.mapper.diverging is False


def test_api_endpoints(monkeypatch):
    from fastapi.testclient import TestClient

    from app import main

    b = audio.AudioBridge()
    monkeypatch.setattr(audio, "bridge", b)

    async def fake_snap(theme, day):
        return day, None

    async def fake_fetch(theme, bbox, w, h, day):
        return _png((0, 255, 0), w, h)

    monkeypatch.setattr(maps, "snap_date", fake_snap)
    monkeypatch.setattr(maps, "fetch_layer", fake_fetch)
    with TestClient(main.app) as c:
        r = c.post("/api/audio/source", json={"theme": "bitki", "date": "2026-11-13", "region": "turkiye"})
        assert r.status_code == 200 and r.json()["ok"] and r.json()["bbox"] == [25, 35, 45, 43]
        assert c.post("/api/audio/instrument", json={"key": "violin", "enabled": True, "volume": 0.5}).json()["ok"]
        assert c.post("/api/audio/eq", json={"band": "bass", "db": -3}).json()["db"] == -3
        assert c.post("/api/audio/eq", json={"band": "bass", "db": 30}).status_code == 422
        assert c.post("/api/audio/view", json={"west": 30, "south": 36, "east": 40, "north": 42}).json()["ok"]
        assert c.post("/api/audio/loop", json={"loop": True}).json()["ok"]
        st = c.get("/api/audio/state").json()
        assert st["ready"] and st["instruments"]["violin"]["enabled"] and st["eq"]["bass"] == -3
        assert st["view"] == [30, 36, 40, 42] and st["loop"] is True
        r = c.post("/api/audio/source", json={"theme": "yok_boyle", "region": "dunya"})
        assert r.status_code == 404 and not r.json()["ok"]
    b.close()
