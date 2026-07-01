#!/usr/bin/env python3
"""
filter_geojson.py — UAS Zone GeoJSON Filter (CLI, no map output)

Reads a UAS zone GeoJSON file (ED-269 format), keeps only the features
whose polygon centroid falls within a given geodetic radius from a
reference point, and writes the result to ``filtered.json``.

Usage::

    python filter_geojson.py <file> <latitude_dms> <longitude_dms> <radius_km>

Example::

    python filter_geojson.py ita_zones.json "45 27 55N" "9 11 20E" 30

Outputs:
    filtered.json — subset of the input containing only the zones in range
"""

import json
import argparse
import re
from shapely.geometry import shape
from pyproj import Geod

# WGS-84 geodetic calculator used for accurate great-circle distances
geod = Geod(ellps="WGS84")


# ------------------------------------------------------------------
def dms_to_decimal(dms: str) -> float:
    """Convert a DMS coordinate string to decimal degrees.

    Accepts formats like ``45°50'34"N``, ``45 50 34 N``, or mixed.
    Handles N/S/E/W direction suffixes and negative degree values.

    Args:
        dms: Coordinate string in Degrees-Minutes-Seconds notation.

    Returns:
        Decimal degree value (negative for S or W).

    Raises:
        ValueError: If the string cannot be parsed as DMS.
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

    # Negate for southern latitudes or western longitudes
    if deg < 0 or (direction and direction.upper() in ("S", "W")):
        decimal *= -1

    return decimal


# ------------------------------------------------------------------
def geometry_matches_search_geodetic(polygon, center_lat, center_lon, radius_m):
    """Test whether a polygon's centroid lies within *radius_m* of the search centre.

    Uses the WGS-84 ellipsoid for distance measurement, so the result is
    accurate across all latitudes (no flat-Earth projection error).

    Args:
        polygon: Shapely geometry representing the UAS zone horizontal extent.
        center_lat: Reference latitude in decimal degrees.
        center_lon: Reference longitude in decimal degrees.
        radius_m: Search radius in metres.

    Returns:
        True if the centroid is within *radius_m*; False on any error.
    """
    try:
        # Repair self-intersecting geometries before computing centroid
        if not polygon.is_valid:
            polygon = polygon.buffer(0)

        centroid = polygon.centroid

        # geod.inv returns (az12, az21, distance_m)
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
def filter_geojson_by_radius(
    input_geojson_path: str,
    latitude_dms: str,
    longitude_dms: str,
    radius_km: float
):
    """Filter a UAS GeoJSON file to the zones within a circular search area.

    For each feature in the input file the function iterates over its geometry
    list and includes the feature in the output as soon as any single geometry
    centroid is within the search radius (first-match semantics).

    The output metadata is updated:
    * ``title`` gets the suffix ``" - cropped"``.
    * ``description`` is updated with zone counts broken down by
      ``otherReasonInfo`` value (ATM09, NFZ, NOTAM).

    ``startDateTime`` / ``endDateTime`` values that use the ``Z`` UTC suffix
    are normalised to ``+00:00`` for ISO-8601 compliance.

    Args:
        input_geojson_path: Path to the source GeoJSON file.
        latitude_dms: Reference latitude in DMS notation.
        longitude_dms: Reference longitude in DMS notation.
        radius_km: Search radius in kilometres.

    Outputs:
        Writes ``filtered.json`` in the current working directory.
    """
    latitude = dms_to_decimal(latitude_dms)
    longitude = dms_to_decimal(longitude_dms)
    radius_m = radius_km * 1000  # convert km → m for geodetic comparison

    # Load the full GeoJSON dataset (BOM-tolerant UTF-8 with utf-8-sig)
    with open(input_geojson_path, "r", encoding="utf-8-sig") as f:
        geojson = json.load(f)

    filtered_features = []

    # --- Spatial filter ---------------------------------------------------
    # A feature is included when at least one of its geometry entries has its
    # centroid inside the search circle.  The loop breaks after the first hit
    # to avoid duplicate entries.
    for feature in geojson.get("features", []):
        for geom in feature.get("geometry", []):
            polygon = shape(geom["horizontalProjection"])

            if geometry_matches_search_geodetic(
                polygon, latitude, longitude, radius_m
            ):
                feature_copy = feature.copy()

                # Normalise UTC timestamps: "Z" → "+00:00" (ISO-8601 strict)
                for app in feature_copy.get("applicability", []):
                    for key in ("startDateTime", "endDateTime"):
                        if key in app and isinstance(app[key], str) and app[key].endswith("Z"):
                            app[key] = app[key].replace("Z", "+00:00")

                filtered_features.append(feature_copy)
                break  # one geometry match is enough; skip remaining geometries

    # --- Build output GeoJSON with updated metadata -----------------------
    filtered_geojson = {
        **{k: v for k, v in geojson.items() if k != "features"},
        "features": filtered_features
    }

    if "title" in filtered_geojson:
        filtered_geojson["title"] += " - cropped"

    # Count features by zone classification type
    geozones_count = len(filtered_features)
    atm09_count = sum(1 for f in filtered_features if f.get("otherReasonInfo") == "ATM09")
    nfz_count   = sum(1 for f in filtered_features if f.get("otherReasonInfo") == "NFZ")
    notam_count = sum(1 for f in filtered_features if f.get("otherReasonInfo") == "NOTAM")

    if "description" in filtered_geojson:
        # Strip any previous cropping annotations before appending fresh ones
        desc_original = filtered_geojson["description"].split(" - GeoZones")[0].strip()
        filtered_geojson["description"] = (
            f"{desc_original} - cropped - "
            f"GeoZones[{geozones_count}] - "
            f"ATM09[{atm09_count}]/NFZ[{nfz_count}]/NOTAM[{notam_count}]"
        )

    # --- Serialise to file -----------------------------------------------
    # Compact JSON with one feature per logical line for readability
    json_str = json.dumps(
        filtered_geojson,
        ensure_ascii=False,
        separators=(",", ":")
    )
    json_str = json_str.replace("},{", "},\n{")  # one feature object per line

    with open("filtered.json", "w", encoding="utf-8") as f:
        f.write(json_str)

    print("✔ File generated: filtered.json")
    print(f"✔ Features included: {len(filtered_features)}")
    print(f"✔ Decimal coordinates used: lat={latitude}, lon={longitude}")


# ------------------------------------------------------------------
def main():
    """Parse CLI arguments and run the filter."""
    parser = argparse.ArgumentParser(
        description="Filter a UAS GeoJSON file using DMS coordinates and a radius (km)"
    )
    parser.add_argument("file",      help="Input GeoJSON file")
    parser.add_argument("latitude",  help='Latitude in DMS (e.g. 45°50\'34"N)')
    parser.add_argument("longitude", help='Longitude in DMS (e.g. 9°16\'12"E)')
    parser.add_argument("radius",    type=float, help="Search radius in km")

    args = parser.parse_args()

    filter_geojson_by_radius(
        input_geojson_path=args.file,
        latitude_dms=args.latitude,
        longitude_dms=args.longitude,
        radius_km=args.radius
    )


# ------------------------------------------------------------------
if __name__ == "__main__":
    main()
