#!/usr/bin/env python3
"""
map_geojson.py — UAS Zone Map Renderer

Reads a pre-filtered UAS zone GeoJSON file (``filtered.json`` by default)
and generates an interactive HTML map (``map.html``) using Folium/Leaflet.

Zones are colour-coded by their lower altitude limit and vertical reference:

    ============  =========  ===========
    lower_limit   vref       colour
    ============  =========  ===========
    0             AGL        red
    25            any        orange
    45            any        yellow
    60            any        light-blue
    other         any        purple
    ============  =========  ===========

Zones are drawn from highest to lowest so that lower (more restrictive)
zones visually sit on top.

Usage::

    python map_geojson.py

    # or point at a different file by editing INPUT_FILE at the top of the script

Outputs:
    map.html — interactive Leaflet map, auto-centred on the dataset
"""

import json
import folium
from shapely.geometry import shape, GeometryCollection

# Input / output file paths (edit here to override)
INPUT_FILE  = "filtered.json"
OUTPUT_FILE = "map.html"


# ------------------------------------------------------------------
def get_color(lower_limit: int, vertical_ref: str) -> str:
    """Return the Folium/CSS colour name for a UAS zone based on its lower limit.

    The colour scheme encodes operational significance:
    * Red   — ground-level restriction (AGL 0), most restrictive.
    * Orange/Yellow/LightBlue — progressively higher, less restrictive floors.
    * Purple — any other altitude not covered by the fixed thresholds.

    Args:
        lower_limit: Lower altitude limit of the zone (metres or ft, as-stored).
        vertical_ref: Vertical reference system string, e.g. ``"AGL"`` or ``"AMSL"``.

    Returns:
        A CSS colour name string accepted by Folium style functions.
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
# Load the filtered GeoJSON dataset (utf-8-sig tolerates BOM in exported files)
with open(INPUT_FILE, "r", encoding="utf-8-sig") as f:
    data = json.load(f)

zones = []

# --- Extract zone geometries and metadata from each feature ---------------
# A single ED-269 feature may contain multiple geometry entries (e.g. segments
# of the same zone at different altitudes).  Each geometry becomes one map layer.
for feature in data["features"]:
    name = feature.get("name", "Unnamed Zone")

    for geom in feature["geometry"]:
        zones.append({
            "name":     name,
            "geometry": geom["horizontalProjection"],   # GeoJSON polygon dict
            "lower":    geom["lowerLimit"],
            "vref":     geom["lowerVerticalReference"],
            "upper":    geom["upperLimit"],
            "uref":     geom["upperVerticalReference"]
        })

# Sort descending by lower limit so that lower (more restrictive) zones are
# rendered last and therefore appear on top in the Leaflet z-order.
zones.sort(key=lambda z: z["lower"], reverse=True)

# --- Compute map centre from the collective centroid of all zone shapes ----
shapes   = [shape(z["geometry"]) for z in zones]
centroid = GeometryCollection(shapes).centroid

m = folium.Map(
    location=[centroid.y, centroid.x],
    zoom_start=10,
    tiles="OpenStreetMap"
)

# --- Draw each zone as a coloured GeoJSON overlay -------------------------
for z in zones:
    color = get_color(z["lower"], z["vref"])

    # Tooltip shown on hover; popup shown on click
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

# --- Save the rendered map ------------------------------------------------
m.save(OUTPUT_FILE)
print(f"Map generated: {OUTPUT_FILE}")
