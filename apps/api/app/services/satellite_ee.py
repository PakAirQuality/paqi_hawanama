"""Earth Engine: one day's satellite column statistics for the registered regions.

The only module that imports ``ee`` (lazily, so the public API service never loads it). The image
expressions are ported from air_copilot's ``atminvest.grid.build_ee_sat``: TROPOMI OFFL L3 daily
means with exact zeros masked where the national zero audit found zero to be a gap, and MAIAC
MCD19A2 granules under the strict QA (clear, land, normal adjacency, best AOD QA) averaged per
platform. Instead of compositing a 0.1° grid and reducing it locally, the native pixels are reduced
straight to each region (mean and valid count), the statistic air_copilot's ``region_daily`` keeps.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

HIGH_VOLUME_URL = "https://earthengine-highvolume.googleapis.com"
EE_SCOPES = ("https://www.googleapis.com/auth/earthengine", "https://www.googleapis.com/auth/cloud-platform")

# product -> (collection, band, exact zero is a gap)
TROPOMI: Dict[str, tuple] = {
    "no2": ("COPERNICUS/S5P/OFFL/L3_NO2", "tropospheric_NO2_column_number_density", True),
    "co": ("COPERNICUS/S5P/OFFL/L3_CO", "CO_column_number_density", True),
    "so2": ("COPERNICUS/S5P/OFFL/L3_SO2", "SO2_column_number_density", True),
    "o3": ("COPERNICUS/S5P/OFFL/L3_O3", "O3_column_number_density", True),
    "hcho": ("COPERNICUS/S5P/OFFL/L3_HCHO", "tropospheric_HCHO_column_number_density", True),
    "aai": ("COPERNICUS/S5P/OFFL/L3_AER_AI", "absorbing_aerosol_index", False),
}
MAIAC_COLLECTION = "MODIS/061/MCD19A2_GRANULES"
MAIAC_BANDS = {"aod550": "Optical_Depth_055", "aod470": "Optical_Depth_047"}
PLATFORMS = (("terra", "T"), ("aqua", "A"))
TILE_SCALE = 4
MAX_PIXELS = int(1e9)


def _ee():
    import ee  # noqa: WPS433  (lazy: only the ingest role has the package)

    return ee


class EEClient:
    """A thin, testable wrapper: ``init`` once, then per-day reductions that return plain dicts."""

    def __init__(self, project: str, *, ee_module=None, regions: Optional[Dict[str, Any]] = None):
        self.project = project
        self._ee = ee_module
        self._regions = regions
        self._fc = None
        self._ready = False

    # -- session ----------------------------------------------------------------

    @property
    def ee(self):
        if self._ee is None:
            self._ee = _ee()
        return self._ee

    def init(self) -> None:
        if self._ready:
            return
        import google.auth
        from google.auth.exceptions import DefaultCredentialsError

        try:
            creds, _ = google.auth.default(scopes=list(EE_SCOPES))
        except DefaultCredentialsError:
            # no application-default credentials (a developer's machine): the Earth Engine CLI's own login
            creds = None
        if creds is not None:
            self.ee.Initialize(credentials=creds, project=self.project, opt_url=HIGH_VOLUME_URL)
        else:
            self.ee.Initialize(project=self.project, opt_url=HIGH_VOLUME_URL)
        self._ready = True

    def ping(self) -> int:
        self.init()
        return int(self.ee.Number(1).getInfo())

    # -- regions ----------------------------------------------------------------

    def regions(self) -> Dict[str, Any]:
        if self._regions is None:
            from app.services.satellite_regions import geometries
            self._regions = geometries()
        return self._regions

    def feature_collection(self):
        if self._fc is None:
            from shapely.geometry import mapping
            ee = self.ee
            feats = [ee.Feature(ee.Geometry(mapping(g), "EPSG:4326", False), {"region": rid})
                     for rid, g in self.regions().items()]
            self._fc = ee.FeatureCollection(feats)
        return self._fc

    # -- availability -----------------------------------------------------------

    def _window(self, day: date):
        return str(day), str(day + timedelta(days=1))

    def images_available(self, kind: str, day: date) -> Dict[str, int]:
        """Images in each product's collection on that day (0 = the day is not published yet)."""
        self.init()
        ee = self.ee
        d0, d1 = self._window(day)
        out: Dict[str, int] = {}
        if kind == "tropomi":
            for q, (coll, _, _) in TROPOMI.items():
                out[q] = int(ee.ImageCollection(coll).filterDate(d0, d1).size().getInfo())
        else:
            col = ee.ImageCollection(MAIAC_COLLECTION).filterDate(d0, d1).filterBounds(self.feature_collection().geometry())
            out["aod"] = int(col.size().getInfo())
        return out

    # -- images -----------------------------------------------------------------

    def tropomi_image(self, day: date, products: List[str]):
        """One band per product: the day's orbits averaged per native pixel, zeros masked where zero is a gap."""
        ee = self.ee
        d0, d1 = self._window(day)
        bands = []
        proj = None
        for q in products:
            coll, band, zero_gap = TROPOMI[q]
            col = ee.ImageCollection(coll).filterDate(d0, d1).select(band)
            img = col.mean()
            if zero_gap:
                img = img.updateMask(img.neq(0))
            if proj is None:
                proj = ee.Image(ee.ImageCollection(coll).first()).select(band).projection()
            bands.append(img.rename(q))
        return ee.Image.cat(bands).setDefaultProjection(proj)

    def maiac_image(self, day: date, platform_code: str):
        """AOD 550 and 470 nm (×0.001) of one platform's granules under the strict QA, averaged per native pixel."""
        ee = self.ee
        d0, d1 = self._window(day)
        col = (ee.ImageCollection(MAIAC_COLLECTION).filterDate(d0, d1)
               .filterBounds(self.feature_collection().geometry()).filter(ee.Filter.eq("SATELLITE", platform_code)))

        def strict(g):
            qa = g.select("AOD_QA")
            ok = (qa.bitwiseAnd(0b111).eq(0b001)                         # cloud: clear
                  .And(qa.rightShift(3).bitwiseAnd(0b11).eq(0))          # surface: land
                  .And(qa.rightShift(5).bitwiseAnd(0b111).eq(0))         # adjacency: normal
                  .And(qa.rightShift(8).bitwiseAnd(0b1111).eq(0)))       # QA for AOD: best
            return g.select(list(MAIAC_BANDS.values()), list(MAIAC_BANDS.keys())).multiply(0.001).updateMask(ok)

        proj = ee.Image(col.first()).select("Optical_Depth_055").projection()
        return col.map(strict).mean().setDefaultProjection(proj)

    # -- reductions ---------------------------------------------------------------

    def _reduce(self, img, bands: List[str]) -> List[Dict[str, Any]]:
        ee = self.ee
        red = ee.Reducer.mean().combine(ee.Reducer.count(), sharedInputs=True)
        fc = img.select(bands).reduceRegions(collection=self.feature_collection(), reducer=red, tileScale=TILE_SCALE)
        feats = fc.getInfo().get("features", [])
        return [f.get("properties", {}) for f in feats]

    def n_possible(self, kind: str, day: date) -> Dict[str, int]:
        """Native pixels of the product grid inside each region (the denominator of coverage)."""
        self.init()
        ee = self.ee
        if kind == "tropomi":
            coll, band, _ = TROPOMI["no2"]
            proj = ee.Image(ee.ImageCollection(coll).first()).select(band).projection()
        else:
            # the grid is the same every day: take any granule from the month up to ``day`` (the day itself may not be published)
            d0 = str(day - timedelta(days=31))
            d1 = str(day + timedelta(days=1))
            col = ee.ImageCollection(MAIAC_COLLECTION).filterDate(d0, d1).filterBounds(self.feature_collection().geometry())
            if int(col.size().getInfo()) == 0:
                raise RuntimeError(f"no MAIAC granules between {d0} and {d1}: cannot size the region grid")
            proj = ee.Image(col.first()).select("Optical_Depth_055").projection()
        img = ee.Image.constant(1).rename("one").setDefaultProjection(proj)
        fc = img.reduceRegions(collection=self.feature_collection(), reducer=ee.Reducer.count(), tileScale=TILE_SCALE)
        return {f["properties"]["region"]: int(f["properties"].get("count") or 0) for f in fc.getInfo().get("features", [])}

    def day_regions(self, kind: str, day: date, products: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Rows {region, product, platform, value, n_valid} for one day; products without images give no rows."""
        self.init()
        rows: List[Dict[str, Any]] = []
        if kind == "tropomi":
            have = self.images_available("tropomi", day)
            wanted = [q for q in (products or list(TROPOMI)) if have.get(q, 0) > 0]
            if not wanted:
                return rows
            for props in self._reduce(self.tropomi_image(day, wanted), wanted):
                for q in wanted:
                    n = int(props.get(f"{q}_count") or 0)
                    v = props.get(f"{q}_mean")
                    rows.append({"region": props.get("region"), "product": q, "platform": None,
                                 "value": float(v) if (n > 0 and v is not None) else None, "n_valid": n})
            return rows
        have = self.images_available("maiac", day)
        if have.get("aod", 0) == 0:
            return rows
        wanted = [q for q in (products or list(MAIAC_BANDS)) if q in MAIAC_BANDS]
        for platform, code in PLATFORMS:
            for props in self._reduce(self.maiac_image(day, code), wanted):
                for q in wanted:
                    n = int(props.get(f"{q}_count") or 0)
                    v = props.get(f"{q}_mean")
                    rows.append({"region": props.get("region"), "product": q, "platform": platform,
                                 "value": float(v) if (n > 0 and v is not None) else None, "n_valid": n})
        return rows
