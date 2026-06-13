"""Coordinate handling: WKT in British National Grid → WGS84 lon/lat.

Street Manager ``*_coordinates`` fields are WKT in EPSG:27700 (easting/northing),
e.g. ``POINT(538500 152400)`` or ``LINESTRING(538500 152400, 538600 152500)``.
For the Leaflet map we need WGS84 / EPSG:4326 (lon/lat), but we keep both so the
original grid geometry is never lost.
"""
from __future__ import annotations

import re
from functools import lru_cache

# POINT / LINESTRING with an optional Z and any case; capture the geom type and
# the coordinate list between the outer parentheses.
_WKT_RE = re.compile(
    r"^\s*(POINT|LINESTRING)\s*(?:Z\s*)?\(\s*(.*?)\s*\)\s*$",
    re.IGNORECASE | re.DOTALL,
)


@lru_cache(maxsize=1)
def _transformer():
    # Imported lazily so importing this module doesn't hard-require pyproj until
    # a conversion is actually attempted.
    from pyproj import Transformer

    # always_xy=True ⇒ inputs/outputs are (x, y) = (easting, northing) and
    # (lon, lat), matching GeoJSON's lon-first ordering.
    return Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)


def _parse_pair(token: str) -> tuple[float, float]:
    parts = token.split()
    if len(parts) < 2:
        raise ValueError(f"coordinate pair needs 2 numbers, got {token!r}")
    return float(parts[0]), float(parts[1])


def parse_wkt(wkt: str) -> tuple[str, list[tuple[float, float]]]:
    """Parse a POINT/LINESTRING WKT string into (geom_type, [(x, y), ...]).

    Coordinates are returned in the source CRS unchanged.
    """
    if not isinstance(wkt, str):
        raise ValueError("WKT must be a string")
    m = _WKT_RE.match(wkt)
    if not m:
        raise ValueError(f"unsupported or malformed WKT: {wkt!r}")
    geom_type = m.group(1).upper()
    body = m.group(2)
    if geom_type == "POINT":
        return geom_type, [_parse_pair(body)]
    # LINESTRING: comma-separated pairs.
    pairs = [p for p in (chunk.strip() for chunk in body.split(",")) if p]
    if len(pairs) < 2:
        raise ValueError("LINESTRING needs at least 2 points")
    return geom_type, [_parse_pair(p) for p in pairs]


def _geojson_type(geom_type: str) -> str:
    return {"POINT": "Point", "LINESTRING": "LineString"}[geom_type]


def convert_wkt(wkt: str) -> tuple[dict, dict, tuple[float, float]]:
    """Convert EPSG:27700 WKT to GeoJSON in both CRSs plus a representative point.

    Returns ``(geometry_27700, geometry_4326, (lon, lat))`` where the
    representative point is the WGS84 centroid used for the bounding-box test.
    """
    geom_type, src_coords = parse_wkt(wkt)
    transformer = _transformer()

    wgs_coords = [transformer.transform(x, y) for x, y in src_coords]  # (lon, lat)

    gj_type = _geojson_type(geom_type)
    if geom_type == "POINT":
        geometry_27700 = {"type": "Point", "coordinates": [src_coords[0][0], src_coords[0][1]]}
        geometry_4326 = {"type": "Point", "coordinates": [wgs_coords[0][0], wgs_coords[0][1]]}
    else:
        geometry_27700 = {
            "type": gj_type,
            "coordinates": [[x, y] for x, y in src_coords],
        }
        geometry_4326 = {
            "type": gj_type,
            "coordinates": [[lon, lat] for lon, lat in wgs_coords],
        }

    # Representative point = mean of the WGS84 vertices (the point itself for a
    # POINT). Good enough for a bounding-box containment test.
    lon = sum(c[0] for c in wgs_coords) / len(wgs_coords)
    lat = sum(c[1] for c in wgs_coords) / len(wgs_coords)
    return geometry_27700, geometry_4326, (lon, lat)
