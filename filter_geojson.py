#!/usr/bin/env python3

import json
import argparse
import re
from shapely.geometry import shape, Point
from shapely.ops import transform
from pyproj import Transformer


def dms_to_decimal(dms: str) -> float:
    """
    Converte una coordinata in formato DMS (es. 45°50'34")
    in gradi decimali.
    Supporta N/S/E/W.
    """
    pattern = r"""(?P<deg>-?\d+)[°\s]+
                  (?P<min>\d+)[\'\s]+
                  (?P<sec>\d+(?:\.\d+)?)[\"\s]*
                  (?P<dir>[NSEW])?"""
    match = re.match(pattern, dms.strip(), re.VERBOSE | re.IGNORECASE)

    if not match:
        raise ValueError(f"Formato DMS non valido: {dms}")

    deg = float(match.group("deg"))
    minutes = float(match.group("min"))
    seconds = float(match.group("sec"))
    direction = match.group("dir")

    decimal = abs(deg) + minutes / 60 + seconds / 3600

    if deg < 0 or (direction and direction.upper() in ("S", "W")):
        decimal *= -1

    return decimal


def filter_geojson_by_radius(
    input_geojson_path: str,
    latitude_dms: str,
    longitude_dms: str,
    radius_km: float
):
    latitude = dms_to_decimal(latitude_dms)
    longitude = dms_to_decimal(longitude_dms)

    with open(input_geojson_path, "r", encoding="utf-8") as f:
        geojson = json.load(f)

    transformer = Transformer.from_crs(
        "EPSG:4326", "EPSG:3857", always_xy=True
    ).transform

    center_point = Point(longitude, latitude)
    center_point_m = transform(transformer, center_point)

    radius_m = radius_km * 1000
    search_area_m = center_point_m.buffer(radius_m)

    filtered_features = []

    for feature in geojson.get("features", []):
        for geom in feature.get("geometry", []):
            polygon = shape(geom["horizontalProjection"])
            polygon_m = transform(transformer, polygon)

            if polygon_m.intersects(search_area_m):
                filtered_features.append(feature)
                break

    filtered_geojson = {
        **geojson,
        "features": filtered_features
    }

    with open("filtered.json", "w", encoding="utf-8") as f:
        json.dump(filtered_geojson, f, indent=2, ensure_ascii=False)

    print("✔ File generato: filtered.json")
    print(f"✔ Feature incluse: {len(filtered_features)}")
    print(f"✔ Coordinate decimali usate: lat={latitude}, lon={longitude}")


def main():
    parser = argparse.ArgumentParser(
        description="Filtra un GeoJSON usando coordinate DMS e un raggio (km)"
    )
    parser.add_argument("file", help="File GeoJSON di input")
    parser.add_argument("latitude", help='Latitudine in DMS (es. 45°50\'34")')
    parser.add_argument("longitude", help='Longitudine in DMS (es. 9°16\'12")')
    parser.add_argument("radius", type=float, help="Raggio in km")

    args = parser.parse_args()

    filter_geojson_by_radius(
        input_geojson_path=args.file,
        latitude_dms=args.latitude,
        longitude_dms=args.longitude,
        radius_km=args.radius
    )


if __name__ == "__main__":
    main()
