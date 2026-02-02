#!/usr/bin/env python3

import json
import argparse
import re

from shapely.geometry import shape, Point, GeometryCollection
from shapely.ops import transform
from pyproj import Transformer, Geod
import folium

geod = Geod(ellps="WGS84")

OUTPUT_GEOJSON = "filtered.json"
OUTPUT_MAP = "map.html"

# ----------------------------
# Utility: DMS → Decimal
# ----------------------------
def dms_to_decimal(dms: str) -> float:
    pattern = r"""(?P<deg>-?\d+)[°\s]+
                  (?P<min>\d+)[\'\s]+
                  (?P<sec>\d+(?:\.\d+)?)[\"\s]*
                  (?P<dir>[NSEW])?"""
    match = re.match(pattern, dms.strip(), re.VERBOSE | re.IGNORECASE)
    if not match:
        raise ValueError(f"Invalid DMS format: {dms}")

    deg = float(match.group("deg"))
    minutes = float(match.group("min"))
    seconds = float(match.group("sec"))
    direction = match.group("dir")

    decimal = abs(deg) + minutes / 60 + seconds / 3600
    if deg < 0 or (direction and direction.upper() in ("S", "W")):
        decimal *= -1

    return decimal

# ----------------------------
# Map coloring logic
# ----------------------------
def get_color(lower_limit, vertical_ref):
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

# ----------------------------
# Geodetic match (IDENTICO)
# ----------------------------
def geometry_matches_search_geodetic(polygon, center_lat, center_lon, radius_m):
    try:
        if not polygon.is_valid:
            polygon = polygon.buffer(0)

        centroid = polygon.centroid
        _, _, dist = geod.inv(
            center_lon,
            center_lat,
            centroid.x,
            centroid.y
        )
        return dist <= radius_m
    except Exception:
        return False

# ----------------------------
# Main processing
# ----------------------------
def process_geojson(input_geojson_path, latitude_dms, longitude_dms, radius_km):
    latitude = dms_to_decimal(latitude_dms)
    longitude = dms_to_decimal(longitude_dms)
    radius_m = radius_km * 1000

    with open(input_geojson_path, "r", encoding="utf-8-sig") as f:
        geojson = json.load(f)

    filtered_features = []

    # ----------------------------
    # Filter zones (LOGICA IDENTICA)
    # ----------------------------
    for feature in geojson.get("features", []):
        for geom in feature.get("geometry", []):
            polygon = shape(geom["horizontalProjection"])

            if geometry_matches_search_geodetic(
                polygon, latitude, longitude, radius_m
            ):
                feature_copy = feature.copy()

                # Normalizza startDateTime / endDateTime in applicability (Z -> +00:00)
                for app in feature_copy.get("applicability", []):
                   for key in ("startDateTime", "endDateTime"):
                    if key in app and isinstance(app[key], str) and app[key].endswith("Z"):
                      app[key] = app[key].replace("Z", "+00:00")

                filtered_features.append(feature_copy)
                break

    # ----------------------------
    # Aggiorna title / description
    # ----------------------------
    filtered_geojson = {
        **{k: v for k, v in geojson.items() if k != "features"},
        "features": filtered_features
    }

    if "title" in filtered_geojson:
        filtered_geojson["title"] += " - cropped"

    geozones_count = len(filtered_features)
    atm09_count = sum(1 for f in filtered_features if f.get("otherReasonInfo") == "ATM09")
    nfz_count = sum(1 for f in filtered_features if f.get("otherReasonInfo") == "NFZ")
    notam_count = sum(1 for f in filtered_features if f.get("otherReasonInfo") == "NOTAM")

    if "description" in filtered_geojson:
        desc_original = filtered_geojson["description"].split(" - GeoZones")[0].strip()
        filtered_geojson["description"] = (
            f"{desc_original} - cropped - "
            f"GeoZones[{geozones_count}] - "
            f"ATM09[{atm09_count}]/NFZ[{nfz_count}]/NOTAM[{notam_count}]"
        )

    # ----------------------------
    # Scrittura filtered.json (IDENTICA)
    # ----------------------------
    json_str = json.dumps(
        filtered_geojson,
        ensure_ascii=False,
        separators=(",", ":")
    )
    json_str = json_str.replace("},{", "},\n{")

    with open(OUTPUT_GEOJSON, "w", encoding="utf-8") as f:
        f.write(json_str)

    print(f"✔ File generato: {OUTPUT_GEOJSON}")
    print(f"✔ Feature incluse: {len(filtered_features)}")
    print(f"✔ Coordinate decimali usate: lat={latitude}, lon={longitude}")

    # ----------------------------
    # Map generation (folium)
    # ----------------------------
    zones = []
    shapes = []

    for feature in filtered_features:
        name = feature.get("name", "Unnamed Zone")
        for geom in feature["geometry"]:
            zones.append({
                "name": name,
                "geometry": geom["horizontalProjection"],
                "lower": geom["lowerLimit"],
                "vref": geom["lowerVerticalReference"],
                "upper": geom["upperLimit"],
                "uref": geom["upperVerticalReference"]
            })
            shapes.append(shape(geom["horizontalProjection"]))

    if not zones:
        print("⚠ Nessuna zona da visualizzare sulla mappa.")
        return

    zones.sort(key=lambda z: z["lower"], reverse=True)
    centroid = GeometryCollection(shapes).centroid

    m = folium.Map(
        location=[centroid.y, centroid.x],
        zoom_start=10,
        tiles="OpenStreetMap"
    )

    for z in zones:
        color = get_color(z["lower"], z["vref"])
        label = f"{z['name']} – Lower {z['lower']} {z['vref']}"
        popup_html = f"""
        <b>{z['name']}</b><br>
        Lower limit: {z['lower']} {z['vref']}<br>
        Upper limit: {z['upper']} {z['uref']}
        """

        folium.GeoJson(
            z["geometry"],
            style_function=lambda x, c=color: {
                "fillColor": c,
                "color": c,
                "weight": 2,
                "fillOpacity": 0.45
            },
            tooltip=label,
            popup=popup_html
        ).add_to(m)

    m.save(OUTPUT_MAP)
    print(f"✔ Mappa generata: {OUTPUT_MAP}")

# ----------------------------
# CLI (NON MODIFICATA)
# ----------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Filtra un GeoJSON UAS e genera una mappa interattiva"
    )
    parser.add_argument("file", help="File GeoJSON di input")
    parser.add_argument("latitude", help='Latitudine in DMS (es. 45°50\'34")')
    parser.add_argument("longitude", help='Longitudine in DMS (es. 9°16\'12")')
    parser.add_argument("radius", type=float, help="Raggio in km")

    args = parser.parse_args()

    process_geojson(
        input_geojson_path=args.file,
        latitude_dms=args.latitude,
        longitude_dms=args.longitude,
        radius_km=args.radius
    )

if __name__ == "__main__":
    main()
