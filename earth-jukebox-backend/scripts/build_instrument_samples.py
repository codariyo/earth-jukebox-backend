"""Gerçek enstrüman kayıtlarını world-sound örnekleyicisi (sampler) için hazırlar.

Kaynak: FluidR3_GM soundfont'unun MIDI.js dönüşümü (gleitz/midi-js-soundfonts), Creative Commons
Attribution 3.0. Her enstrüman bir `<ad>-mp3.js` dosyasıdır (88 nota, A0..C8, 3.13 sn, 44.1 kHz).

    python scripts/build_instrument_samples.py <mp3.js klasörü>

Çıktı: world-sound/worldsound/samples/<anahtar>/m<NNN>.ogg + manifest.json
Her enstrümanda GERÇEK ses aralığındaki notalardan 3 yarım tonda bir kayıt saklanır; aradakiler
çalınırken en çok ±1 yarım ton kaydırılır (örnekleyicilerde standart yöntem, tını bozulmaz).

İşlem (nota başına):
  - mono, DC (doğru akım) kaydırması silinir
  - baştaki sessizlik kırpılır (nota zamanında başlasın)
  - sönen enstrümanlar (piyano, gitarlar): -60 dB'ye inen kuyruk kırpılır, son 40 ms yumuşak kapanır
  - sürekli enstrümanlar (flüt, keman): uzun notalar için döngü (loop) bölgesi; döngü sonu, döngü
    başından önceki sesle eşit güçte karıştırılır (crossfade) → atlama duyulmaz
  - düzey: atak penceresinin RMS'i -18 dBFS'e eşitlenir (tepe en çok -1 dBFS)
  - akort: kaydın gerçek perdesi ölçülür (tune_cents); örnekleyici çalarken düzeltir. Kaynak keman
    kayıtlarında -21..+38 sent sapma vardı; düzeltmesiz piyano + keman birlikte akortsuz duyulurdu.
"""
import base64
import io
import json
import re
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "world-sound" / "worldsound" / "samples"

# anahtar (worldsound InstrumentRack) → kaynak dosya, gerçek ses aralığı (MIDI), sürekli mi
INSTRUMENTS = {
    "piano":   ("acoustic_grand_piano", 33, 99, False),   # haritanın 36..95 aralığını tümüyle kapsar
    "aguitar": ("acoustic_guitar_nylon", 40, 83, False),  # klasik gitar: Mi2 .. Si5
    "eguitar": ("electric_guitar_clean", 40, 86, False),  # elektro gitar (24 perde): Mi2 .. Re6
    "flute":   ("flute", 60, 96, True),                   # yan flüt: Do4 .. Do7
    "violin":  ("violin", 55, 96, True),                  # keman: Sol3 .. Do7
}
STEP = 3
TARGET_RMS_DB = -18.0
PEAK_MAX = 10 ** (-1.0 / 20)
NOTE = {"C": 0, "Db": 1, "D": 2, "Eb": 3, "E": 4, "F": 5, "Gb": 6, "G": 7, "Ab": 8, "A": 9, "Bb": 10, "B": 11}


def midi_of(key: str) -> int:
    m = re.fullmatch(r"([A-G]b?)(-?\d)", key)
    return 12 * (int(m.group(2)) + 1) + NOTE[m.group(1)]


def load_notes(path: Path) -> dict:
    txt = path.read_text(encoding="utf-8", errors="replace")
    pairs = re.findall(r'"([A-G]b?\d)"\s*:\s*"data:audio/mp3;base64,([^"]+)"', txt)
    return {midi_of(k): b64 for k, b64 in pairs}


def decode(b64: str):
    data, sr = sf.read(io.BytesIO(base64.b64decode(b64)), dtype="float64", always_2d=True)
    x = data.mean(axis=1)
    return x - x.mean(), sr


def measure_cents(x: np.ndarray, sr: int, midi: int, sustained: bool) -> float:
    """Kaydın GERÇEK perdesinin eşit tamperamandan sapması (sent). Temel harmoniğin frekansı,
    yüksek çözünürlüklü FFT tepe noktasıyla ölçülür (piyano inharmonikliğinden ve keman
    vibratosundan etkilenmez: vibrato 1 sn'lik pencerede ortalanır)."""
    f_nom = 440.0 * 2 ** ((midi - 69) / 12)
    a, b = (int(0.3 * sr), int(1.5 * sr)) if sustained else (int(0.08 * sr), int(1.0 * sr))
    seg = x[a:b] * np.hanning(len(x[a:b]))
    n = 1 << 18
    spec = np.abs(np.fft.rfft(seg, n))
    freqs = np.fft.rfftfreq(n, 1 / sr)
    m = (freqs > f_nom * 0.94) & (freqs < f_nom * 1.06)
    i = int(np.argmax(np.where(m, spec, 0)))
    la, lb, lc = (np.log(spec[j] + 1e-12) for j in (i - 1, i, i + 1))
    f = (i + 0.5 * (la - lc) / (la - 2 * lb + lc)) * sr / n
    return float(1200 * np.log2(f / f_nom))


