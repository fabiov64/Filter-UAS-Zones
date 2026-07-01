#!/usr/bin/env python3
"""
filter_map_geojson.py — UAS Zone Filter + Map Generator (combined CLI tool)

Combines the functionality of ``filter_geojson.py`` and ``map_geojson.py``
into a single script: filters a UAS zone GeoJSON file by a geodetic search
radius, writes the result to ``filtered.json``, and immediately renders an
interactive HTML map (``map.html``).

Usage::

    python filter_map_geojson.py <file> <latitude_dms> <longitude_dms> <radius_km>

Example::

    python filter_map_geojson.py ita_zones.json "45 27 55N" "9 11 20E" 30

Outputs:
    filtered.json — zones whose centroid is within the search radius
    map.html      — interactive Leaflet map of the filtered zones

Colour legend (lower altitude limit):
    red        — AGL 0 (ground-level restriction, most restrictive)
    orange     — 25 m/ft
    yellow     — 45 m/ft
    light-blue — 60 m/ft
    purple     — any other value
"""

import json
import argparse
import re

from shapely.geometry import shape, Point, GeometryCollection
from shapely.ops import transform
from pyproj import Transformer, Geod
import folium

# WGS-84 geodetic object for accurate great-circle distance computation
geod = Geod(ellps="WGS84")

OUTPUT_GEOJSON = "filtered.json"
OUTPUT_MAP     = "map.html"


# ------------------------------------------------------------------
def dms_to_decimal(dms: str) -> float:
    """Convert a DMS coordinate string to decimal degrees.

    Accepts formats like ``45°50'34"N``, ``45 50 34 N``, or mixed.
    Handles N/S/E/W suffixes and negative degree values.

    Args:
        dms: Coordinate string in Degrees-Minutes-Seconds notation.

    Returns:
        Decimal degree value (negative for S or W).

    Raises:
        ValueError: If *dms* cannot be parsed.
    """
    pattern = r"""(?P<deg>-?\d+)[°\s]+
                  (?P<min>\d+)[\'\s]+
                  (?P<sec>\d+(?:\.\d+)?)[\"\s]*
                  (?P<dir>[NSEW])?"""
    match = re.match(pattern, dms.strip(), re.VERBOSE | re.IGNORECASE)
    if not match:
        raise ValueError(f"Invalid DMS format: {dms}")

    deg       = float(match.group("deg"))
    minutes   = float(match.group("min"))
    seconds   = float(match.group("sec"))
    direction = match.group("dir")

    decimal = abs(deg) + minutes / 60 + seconds / 3600

    # Negate for southern latitudes or western longitudes
    if deg < 0 or (direction and direction.upper() in ("S", "W")):
        decimal *= -1

    return decimal


# ------------------------------------------------------------------
def get_color(lower_limit: int, vertical_ref: str) -> str:
    """Return the Folium/CSS colour for a zone based on its lower altitude limit.

    Args:
        lower_limit: Lower altitude limit (metres or feet, as stored).
        vertical_ref: Vertical reference string, e.g. ``"AGL"`` or ``"AMSL"``.

    Returns:
        CSS colour name string.
    """
    if vertical_ref == "AGL" and lower_limit == 0:
        return "red"
    elif lower_limit == 25:
        return "orange"
    elif lower_limit == 45:
        return "yellow"
    elif lower_limit == 60:
        return "lightblue"
    else:
        return "purple"


# ------------------------------------------------------------------
def geometry_matches_search_geodetic(polygon, center_lat, center_lon, radius_m):
    """Test whether a polygon centroid is within *radius_m* of the search centre.

    Computes geodetic distance on the WGS-84 ellipsoid for accuracy at any
    latitude, avoiding flat-Earth projection errors.

    Args:
        polygon: Shapely geometry for the UAS zone footprint.
        center_lat: Reference latitude in decimal degrees.
        center_lon: Reference longitude in decimal degrees.
        radius_m: Search radius in metres.

    Returns:
        True if the centroid distance ≤ *radius_m*; False on any error.
    """
    try:
        # Repair self-intersecting rings before centroid computation
        if not polygon.is_valid:
            polygon = polygon.buffer(0)

        centroid = polygon.centroid

        # geod.inv returns (forward_az, back_az, distance_m)
        _, _, dist = geod.inv(
            center_lon,
            center_lat,
            centroid.x,
            centroid.y
        )
        return dist <= radius_m
    except Exception:
        return False


