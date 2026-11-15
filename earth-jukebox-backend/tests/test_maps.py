"""Gorsel API testleri — internet GEREKMEZ (NASA cagrilari sahte verilerle degistirilir)."""
import io
import sys
import warnings
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import capabilities, gibs_api, maps  # noqa: E402
from app.capabilities import parse_time_value, parse_wmts_capabilities  # noqa: E402

CAPS = """<?xml version="1.0"?>
<Capabilities xmlns="http://www.opengis.net/wmts/1.0" xmlns:ows="http://www.opengis.net/ows/1.1"
              xmlns:xlink="http://www.w3.org/1999/xlink">
 <Contents>
  <Layer><ows:Identifier>MODIS_Terra_Land_Surface_Temp_Day</ows:Identifier>
   <ows:Metadata xlink:role="http://earthdata.nasa.gov/gibs/metadata-type/colormap/1.3"
                 xlink:href="https://gibs.earthdata.nasa.gov/colormaps/v1.3/MODIS_Land_Surface_Temp.xml"/>
   <Style><LegendURL xlink:role="http://earthdata.nasa.gov/gibs/legend-type/horizontal"
                     xlink:href="https://gibs.earthdata.nasa.gov/legends/MODIS_Land_Surface_Temp_H.svg"/></Style>
   <Format>image/png</Format>
   <Dimension><ows:Identifier>Time</ows:Identifier><Value>2000-02-24/2026-11-14/P1D</Value></Dimension>
   <TileMatrixSetLink><TileMatrixSet>1km</TileMatrixSet></TileMatrixSetLink>
   <ResourceURL template="https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/MODIS_Terra_Land_Surface_Temp_Day/default/{Time}/{TileMatrixSet}/{TileMatrix}/{TileRow}/{TileCol}.png"/>
  </Layer>
  <Layer><ows:Identifier>MERRA2_2m_Air_Temperature_Monthly</ows:Identifier>
   <ows:Metadata xlink:role="http://earthdata.nasa.gov/gibs/metadata-type/colormap/1.3"
                 xlink:href="https://gibs.earthdata.nasa.gov/colormaps/v1.3/MERRA2_2m_Air_Temperature_Monthly.xml"/>
   <Format>image/png</Format>
   <Dimension><ows:Identifier>Time</ows:Identifier>
     <Value>1980-01-01/2023-11-01/P1M</Value><Value>2024-02-01/2024-04-01/P1M</Value>
     <Value>2024-06-01/2026-08-01/P1M</Value></Dimension>
   <TileMatrixSetLink><TileMatrixSet>2km</TileMatrixSet></TileMatrixSetLink>
  </Layer>
  <Layer><ows:Identifier>OSCAR_Sea_Surface_Currents_Zonal</ows:Identifier>
   <Format>image/png</Format>
   <Dimension><ows:Identifier>Time</ows:Identifier>
     <Value>2014-10-22/2014-12-21/P5D</Value><Value>2024-07-07/2024-07-17/P5D</Value></Dimension>
  </Layer>
  <Layer><ows:Identifier>MODIS_Terra_CorrectedReflectance_TrueColor</ows:Identifier>
   <Format>image/jpeg</Format>
   <Dimension><ows:Identifier>Time</ows:Identifier><Value>2000-02-24/2026-11-14/P1D</Value></Dimension>
   <TileMatrixSetLink><TileMatrixSet>250m</TileMatrixSet></TileMatrixSetLink>
  </Layer>
 </Contents>
</Capabilities>"""

COLORMAP = """<ColorMaps><ColorMap title="Temp" units="K"><Entries>
<ColorMapEntry rgb="0,0,255" transparent="false" value="[250,260)"/>
<ColorMapEntry rgb="255,0,0" transparent="false" value="[300,310)"/>
</Entries></ColorMap></ColorMaps>"""


# ---------- tarih araliklari ----------
def test_time_value_parsing_and_snap():
    layers = parse_wmts_capabilities(CAPS)
    lst = layers["MODIS_Terra_Land_Surface_Temp_Day"]
    assert lst.colormap_url.endswith("MODIS_Land_Surface_Temp.xml")
    assert lst.legend_url.endswith("_H.png")  # svg -> png
    assert lst.tile_ext == "png" and lst.tile_matrix_sets == ["1km"]
    assert lst.snap(date(2026, 11, 20)) == date(2026, 11, 14)  # gelecek -> son veri
    assert lst.snap(date(1990, 1, 1)) == date(2000, 2, 24)  # once -> ilk veri

    merra = layers["MERRA2_2m_Air_Temperature_Monthly"]
    assert merra.snap(date(2024, 1, 17)) == date(2023, 11, 1)  # 2023-12 ve 2024-01 eksik
    assert merra.snap(date(2025, 7, 20)) == date(2025, 7, 1)
    assert "aylık" in merra.describe_coverage()

    oscar = layers["OSCAR_Sea_Surface_Currents_Zonal"]
    assert oscar.snap(date(2026, 11, 10)) == date(2024, 7, 17)  # veri 2024'te bitiyor
    assert oscar.snap(date(2014, 10, 30)) == date(2014, 10, 27)  # 5 gunluk adim


def test_period_variants():
    r = parse_time_value("2020-01-01/2020-12-01/P3M,2021-05-05")
    assert [(x.unit, x.step) for x in r] == [("M", 3), ("D", 1)]
    assert r[0].latest_on_or_before(date(2020, 8, 15)) == date(2020, 7, 1)


