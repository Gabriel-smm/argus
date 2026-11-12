"""Fill a site profile's "nearby" list from OpenStreetMap.

Asks the public Overpass API (OpenStreetMap data, ODbL) once for airports,
communication towers and power infrastructure around the site, and writes them
into the site file with the bands each one explains. Run it before a demo or a
deployment, with internet. Argus itself never calls the internet: it only reads
the saved file, so it stays passive.

From the repository root:

    python -m context_sources.osm_site                      # updates data/context/site.json
    python -m context_sources.osm_site --lat 41.70 --lon -86.24 --radius-km 10 \
        --name "My site" --out data/context/site_mysite.json

For many sites, or with no Overpass access, the same features are in the
Geofabrik state extracts (.osm.pbf) listed in the source log.
"""

import argparse
import json
import math
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SITE = ROOT / "data" / "context" / "site.json"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
MAX_PER_KIND = 10

AIRPORT_BANDS = ["aviation_voice", "dme", "ssr_1030", "adsb_1090", "radar_s"]
CELL_BANDS = ["cell_low", "cell_mid", "cell_25", "cband_5g"]


def query(lat, lon, radius_m):
    around = f"(around:{radius_m},{lat},{lon})"
    return f"""[out:json][timeout:60];
(
  nwr{around}["aeroway"~"^(aerodrome|heliport)$"];
  nwr{around}["man_made"="communications_tower"];
  nwr{around}["man_made"~"^(mast|tower)$"]["tower:type"~"^(communication|broadcast)$"];
  nwr{around}["power"~"^(plant|substation)$"];
);
out center tags;"""


def distance_km(lat1, lon1, lat2, lon2):
    """Great-circle distance."""
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def classify(tags):
    """What kind of feature this is, and which bands it explains."""
    if tags.get("aeroway") == "aerodrome":
        return "airport", AIRPORT_BANDS, ""
    if tags.get("aeroway") == "heliport":
        return "heliport", ["aviation_voice", "adsb_1090"], ""
    if tags.get("tower:type") == "broadcast":
        return "broadcast tower", ["fm_broadcast"], ""
    if tags.get("man_made") in ("communications_tower", "mast", "tower"):
        return "communication tower", CELL_BANDS, ""
    if tags.get("power") == "plant":
        return "power plant", [], "can cause electrical noise that looks like interference"
    if tags.get("power") == "substation":
        return "power substation", [], "can cause electrical noise that looks like interference"
    return None, [], ""


def features(payload, lat, lon):
    """Turn an Overpass reply into the site's nearby list, closest first per kind."""
    found = {}
    for element in payload.get("elements", []):
        tags = element.get("tags", {})
        kind, implies, effect = classify(tags)
        if not kind:
            continue
        point = element.get("center") or element
        if "lat" not in point or "lon" not in point:
            continue
        name = tags.get("name") or tags.get("operator") or f"unnamed {kind}"
        if tags.get("iata"):
            name += f" ({tags['iata']})"
        item = {
            "kind": kind,
            "name": name,
            "distance_km": round(distance_km(lat, lon, point["lat"], point["lon"]), 1),
            "implies": implies,
            "source": f"OpenStreetMap {element.get('type', 'element')} {element.get('id', '')}".strip(),
        }
        if effect:
            item["effect"] = effect
        found.setdefault(kind, []).append(item)
    nearby = []
    for items in found.values():
        items.sort(key=lambda item: item["distance_km"])
        nearby += items[:MAX_PER_KIND]
    nearby.sort(key=lambda item: item["distance_km"])
    return nearby


def fetch(lat, lon, radius_km):
    body = urllib.parse.urlencode({"data": query(lat, lon, round(radius_km * 1000))}).encode()
    request = urllib.request.Request(OVERPASS_URL, data=body, headers={"User-Agent": "argus-site-profile"})
    with urllib.request.urlopen(request, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--site", type=Path, default=DEFAULT_SITE, help="site file to start from")
    parser.add_argument("--out", type=Path, help="where to write; defaults to --site")
    parser.add_argument("--lat", type=float)
    parser.add_argument("--lon", type=float)
    parser.add_argument("--radius-km", type=float)
    parser.add_argument("--name")
    args = parser.parse_args()

    site = json.loads(args.site.read_text(encoding="utf-8")) if args.site.is_file() else {}
    lat = args.lat if args.lat is not None else site["latitude"]
    lon = args.lon if args.lon is not None else site["longitude"]
    radius = args.radius_km or site.get("radius_km", 10)
    site.update({"latitude": lat, "longitude": lon, "radius_km": radius})
    if args.name:
        site["name"] = args.name
    site.setdefault("name", f"Site at {lat}, {lon}")
    site.setdefault("frequency_list", "United States (FCC / NTIA)")
    site.setdefault("expected_bands", [])
    site.setdefault("restricted", [])

    nearby = features(fetch(lat, lon, radius), lat, lon)
    site["nearby"] = nearby
    added = []
    for item in nearby:
        for band in item["implies"]:
            if band not in site["expected_bands"]:
                site["expected_bands"].append(band)
                added.append(band)

    out = args.out or args.site
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(site, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(nearby)} nearby features to {out}")
    for item in nearby:
        print(f"  {item['distance_km']:>5} km  {item['kind']}: {item['name']}")
    if added:
        print(f"Added to expected bands because of these features: {', '.join(added)}")


if __name__ == "__main__":
    main()
