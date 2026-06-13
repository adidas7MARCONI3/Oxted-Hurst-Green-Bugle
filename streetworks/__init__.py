"""Street Manager road-closure feed for Oxted & Hurst Green.

A small production service that ingests DfT Street Manager open data (a push
feed delivered over AWS SNS), filters it to Oxted and Hurst Green (Surrey),
maintains the current state of road/street works and closures, and serves them
as live GeoJSON for a Leaflet map and list view.

See ``streetworks/README.md`` for the full picture; this is a self-contained
service that lives alongside the Bugle collectors but does not depend on them.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
