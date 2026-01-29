#!/usr/bin/env python3

import json
import argparse
import re
from shapely.geometry import shape
from pyproj import Geod

geod = Geod(ellps="WGS84")

# ==================================================
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

# ==================================================
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

# ==================================================
def filter_geojson_by_radius(
    input_geojson_path: str,
    latitude_dms: str,
    longitude_dms: str,
    radius_km: float
):
    latitude = dms_to_decimal(latitude_dms)
    longitude = dms_to_decimal(longitude_dms)
    radius_m = radius_km * 1000

    with open(input_geojson_path, "r", encoding="utf-8-sig") as f:
        geojson = json.load(f)

    filtered_features = []

    # ==================================================
    # Filtering (LOGICA IDENTICA)
    # ==================================================
    for feature in geojson.get("features", []):
        for geom in feature.get("geometry", []):
            polygon = shape(geom["horizontalProjection"])

            if geometry_matches_search_geodetic(
                polygon, latitude, longitude, radius_m
            ):
                feature_copy = feature.copy()

                # ED-269 / RC compatibility
                app = feature_copy.get("applicability")
                if app and isinstance(app, list):
                    for a in app:
                        if "startDateTime" in a or "endDateTime" in a:
                            feature_copy.pop("applicability", None)
                            feature_copy["description"] = (
                                "[Date/Time removed for RC compatibility]"
                            )
                            break

                filtered_features.append(feature_copy)
                break

    # ==================================================
    # Aggiornamento title / description
    # ==================================================
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

    # ==================================================
    # Scrittura filtered.json (IDENTICA)
    # ==================================================
    json_str = json.dumps(
        filtered_geojson,
        ensure_ascii=False,
        separators=(",", ":")
    )

    # newline dopo ogni feature
    json_str = json_str.replace("},{", "},\n{")

    with open("filtered.json", "w", encoding="utf-8") as f:
        f.write(json_str)

    print("✔ File generato: filtered.json")
    print(f"✔ Feature incluse: {len(filtered_features)}")
    print(f"✔ Coordinate decimali usate: lat={latitude}, lon={longitude}")

# ==================================================
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

# ==================================================
if __name__ == "__main__":
    main()
