"""Sentinel-2 over a block, via Copernicus Data Space (Sentinel Hub APIs). Free account.

- Statistical API: per-pass NDVI and NDMI mean / std over the block's cloud-free pixels.
- Process API: an NDVI colour map of the block for the latest clear pass (PNG).

Credentials: SH_CLIENT_ID / SH_CLIENT_SECRET (an OAuth client created in the
Copernicus Data Space dashboard). Only the sync job uses these; the web app reads
what the job stored.
"""

import math
import os
import time
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from engine.fieldhealth import Observation
from engine.models import Boundary

TOKEN_URL = os.environ.get(
    "SH_TOKEN_URL",
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token",
)
STATS_URL = os.environ.get("SH_STATS_URL", "https://sh.dataspace.copernicus.eu/statistics/v1")
PROCESS_URL = os.environ.get("SH_PROCESS_URL", "https://sh.dataspace.copernicus.eu/process/v1")
CRS84 = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"
RES_DEG = 0.0001  # about 10 m, Sentinel-2's native resolution for B04/B08

# SCL classes treated as unusable: 3 cloud shadow, 8/9 cloud, 10 thin cirrus, 11 snow.
STATS_EVALSCRIPT = """//VERSION=3
function setup() {
  return {
    input: [{bands: ["B04", "B08", "B8A", "B11", "SCL", "dataMask"]}],
    output: [
      {id: "ndvi", bands: 1, sampleType: "FLOAT32"},
      {id: "ndmi", bands: 1, sampleType: "FLOAT32"},
      {id: "dataMask", bands: 1}
    ]
  };
}
function evaluatePixel(s) {
  const bad = [3, 8, 9, 10, 11].includes(s.SCL);
  const ndvi = (s.B08 - s.B04) / (s.B08 + s.B04);
  const ndmi = (s.B8A - s.B11) / (s.B8A + s.B11);
  const ok = s.dataMask === 1 && !bad && isFinite(ndvi) && isFinite(ndmi);
  return {ndvi: [ndvi], ndmi: [ndmi], dataMask: [ok ? 1 : 0]};
}
"""

MAP_EVALSCRIPT = """//VERSION=3
function setup() {
  return {input: [{bands: ["B04", "B08", "SCL", "dataMask"]}], output: {bands: 4}};
}
const ramp = [[0.0, 0xa6611a], [0.2, 0xdfc27d], [0.4, 0xe6f598], [0.6, 0x66bd63], [0.8, 0x1a9850]];
const viz = new ColorRampVisualizer(ramp);
function evaluatePixel(s) {
  const bad = [3, 8, 9, 10, 11].includes(s.SCL);
  const ndvi = (s.B08 - s.B04) / (s.B08 + s.B04);
  if (!s.dataMask || bad || !isFinite(ndvi)) return [0, 0, 0, 0];
  const c = viz.process(ndvi);
  return [c[0], c[1], c[2], 1];
}
"""


class SentinelHub:
    def __init__(self, client_id: str, client_secret: str, http: httpx.Client) -> None:
        self._id = client_id
        self._secret = client_secret
        self._http = http
        self._token: str | None = None
        self._expires = 0.0

    @classmethod
    def from_env(cls, http: httpx.Client) -> "SentinelHub | None":
        cid = os.environ.get("SH_CLIENT_ID", "").strip()
        secret = os.environ.get("SH_CLIENT_SECRET", "").strip()
        return cls(cid, secret, http) if cid and secret else None

    def _auth(self) -> dict[str, str]:
        if self._token is None or time.time() > self._expires - 60:
            res = self._http.post(
                TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self._id,
                    "client_secret": self._secret,
                },
            )
            res.raise_for_status()
            body = res.json()
            self._token = body["access_token"]
            self._expires = time.time() + float(body.get("expires_in", 300))
        return {"Authorization": f"Bearer {self._token}"}

    def observations(self, boundary: Boundary, start: date, end: date) -> list[Observation]:
        body = stats_request(boundary, start, end)
        res = self._http.post(STATS_URL, json=body, headers=self._auth(), timeout=120.0)
        res.raise_for_status()
        return parse_stats(res.json())

    def ndvi_png(self, boundary: Boundary, day: date) -> bytes:
        body = map_request(boundary, day)
        res = self._http.post(
            PROCESS_URL, json=body, headers={**self._auth(), "Accept": "image/png"},
            timeout=120.0,
        )
        res.raise_for_status()
        return res.content


def _bounds(boundary: Boundary) -> dict[str, Any]:
    return {"geometry": boundary.model_dump(), "properties": {"crs": CRS84}}


def stats_request(boundary: Boundary, start: date, end: date) -> dict[str, Any]:
    return {
        "input": {
            "bounds": _bounds(boundary),
            "data": [{"type": "sentinel-2-l2a", "dataFilter": {"mosaickingOrder": "leastCC"}}],
        },
        "aggregation": {
            "timeRange": {
                "from": f"{start.isoformat()}T00:00:00Z",
                "to": f"{(end + timedelta(days=1)).isoformat()}T00:00:00Z",
            },
            "aggregationInterval": {"of": "P1D"},
            "evalscript": STATS_EVALSCRIPT,
            "resx": RES_DEG,
            "resy": RES_DEG,
        },
        "calculations": {"default": {}},
    }


def map_request(boundary: Boundary, day: date) -> dict[str, Any]:
    width, height = map_size(boundary)
    return {
        "input": {
            "bounds": _bounds(boundary),
            "data": [{
                "type": "sentinel-2-l2a",
                "dataFilter": {
                    "timeRange": {
                        "from": f"{day.isoformat()}T00:00:00Z",
                        "to": f"{day.isoformat()}T23:59:59Z",
                    },
                    "mosaickingOrder": "leastCC",
                },
            }],
        },
        "output": {
            "width": width,
            "height": height,
            "responses": [{"identifier": "default", "format": {"type": "image/png"}}],
        },
        "evalscript": MAP_EVALSCRIPT,
    }


def map_size(boundary: Boundary, long_side: int = 320) -> tuple[int, int]:
    """Pixel size keeping the field's real proportions (longitude shrinks with latitude)."""
    ring = boundary.coordinates[0]
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    mid_lat = math.radians((min(lats) + max(lats)) / 2)
    w = (max(lons) - min(lons)) * math.cos(mid_lat)
    h = max(lats) - min(lats)
    if w <= 0 or h <= 0:
        return long_side, long_side
    if w >= h:
        return long_side, max(16, round(long_side * h / w))
    return max(16, round(long_side * w / h)), long_side


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def parse_stats(payload: dict[str, Any]) -> list[Observation]:
    """One Observation per day that had a usable pass; empty days are skipped."""
    out = []
    for item in payload.get("data", []):
        try:
            day = datetime.fromisoformat(item["interval"]["from"].replace("Z", "+00:00")).date()
            ndvi = item["outputs"]["ndvi"]["bands"]["B0"]["stats"]
            ndmi = item["outputs"]["ndmi"]["bands"]["B0"]["stats"]
        except (KeyError, TypeError, ValueError):
            continue
        valid = int(ndvi.get("sampleCount", 0)) - int(ndvi.get("noDataCount", 0))
        values = [_num(ndvi.get("mean")), _num(ndvi.get("stDev")),
                  _num(ndmi.get("mean")), _num(ndmi.get("stDev"))]
        if valid <= 0 or any(v is None for v in values):
            continue
        n_mean, n_std, m_mean, m_std = (float(v) for v in values)  # type: ignore[arg-type]
        out.append(Observation(day, n_mean, n_std, m_mean, m_std, valid))
    return out
