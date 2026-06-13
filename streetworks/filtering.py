"""The two-stage filter that scopes the national feed to Oxted & Hurst Green.

Stage 1 — authority: keep a record only if its highway authority is Surrey CC
(by the ``ha_org`` SNS attribute or the ``highway_authority_swa_code`` body
field). This is a cheap string check done before any coordinate maths.

Stage 2 — geography: after converting to WGS84, keep only records whose
representative point falls inside the configured bounding box. An optional
USRN allow-list can refine this further once real USRNs are known.
"""
from __future__ import annotations

from .config import BBox, Settings


def passes_authority(
    object_data: dict,
    attributes: dict[str, str],
    settings: Settings,
) -> bool:
    """Stage 1: is this Surrey County Council's record?"""
    swa = settings.surrey_swa_code
    ha_org = attributes.get("ha_org")
    body_code = object_data.get("highway_authority_swa_code")
    # Compare as strings; SWA codes are numeric-looking but treated as opaque.
    return str(ha_org) == str(swa) or str(body_code) == str(swa)


def passes_geography(
    lon: float,
    lat: float,
    bbox: BBox,
    *,
    usrn: str | None = None,
    usrn_allow_list: frozenset[str] | None = None,
) -> bool:
    """Stage 2: does the geometry fall inside the area?

    If a ``usrn_allow_list`` is supplied, a USRN on the list passes regardless
    of the bounding box (a precise refinement); otherwise the bounding box is
    authoritative.
    """
    if usrn_allow_list and usrn is not None and str(usrn) in usrn_allow_list:
        return True
    return bbox.contains(lon, lat)
