"""Build frontend/src/data/india-states.json from DataMeet's state boundaries.

Source: https://github.com/datameet/maps (States/Admin2.shp), boundaries updated to the
Survey of India map (Ladakh and J&K, 2021). License: CC BY 4.0, DataMeet India community.

The shapefile is 17 MB; this script simplifies it and pre-projects it into SVG paths
(about 100 KB), so the browser needs no GIS library.

    uv run --with pyshp --with shapely python scripts/build_india_map.py
"""

import json
import math
import sys
import urllib.request
from pathlib import Path

import shapefile  # pyshp
from shapely.geometry import shape
from shapely.ops import transform

BASE = "https://raw.githubusercontent.com/datameet/maps/master/States/Admin2"
CACHE = Path(__file__).parent / ".cache"
OUT = Path(__file__).parent.parent / "frontend" / "src" / "data" / "india-states.json"

# DataMeet name -> the state names TenderLens stores (tenders/pincode.py)
RENAME = {
    "Andaman & Nicobar": "Andaman and Nicobar Islands",
    "Jammu & Kashmir": "Jammu and Kashmir",
}
WIDTH = 600.0
LAT0 = math.radians(23.0)  # equirectangular projection centred on India


def fetch() -> Path:
    CACHE.mkdir(exist_ok=True)
    for ext in ("shp", "shx", "dbf", "prj"):
        dest = CACHE / f"Admin2.{ext}"
        if not dest.exists():
            print(f"downloading Admin2.{ext}", file=sys.stderr)
            urllib.request.urlretrieve(f"{BASE}.{ext}", dest)
    return CACHE / "Admin2"


def project(lon, lat):
    return lon * math.cos(LAT0), -lat


def path_d(geom, ox, oy, k) -> str:
    polys = [geom] if geom.geom_type == "Polygon" else list(geom.geoms)
    parts = []
    for poly in polys:
        for ring in [poly.exterior, *poly.interiors]:
            pts = [((x - ox) * k, (y - oy) * k) for x, y in ring.coords]
            if len(pts) < 3:
                continue
            parts.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in pts[:-1]) + "Z")
    return "".join(parts)


def main():
    reader = shapefile.Reader(str(fetch()))
    states = []
    for sr in reader.shapeRecords():
        name = RENAME.get(sr.record["ST_NM"], sr.record["ST_NM"])
        geom = transform(project, shape(sr.shape.__geo_interface__))
        area = geom.area
        # Simplify big states hard, tiny UTs (Chandigarh, Delhi, Puducherry) gently.
        tol = 0.02 if area > 5 else 0.004 if area > 0.2 else 0.0008
        geom = geom.simplify(tol, preserve_topology=True)
        states.append((name, geom))

    minx = min(g.bounds[0] for _, g in states)
    miny = min(g.bounds[1] for _, g in states)
    maxx = max(g.bounds[2] for _, g in states)
    maxy = max(g.bounds[3] for _, g in states)
    k = WIDTH / (maxx - minx)
    height = (maxy - miny) * k

    out = {
        "attribution": "State boundaries: DataMeet India community (CC BY 4.0), "
        "github.com/datameet/maps",
        "viewBox": f"0 0 {WIDTH:.0f} {height:.0f}",
        "states": [],
    }
    for name, geom in sorted(states):
        c = geom.representative_point()
        out["states"].append(
            {
                "name": name,
                "d": path_d(geom, minx, miny, k),
                "cx": round((c.x - minx) * k, 1),
                "cy": round((c.y - miny) * k, 1),
            }
        )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, separators=(",", ":")))
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB, {len(states)} regions)")


if __name__ == "__main__":
    main()
