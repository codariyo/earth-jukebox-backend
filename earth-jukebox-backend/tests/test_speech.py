"""Seslendirme (app/speech.py) — internet ve ses kartı gerektirmez (NASA ve konuşma servisi taklit edilir)."""
import os
import sys
from datetime import date
from pathlib import Path

import pytest

os.environ["ERATONE_NO_AUDIO"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import speech  # noqa: E402


def fake_snapshot(stats, date_used="2025-07-01"):
    async def snap(theme_id, bbox, day, *a, **k):
        return {"stats": stats, "date_used": date_used}
    return snap


@pytest.fixture(autouse=True)
def clear_cache():
    speech._text_cache.clear()


def run(coro):
    import asyncio
    return asyncio.run(coro)


def test_say_number_turkish():
    assert speech.say_number(33.41, 1) == "33,4"
    assert speech.say_number(-2.5, 1) == "eksi 2,5"
    assert speech.say_number(16.0, 1) == "16"
    assert speech.say_number(0.41, 2) == "0,41"


def test_temperature_narration_has_real_values(monkeypatch):
    stats = {"mean_real": 33.41, "min_real": 28.2, "max_real": 38.7, "units": "°C", "coverage": 0.67,
             "series": [0.3] * 10 + [0.5] * 11 + [0.8] * 11}
    monkeypatch.setattr(speech.sound, "snapshot", fake_snapshot(stats))
    t = run(speech.narration("sicaklik", date(2025, 7, 1), "turkiye"))["text"]
    assert t.startswith("Sıcaklık Değişimi haritası, Türkiye, 1 Temmuz 2025.")
    # geniş aralık (28..39 °C): tam sayı okunur — kısa ve anlaşılır
    assert "ortalaması 33 derece; en düşük 28, en yüksek 39 derece" in t
    assert "bölgenin doğusunda" in t
    assert "°" not in t and "33.4" not in t          # konuşmaya uygun: simge ve nokta yok


def test_snapped_date_is_said(monkeypatch):
    monkeypatch.setattr(speech.sound, "snapshot", fake_snapshot(
        {"mean_real": 20.0, "min_real": 10.0, "max_real": 30.0, "units": "°C"}, date_used="2024-07-17"))
    t = run(speech.narration("okyanus_akinti", date(2025, 3, 1), "akdeniz"))["text"]
    assert t.startswith("Okyanus Akıntıları haritası, Akdeniz. 1 Mart 2025 için veri yok; en yakın veri tarihi 17 Temmuz 2024.")


def test_monthly_says_month_and_intro(monkeypatch):
    monkeypatch.setattr(speech.sound, "snapshot", fake_snapshot(
        {"mean_real": 26.46, "min_real": 24.7, "max_real": 28.0, "units": "°C", "coverage": 1.0}))
    t = run(speech.narration("kuresel_isinma", date(2025, 7, 1), "turkiye", intro=True))["text"]
    assert t.startswith("Seslendirme açık.") and "Küresel Sıcaklık haritası" in t
    assert "Temmuz 2025." in t and "1 Temmuz 2025" not in t
    assert "(Aylık)" not in t


def test_monthly_same_month_is_not_missing_data(monkeypatch):
    """Arayüz aylık temada ayın son gününü ister (31 Ağu), NASA verisi 1 Ağu tarihli: 'veri yok' DENMEZ."""
    monkeypatch.setattr(speech.sound, "snapshot", fake_snapshot(
        {"mean_real": 26.0, "min_real": 20.0, "max_real": 30.0, "units": "°C"}, date_used="2026-08-01"))
    t = run(speech.narration("kuresel_isinma", date(2026, 8, 31), "turkiye"))["text"]
    assert "veri yok" not in t and t.startswith("Küresel Sıcaklık haritası, Türkiye, Ağustos 2026.")


def test_rain_speaks_coverage(monkeypatch):
    monkeypatch.setattr(speech.sound, "snapshot", fake_snapshot(
        {"mean_real": 0.31, "min_real": 0.18, "max_real": 0.53, "units": "mm/hr", "coverage": 0.027}))
    t = run(speech.narration("yagis", date(2025, 7, 1), "akdeniz"))["text"]
    assert "yüzde 3 kadarında yağış var" in t and "milimetre bölü saat" in t


def test_range_narration_needs_no_data():
    t = run(speech.narration("sicaklik", date(2024, 6, 1), "dunya",
                             range_start=date(2024, 6, 1), range_end=date(2024, 8, 1), frames=12))["text"]
    assert t.startswith("Sıcaklık Değişimi haritası, Dünya. Tarih aralığı: 1 Haziran 2024 ile 1 Ağustos 2024 arası, 12 kare")


def test_instruments_phrase():
    assert speech.instruments_phrase(["piano"]) == "Çalan enstrüman: piyano."
    assert speech.instruments_phrase(["violin", "acoustic_guitar", "piano"]) == \
        "Çalan enstrümanlar: akustik gitar, piyano ve keman."          # arayüzdeki sırayla
    assert speech.instruments_phrase([]) == "Hiçbir enstrüman seçili değil."
    assert speech.instruments_phrase(["davul"]) == "Hiçbir enstrüman seçili değil."


def test_narration_ends_with_instruments_and_range(monkeypatch):
    monkeypatch.setattr(speech.sound, "snapshot", fake_snapshot(
        {"mean_real": 20.0, "min_real": 10.0, "max_real": 30.0, "units": "°C"}))
    t = run(speech.narration("sicaklik", date(2025, 7, 1), "turkiye", instruments=["piano", "flute"]))["text"]
    assert t.endswith("Çalan enstrümanlar: piyano ve yan flüt.")
    r = run(speech.narration("sicaklik", date(2024, 6, 1), "dunya", range_start=date(2024, 6, 1),
                             range_end=date(2024, 8, 1), frames=12, instruments=["electric_guitar"]))["text"]
    assert "1 Haziran 2024 ile 1 Ağustos 2024 arası, 12 kare" in r and r.endswith("Çalan enstrüman: elektro gitar.")
    # instruments verilmezse (eski çağrılar) enstrüman cümlesi eklenmez
    assert "Çalan" not in run(speech.narration("sicaklik", date(2025, 7, 1), "turkiye"))["text"]


def test_narration_endpoint_instruments_only():
    from fastapi.testclient import TestClient

    from app import main
    with TestClient(main.app) as c:
        j = c.get("/api/narration/sicaklik", params={"instruments_only": "true", "instruments": "piano,violin"}).json()
    assert j["text"] == "Çalan enstrümanlar: piyano ve keman."


def test_speed_endpoint_and_bridge():
    """Hız çubuğu: 0.25x…2x; motor yokken saklanır, kurulunca uygulanır; 1x = saniyede 5 sütun."""
    from fastapi.testclient import TestClient

    from app import audio, main
    audio.bridge.close()
    audio.bridge.speed = 1.0
    with TestClient(main.app) as c:
        assert c.post("/api/audio/speed", json={"factor": 1.5}).json() == {"ok": True, "speed": 1.5}
        assert c.post("/api/audio/speed", json={"factor": 3}).status_code == 422      # sınır dışı
        assert c.post("/api/audio/speed", json={"factor": 0.1}).status_code == 422
    assert audio.bridge._son is None, "hız ayarı ses kartını açmamalı"
    son = audio.bridge.sonifier()
    assert son.sequencer.step_seconds == pytest.approx(1 / (5 * 1.5))
    audio.bridge.set_speed(0.25)
    assert son.sequencer.step_seconds == pytest.approx(1 / 1.25)
    audio.bridge.set_speed(2.0)
    assert son.sequencer.step_seconds == pytest.approx(0.1)
    assert audio.bridge.state()["speed"] == 2.0
    audio.bridge.set_speed(1.0)
    audio.bridge.close()


def test_unknown_theme_and_voice():
    with pytest.raises(speech.SpeechError):
        run(speech.narration("yok_boyle", date(2025, 1, 1), "dunya"))
    with pytest.raises(speech.SpeechError):
        run(speech.synthesize("merhaba", "robot"))


def test_speech_endpoint_503_when_service_unreachable(monkeypatch, tmp_path):
    """Konuşma servisi yoksa 503 JSON döner; arayüz bunu görünce yerel Windows sesine düşer."""
    from fastapi.testclient import TestClient

    import edge_tts
    from app import main

    class Broken:
        def __init__(self, *a, **k):
            pass

        async def stream(self):
            raise ConnectionError("ağ yok")
            yield  # noqa

    monkeypatch.setattr(speech, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(edge_tts, "Communicate", Broken)
    with TestClient(main.app) as c:
        r = c.get("/api/speech", params={"voice": "tr_female", "text": "Merhaba"})
        assert r.status_code == 503 and r.json()["ok"] is False


def test_speech_endpoint_streams_and_caches(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    import edge_tts
    from app import main
    calls = []

    class Fake:
        def __init__(self, text, voice, rate=None):
            calls.append(voice)

        async def stream(self):
            yield {"type": "audio", "data": b"ID3abc"}
            yield {"type": "WordBoundary"}
            yield {"type": "audio", "data": b"def"}

    monkeypatch.setattr(speech, "CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(edge_tts, "Communicate", Fake)
    with TestClient(main.app) as c:
        a = c.get("/api/speech", params={"voice": "tr_male", "text": "Türkiye"})
        b = c.get("/api/speech", params={"voice": "tr_male", "text": "Türkiye"})
    assert a.status_code == 200 and a.headers["content-type"] == "audio/mpeg" and a.content == b"ID3abcdef"
    assert b.content == a.content and calls == ["tr-TR-AhmetNeural"], "ikinci istek önbellekten gelmeli"


def test_duck_endpoint_without_engine_does_not_open_sound_card():
    from fastapi.testclient import TestClient

    from app import audio, main
    audio.bridge.close()
    with TestClient(main.app) as c:
        assert c.post("/api/audio/duck", json={"on": True}).json() == {"ok": True, "duck": True}
    assert audio.bridge._son is None
