#!/usr/bin/env python3

import json
import argparse
import re

from shapely.geometry import shape, Point, GeometryCollection
from shapely.ops import transform
from pyproj import Transformer
import folium


OUTPUT_GEOJSON = "filtered.json"
OUTPUT_MAP = "map.html"


# ----------------------------
# Utility: DMS → Decimal
# ----------------------------
def dms_to_decimal(dms: str) -> float:
    """
    Convert DMS coordinates (e.g. 45°50'34") to decimal degrees.
    Supports N/S/E/W.
    """
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
# Main processing
# ----------------------------
def process_geojson(input_geojson_path, latitude_dms, longitude_dms, radius_km):
    # Convert coordinates
    latitude = dms_to_decimal(latitude_dms)
    longitude = dms_to_decimal(longitude_dms)

    with open(input_geojson_path, "r", encoding="utf-8-sig") as f:
        geojson = json.load(f)

    # Coordinate transformer (WGS84 → Web Mercator)
    transformer = Transformer.from_crs(
        "EPSG:4326", "EPSG:3857", always_xy=True
    ).transform

    center_point = Point(longitude, latitude)
    center_point_m = transform(transformer, center_point)

    radius_m = radius_km * 1000
    search_area_m = center_point_m.buffer(radius_m)

    filtered_features = []

    # Filter zones
    for feature in geojson.get("features", []):
        for geom in feature.get("geometry", []):
            polygon = shape(geom["horizontalProjection"])
            polygon_m = transform(transformer, polygon)

            if polygon_m.intersects(search_area_m):
                # Rimuovo 'applicability' dalla feature
                feature_copy = feature.copy()
                feature_copy.pop("applicability", None)
                filtered_features.append(feature_copy)
                break

    filtered_geojson = {
        **geojson,
        "features": filtered_features
    }

    # Save filtered GeoJSON
    with open(OUTPUT_GEOJSON, "w", encoding="utf-8") as f:
        json.dump(filtered_geojson, f, indent=2, ensure_ascii=False)

    print(f"✔ File generato: {OUTPUT_GEOJSON}")
    print(f"✔ Feature incluse: {len(filtered_features)}")
    print(f"✔ Coordinate decimali usate: lat={latitude}, lon={longitude}")

    # ----------------------------
    # Map generation (folium)
    # ----------------------------
    zones = []

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

    if not zones:
        print("⚠ Nessuna zona da visualizzare sulla mappa.")
        return

    # Draw higher zones first, lower zones on top
    zones.sort(key=lambda z: z["lower"], reverse=True)

    shapes = [shape(z["geometry"]) for z in zones]
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
# CLI
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