def test_frame_dates_same_season_for_long_ranges():
    d = maps.frame_dates(date(1985, 7, 1), date(2025, 7, 1), 5)
    assert [x.year for x in d] == [1985, 1995, 2005, 2015, 2025]
    assert all((x.month, x.day) == (7, 1) for x in d)
    short = maps.frame_dates(date(2025, 1, 1), date(2025, 1, 31), 4)
    assert short[0] == date(2025, 1, 1) and short[-1] == date(2025, 1, 31) and len(short) == 4


def test_frame_dates_rejects_reversed_range():
    with pytest.raises(maps.MapRequestError):
        maps.frame_dates(date(2025, 1, 1), date(2024, 1, 1), 4)


# ---------- uc noktalar (sahte NASA) ----------
def _png(w, h, rgb=(255, 0, 0), alpha=255):
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    arr[..., :3] = rgb
    arr[..., 3] = alpha
    buf = io.BytesIO()
    Image.fromarray(arr, "RGBA").save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def client(monkeypatch):
    calls = []

    async def fake_getmap(layers, bbox, width, height, time=None, epsg=4326, fmt="image/png", transparent=True):
        calls.append((tuple(layers), time, epsg))
        if layers == ["Coastlines_15m"]:
            return _png(width, height, (255, 255, 255), 0)
        # erken tarih mavi (soguk), gec tarih kirmizi (sicak)
        rgb = (0, 0, 255) if time and time < "2000" else (255, 0, 0)
        return _png(width, height, rgb)

    async def fake_caps(epsg=4326):
        return CAPS

    async def fake_text(url, label, ttl_hours=None):
        return COLORMAP

    async def fake_legend(url):
        return _png(300, 40, (200, 200, 200))

    async def fake_tile(layer, time, tms, z, row, col, ext, epsg=4326):
        return _png(512, 512)

    async def fake_eonet(start, end, categories=None):
        return {"events": [{"title": "Yangin", "categories": [{"id": "wildfires", "title": "Wildfires"}],
                            "geometry": [{"type": "Point", "coordinates": [30.0, 39.0]}]}]}

    monkeypatch.setattr(gibs_api, "wms_getmap", fake_getmap)
    monkeypatch.setattr(gibs_api, "wmts_capabilities_xml", fake_caps)
    monkeypatch.setattr(gibs_api, "fetch_text", fake_text)
    monkeypatch.setattr(gibs_api, "legend_png", fake_legend)
    monkeypatch.setattr(gibs_api, "wmts_tile", fake_tile)
    monkeypatch.setattr(gibs_api, "eonet_events", fake_eonet)
    capabilities.reset_cache()

    warnings.filterwarnings("ignore")
    from fastapi.testclient import TestClient

    from app.main import app
    c = TestClient(app, raise_server_exceptions=False)
    c.calls = calls
    yield c
    capabilities.reset_cache()


def _img(resp):
    return Image.open(io.BytesIO(resp.content))


@pytest.mark.parametrize("url,fmt", [
    ("/api/map/sicaklik?date=2026-11-10", "PNG"),
    ("/api/map/sicaklik/compare?start=1990-07-01&end=2025-07-01", "PNG"),
    ("/api/map/kuresel_isinma/range?start=1985-07-01&end=2025-07-01&frames=4&width=320", "GIF"),
    ("/api/overview?width=200", "PNG"),
    ("/api/projection/dunya_renkleri?epsg=3031&size=256", "PNG"),
    ("/api/tile/sicaklik/0/0/0", "PNG"),
    ("/api/legend/sicaklik", "PNG"),
    ("/api/events?start=2026-10-01&end=2026-11-01&width=512", "PNG"),
    ("/api/catalog", "PNG"),
])
def test_every_endpoint_returns_an_image(client, url, fmt):
    r = client.get(url)
    assert r.status_code == 200, r.content[:200]
    assert r.headers["content-type"].startswith("image/")
    assert _img(r).format == fmt


def test_range_gif_has_frames_with_snapped_dates(client):
    r = client.get("/api/map/kuresel_isinma/range?start=1985-07-01&end=2025-07-01&frames=3&width=320")
    assert _img(r).n_frames == 3
    times = [t for layers, t, _ in client.calls if layers == ("MERRA2_2m_Air_Temperature_Monthly",)]
    assert times == ["1985-07-01", "2005-07-01", "2025-07-01"]


def test_single_map_uses_capabilities_date(client):
    client.get("/api/map/okyanus_akinti?date=2026-11-10")
    times = [t for layers, t, _ in client.calls if layers == ("OSCAR_Sea_Surface_Currents_Zonal",)]
    assert times == ["2024-07-17"]  # veri olmayan tarih -> en yakin gecerli tarih


@pytest.mark.parametrize("url,status", [
    ("/api/map/yok", 404),
    ("/api/map/sicaklik?date=2026-99-99", 400),
    ("/api/map/sicaklik?region=mars", 400),
    ("/api/map/sicaklik/range?start=2025-01-01", 422),  # end eksik
    ("/api/map/sicaklik/compare?start=2025-01-01&end=2024-01-01", 400),
])
def test_errors_are_images_too(client, url, status):
    r = client.get(url)
    assert r.status_code == status
    assert r.headers["content-type"] == "image/png"
    assert _img(r).format == "PNG"
