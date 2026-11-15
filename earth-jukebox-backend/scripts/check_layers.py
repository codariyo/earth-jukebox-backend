"""GIBS katman adlarini dogrular. Calistir:  python scripts/check_layers.py

GIBS API ANAHTARI ISTEMEZ. Bu script GIBS'in katman listesini indirir,
config.py'deki her katmanin gercekten var olup olmadigini kontrol eder,
yoksa benzer adlari onerir. Ayrica her katmanin gecerli tarih araligini yazar.
"""
import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.capabilities import parse_wmts_capabilities  # noqa: E402
from app.colormap import parse_colormap  # noqa: E402
from app.config import DENEYSEL_KATMANLAR, GIBS_WMS_URL, GIBS_WMTS_TEMPLATE, THEMES  # noqa: E402

# Renk haritasi adi katman adiyla ayni OLMAYABILIR (NDVI -> MODIS_NDVI.xml).
# Dogru link WMTS capabilities'teki Metadata(role=colormap/1.3) alanindadir.
_WMTS_LAYERS = None


def colormap_url(layer: str) -> str | None:
    global _WMTS_LAYERS
    if _WMTS_LAYERS is None:
        r = httpx.get(GIBS_WMTS_TEMPLATE.format(epsg=4326),
                      params={"SERVICE": "WMTS", "REQUEST": "GetCapabilities"}, timeout=120)
        r.raise_for_status()
        _WMTS_LAYERS = parse_wmts_capabilities(r.text)
    info = _WMTS_LAYERS.get(layer)
    return info.colormap_url if info else None

KEYWORDS = {
    "dunya_renkleri": ["CorrectedReflectance", "TrueColor", "SurfaceReflectance"],
    "sicaklik": ["Land_Surface_Temp", "Surface_Air_Temperature", "Skin_Temperature"],
    "okyanus": ["Sea_Surface_Temp", "SST", "Currents", "OSCAR"],
    "bitki": ["NDVI", "EVI", "Vegetation", "Leaf_Area"],
    "yagis": ["Precipitation", "IMERG", "Rain"],
    "kuresel_isinma": ["2m_Air_Temperature", "Air_Temperature", "Anomal"],
    "isinma_anomali": ["Anomal"],
}


def fetch_names() -> set[str]:
    print("GIBS katman listesi indiriliyor (anahtar gerekmez, birkac saniye surer)...")
    r = httpx.get(
        GIBS_WMS_URL,
        params={"SERVICE": "WMS", "REQUEST": "GetCapabilities", "VERSION": "1.1.1"},
        timeout=120,
    )
    r.raise_for_status()
    Path("docs").mkdir(exist_ok=True)
    Path("docs/gibs_capabilities.xml").write_text(r.text, encoding="utf-8")
    return set(re.findall(r"<Name>([^<]+)</Name>", r.text))


def time_extent(xml: str, layer: str) -> str:
    """Katmanin gecerli tarih araligini capabilities XML'inden okur."""
    block = re.search(
        rf"<Name>{re.escape(layer)}</Name>.*?(?=<Name>|</Layer>\s*</Layer>)", xml, re.S
    )
    if not block:
        return "-"
    ext = re.search(r'<Extent name="time"[^>]*>([^<]+)</Extent>', block.group(0))
    return ext.group(1).strip() if ext else "tarih yok (sabit katman)"


def colormap_summary(layer: str) -> str:
    """Renk haritasini indirip birimini, araligini ve hassasiyetini ozetler."""
    try:
        url = colormap_url(layer)
        if not url:
            return "YOK (capabilities'te renk haritasi linki yok) -> renk tonu tahmini kullanilacak"
        r = httpx.get(url, timeout=60)
    except httpx.HTTPError as exc:
        return f"indirilemedi ({exc})"
    if r.status_code != 200:
        return f"YOK (HTTP {r.status_code}) -> renk tonu tahmini kullanilacak"
    cmap = parse_colormap(r.text, layer)
    if cmap is None:
        return "sayisal deger yok (siniflandirma haritasi) -> renk tonu tahmini kullanilacak"
    prec = f", hassasiyet {cmap.bin_width:g}" if cmap.bin_width else ""
    return (f"OK - {len(cmap.mids)} renk, {cmap.vmin:g} ile {cmap.vmax:g} {cmap.units}"
            f"{prec} ({cmap.title})")


def main():
    names = fetch_names()
    xml = Path("docs/gibs_capabilities.xml").read_text(encoding="utf-8")
    print(f"{len(names)} katman bulundu.\n")

    eksik = False
    for key, theme in THEMES.items():
        ok = theme["layer"] in names
        eksik = eksik or not ok
        print(f"[{'OK ' if ok else 'YOK'}] {key:18} -> {theme['layer']}")
        if ok:
            print(f"      Tarih araligi: {time_extent(xml, theme['layer'])}")
            if theme["feature"] == "colormap":
                print(f"      Renk haritasi: {colormap_summary(theme['layer'])}")
        else:
            similar = sorted(
                n for n in names if any(k.lower() in n.lower() for k in KEYWORDS.get(key, []))
            )
            print("      Benzer katmanlar:", ", ".join(similar[:12]) or "-")

    print("\n--- Deneysel katmanlar ---")
    for layer in DENEYSEL_KATMANLAR:
        var = layer in names
        print(f"[{'VAR' if var else 'YOK'}] {layer}")
        if var:
            print(f"      Tarih araligi: {time_extent(xml, layer)}")

    print("\nTam liste: docs/gibs_capabilities.xml")
    if eksik:
        print("Eksik katman var -> benzer adlardan birini app/config.py icine yaz.")


if __name__ == "__main__":
    main()