# ------------------------------------------------------------------
def process_geojson(input_geojson_path, latitude_dms, longitude_dms, radius_km):
    """Filter a UAS GeoJSON file and produce both a filtered JSON and an HTML map.

    Steps performed:
    1. Parse DMS coordinates → decimal degrees.
    2. Iterate features; include each feature if any geometry centroid is
       within *radius_km* (first-match semantics).
    3. Normalise ISO-8601 timestamps (``Z`` → ``+00:00``).
    4. Update dataset ``title`` and ``description`` with crop metadata.
    5. Write ``filtered.json``.
    6. Build a Folium map with colour-coded zone polygons and write ``map.html``.

    Args:
        input_geojson_path: Path to the source UAS GeoJSON file.
        latitude_dms: Reference latitude in DMS notation.
        longitude_dms: Reference longitude in DMS notation.
        radius_km: Search radius in kilometres.
    """
    latitude  = dms_to_decimal(latitude_dms)
    longitude = dms_to_decimal(longitude_dms)
    radius_m  = radius_km * 1000  # km → m

    # Load full dataset (utf-8-sig handles BOM that some tools add)
    with open(input_geojson_path, "r", encoding="utf-8-sig") as f:
        geojson = json.load(f)

    filtered_features = []

    # --- Spatial filter ---------------------------------------------------
    for feature in geojson.get("features", []):
        for geom in feature.get("geometry", []):
            polygon = shape(geom["horizontalProjection"])

            if geometry_matches_search_geodetic(
                polygon, latitude, longitude, radius_m
            ):
                feature_copy = feature.copy()

                # Normalise UTC suffix to strict ISO-8601
                for app in feature_copy.get("applicability", []):
                    for key in ("startDateTime", "endDateTime"):
                        if key in app and isinstance(app[key], str) and app[key].endswith("Z"):
                            app[key] = app[key].replace("Z", "+00:00")

                filtered_features.append(feature_copy)
                break  # first geometry hit is sufficient

    # --- Build output GeoJSON with updated metadata -----------------------
    filtered_geojson = {
        **{k: v for k, v in geojson.items() if k != "features"},
        "features": filtered_features
    }

    if "title" in filtered_geojson:
        filtered_geojson["title"] += " - cropped"

    # Zone counts by classification type for the description field
    geozones_count = len(filtered_features)
    atm09_count    = sum(1 for f in filtered_features if f.get("otherReasonInfo") == "ATM09")
    nfz_count      = sum(1 for f in filtered_features if f.get("otherReasonInfo") == "NFZ")
    notam_count    = sum(1 for f in filtered_features if f.get("otherReasonInfo") == "NOTAM")

    if "description" in filtered_geojson:
        # Remove any prior crop annotations before writing fresh ones
        desc_original = filtered_geojson["description"].split(" - GeoZones")[0].strip()
        filtered_geojson["description"] = (
            f"{desc_original} - cropped - "
            f"GeoZones[{geozones_count}] - "
            f"ATM09[{atm09_count}]/NFZ[{nfz_count}]/NOTAM[{notam_count}]"
        )

    # --- Write filtered.json ----------------------------------------------
    json_str = json.dumps(
        filtered_geojson,
        ensure_ascii=False,
        separators=(",", ":")
    )
    json_str = json_str.replace("},{", "},\n{")  # one feature object per line

    with open(OUTPUT_GEOJSON, "w", encoding="utf-8") as f:
        f.write(json_str)

    print(f"✔ File generated: {OUTPUT_GEOJSON}")
    print(f"✔ Features included: {len(filtered_features)}")
    print(f"✔ Decimal coordinates used: lat={latitude}, lon={longitude}")

    # --- Map generation ---------------------------------------------------
    zones  = []
    shapes = []

    for feature in filtered_features:
        name = feature.get("name", "Unnamed Zone")
        for geom in feature["geometry"]:
            zones.append({
                "name":     name,
                "geometry": geom["horizontalProjection"],
                "lower":    geom["lowerLimit"],
                "vref":     geom["lowerVerticalReference"],
                "upper":    geom["upperLimit"],
                "uref":     geom["upperVerticalReference"]
            })
            shapes.append(shape(geom["horizontalProjection"]))

    if not zones:
        print("⚠ No zones to display on map.")
        return

    # Render lower zones on top by sorting descending, then drawing last
    zones.sort(key=lambda z: z["lower"], reverse=True)
    centroid = GeometryCollection(shapes).centroid

    m = folium.Map(
        location=[centroid.y, centroid.x],
        zoom_start=10,
        tiles="OpenStreetMap"
    )

    for z in zones:
        color      = get_color(z["lower"], z["vref"])
        label      = f"{z['name']} – Lower {z['lower']} {z['vref']}"
        popup_html = (
            f"<b>{z['name']}</b><br>"
            f"Lower limit: {z['lower']} {z['vref']}<br>"
            f"Upper limit: {z['upper']} {z['uref']}"
        )

        folium.GeoJson(
            z["geometry"],
            style_function=lambda x, c=color: {
                "fillColor":   c,
                "color":       c,
                "weight":      2,
                "fillOpacity": 0.45
            },
            tooltip=label,
            popup=popup_html
        ).add_to(m)

    m.save(OUTPUT_MAP)
    print(f"✔ Map generated: {OUTPUT_MAP}")


# ------------------------------------------------------------------
def main():
    """Parse CLI arguments and run the combined filter + map pipeline."""
    parser = argparse.ArgumentParser(
        description="Filter a UAS GeoJSON file and generate an interactive map"
    )
    parser.add_argument("file",      help="Input GeoJSON file")
    parser.add_argument("latitude",  help='Latitude in DMS (e.g. 45°50\'34"N)')
    parser.add_argument("longitude", help='Longitude in DMS (e.g. 9°16\'12"E)')
    parser.add_argument("radius",    type=float, help="Search radius in km")

    args = parser.parse_args()

    process_geojson(
        input_geojson_path=args.file,
        latitude_dms=args.latitude,
        longitude_dms=args.longitude,
        radius_km=args.radius
    )


if __name__ == "__main__":
    main()