def rising_zero(x: np.ndarray, near: int, span: int) -> int:
    lo, hi = max(1, near - span), min(len(x) - 1, near + span)
    idx = np.nonzero((x[lo - 1:hi - 1] < 0) & (x[lo:hi] >= 0))[0]
    if len(idx) == 0:
        return near
    return int(lo + idx[np.argmin(np.abs(idx + lo - near))])


def process(x: np.ndarray, sr: int, sustained: bool):
    peak = np.max(np.abs(x)) + 1e-12
    on = np.nonzero(np.abs(x) > peak * 10 ** (-50 / 20))[0]
    start = max(0, int(on[0]) - int(0.002 * sr)) if len(on) else 0
    x = x[start:]
    loop = None
    if sustained:
        end = len(x) - int(0.25 * sr)
        a = rising_zero(x, int(1.0 * sr), int(0.005 * sr))
        b = rising_zero(x, end, int(0.005 * sr))
        xf = int(0.15 * sr)
        x = x[: b + 1].copy()
        t = np.linspace(0.0, np.pi / 2, xf)
        x[b - xf:b] = x[b - xf:b] * np.cos(t) + x[a - xf:a] * np.sin(t)
        x[b] = x[a]
        loop = (a, b)
        win = x[int(0.3 * sr): int(1.3 * sr)]
    else:
        env = np.sqrt(np.convolve(x ** 2, np.ones(512) / 512, mode="same"))
        live = np.nonzero(env > np.max(env) * 10 ** (-60 / 20))[0]
        stop = int(live[-1]) if len(live) else len(x)
        x = x[: max(stop, int(0.3 * sr))].copy()
        fade = min(int(0.04 * sr), len(x))
        x[-fade:] *= np.linspace(1.0, 0.0, fade)
        win = x[: int(0.4 * sr)]
    rms = np.sqrt(np.mean(win ** 2)) + 1e-12
    gain = 10 ** (TARGET_RMS_DB / 20) / rms
    gain = min(gain, PEAK_MAX / (np.max(np.abs(x)) + 1e-12))
    return (x * gain).astype(np.float32), loop, 20 * np.log10(rms)


def main(src: Path):
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {
        "source": "FluidR3_GM (Frank Wen) · MIDI.js dönüşümü: github.com/gleitz/midi-js-soundfonts",
        "license": "Creative Commons Attribution 3.0 (https://creativecommons.org/licenses/by/3.0/us/)",
        "sample_rate": 44100,
        "instruments": {},
    }
    for key, (name, lo, hi, sustained) in INSTRUMENTS.items():
        notes = load_notes(src / f"{name}-mp3.js")
        roots = list(range(lo, hi + 1, STEP))
        if hi - roots[-1] >= 2:
            roots.append(hi)
        folder = OUT / key
        folder.mkdir(exist_ok=True)
        for old in folder.glob("*.ogg"):
            old.unlink()
        entry = {"low": lo, "high": hi, "sustained": sustained, "notes": {}}
        for want in roots:
            # Kaynakta tek tük boş kayıt var (ör. keman Si♭6): komşu notayı kullan
            for m in (want, want - 1, want + 1):
                x, sr = decode(notes[m])
                y, loop, src_db = process(x, sr, sustained)
                if src_db >= -60:
                    break
            else:
                raise SystemExit(f"{key} m{want}: kayıt ve komşuları sessiz — aralığı daralt")
            fn = f"m{m:03d}.ogg"
            sf.write(folder / fn, y, sr, format="OGG", subtype="VORBIS")
            # akort düzeltmesi: çalarken bu kadar sent ters yönde kaydırılır (tüm enstrümanlar aynı akortta)
            tune = round(measure_cents(y.astype(np.float64), sr, m, sustained), 1)
            entry["notes"][str(m)] = {"file": fn, "loop": list(loop) if loop else None,
                                      "length": len(y), "tune_cents": tune}
        manifest["instruments"][key] = entry
        size = sum(f.stat().st_size for f in folder.glob("*.ogg"))
        tunes = [n["tune_cents"] for n in entry["notes"].values()]
        print(f"{key:8} {name:24} {len(roots):2} kayıt  MIDI {lo}-{hi}  {size / 1024:.0f} KB  "
              f"akort sapması {min(tunes):+.0f}..{max(tunes):+.0f} sent (düzeltilecek)")
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "KAYNAK.txt").write_text(
        "Enstrüman kayıtları: FluidR3_GM soundfont (Frank Wen), MIDI.js dönüşümü "
        "https://github.com/gleitz/midi-js-soundfonts\n"
        "Lisans: Creative Commons Attribution 3.0 — https://creativecommons.org/licenses/by/3.0/us/\n"
        "Değişiklikler: mono, kırpma, düzey eşitleme, sürekli seslerde döngü; "
        "scripts/build_instrument_samples.py ile üretildi.\n", encoding="utf-8")
    total = sum(f.stat().st_size for f in OUT.rglob("*.ogg"))
    print(f"toplam {total / 1024 / 1024:.2f} MB → {OUT}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
