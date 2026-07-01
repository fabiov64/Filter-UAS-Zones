#!/usr/bin/env python3
"""
interactive_uas_filter.py — Interactive UAS Zone Filter (CLI / server version)

Starts a local Flask web server and opens a browser showing an interactive
Leaflet map of all UAS zones from the supplied GeoJSON file.  The user draws
a circle on the map, then clicks **Save** to filter zones to that area and
write ``filtered.json``.

Workflow:
    1. Launch: ``python interactive_uas_filter.py <geojson_file>``
    2. Browser opens automatically at http://127.0.0.1:5000
    3. Click the circle-draw tool (left toolbar) and draw a search area.
    4. Click **💾 Save** — the server filters the original data, saves
       ``filtered.json`` in the working directory, and reloads the map.
    5. Click **🔄 Reset** to discard the filter and show all zones again.
    6. Click **❌ Quit** to shut down the server and close the browser.

Flask routes:
    GET  /        — render the full interactive map HTML
    POST /filter  — apply circle filter, save filtered.json, return JSON status
    POST /reset   — clear the current filter (show all zones)
    POST /quit    — gracefully terminate the Flask server

Outputs:
    filtered.json — written next to the input file when Save is clicked
"""

import json
import argparse
import threading
import webbrowser
import os
import signal
from flask import Flask, request, jsonify
from shapely.geometry import shape, Point, GeometryCollection
from shapely.ops import transform
from pyproj import Transformer
import folium
from folium.plugins import Draw
from pyproj import Geod

# WGS-84 geodetic object for accurate great-circle distance computation
geod = Geod(ellps="WGS84")

# Output filename written alongside the input file on Save
FILTERED_FILE = "filtered.json"

# Module-level state: original dataset loaded at startup; current holds the
# active filter result (None means "show everything").
ORIGINAL_GEOJSON = None
CURRENT_GEOJSON  = None  # None → show the full original dataset

app = Flask(__name__)

# Coordinate transformer: WGS-84 geographic → Web Mercator (metres).
# Used to build a metric buffer around the search point for a quick
# pre-filter before the precise geodetic check.
transformer = Transformer.from_crs(
    "EPSG:4326", "EPSG:3857", always_xy=True
).transform


# ------------------------------------------------------------------
def get_color(lower: int, vref: str) -> str:
    """Return a Folium/CSS colour name for a zone's lower altitude limit.

    Colour scheme (most to least restrictive):
        red        — AGL 0 (ground-level, no-fly)
        orange     — 25 m/ft floor
        yellow     — 45 m/ft floor
        light-blue — 60 m/ft floor
        purple     — any other altitude

    Args:
        lower: Lower altitude limit value.
        vref:  Vertical reference string (e.g. ``"AGL"``).

    Returns:
        CSS colour name string.
    """
    if vref == "AGL" and lower == 0:
        return "red"
    elif lower == 25:
        return "orange"
    elif lower == 45:
        return "yellow"
    elif lower == 60:
        return "lightblue"
    else:
        return "purple"


# ------------------------------------------------------------------
def geometry_matches_search_geodetic(polygon, center_lat, center_lon, radius_m):
    """Test whether a polygon centroid lies within *radius_m* of the search point.

    Uses the WGS-84 ellipsoid for precise distance measurement.

    Args:
        polygon: Shapely geometry (UAS zone horizontal footprint).
        center_lat: Search centre latitude in decimal degrees.
        center_lon: Search centre longitude in decimal degrees.
        radius_m: Search radius in metres.

    Returns:
        True if the centroid is inside the radius; False on any error.
    """
    try:
        # Repair invalid geometries (self-intersecting rings, etc.)
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
def filter_by_circle(geojson: dict, lat: float, lon: float, radius_m: float) -> dict:
    """Return a new GeoJSON dict containing only zones within the search circle.

    For each feature the function checks every geometry entry; the feature is
    included on the first geometry centroid that falls inside *radius_m*
    (first-match semantics — no duplicate features).

    ``startDateTime`` / ``endDateTime`` values with the ``Z`` UTC suffix are
    normalised to ``+00:00`` for strict ISO-8601 compliance.

    The output dataset's ``title`` and ``description`` fields are updated with
    crop metadata and zone counts broken down by ``otherReasonInfo`` type.

    Args:
        geojson:  Original GeoJSON dict (not mutated).
        lat:      Search centre latitude in decimal degrees.
        lon:      Search centre longitude in decimal degrees.
        radius_m: Search radius in metres.

    Returns:
        New GeoJSON dict with only matching features and updated metadata.
    """
    # Build a projected search area for a fast approximate pre-filter.
    # The precise geodetic check below handles the definitive include/exclude.
    center   = Point(lon, lat)
    center_m = transform(transformer, center)
    search_area = center_m.buffer(radius_m + 2)  # +2 m slop for projection error

    filtered = []

    for feature in geojson.get("features", []):
        for geom in feature.get("geometry", []):
            polygon = shape(geom["horizontalProjection"])

            if geometry_matches_search_geodetic(polygon, lat, lon, radius_m):
                feature_copy = feature.copy()

                # Normalise UTC timestamps
                for app in feature_copy.get("applicability", []):
                    for key in ("startDateTime", "endDateTime"):
                        if key in app and isinstance(app[key], str) and app[key].endswith("Z"):
                            app[key] = app[key].replace("Z", "+00:00")

                filtered.append(feature_copy)
                break  # one geometry hit is enough

    # Build output structure, preserving all top-level metadata except features
    geojson_copy = {
        **{k: v for k, v in geojson.items() if k != "features"},
        "features": filtered
    }

    if "title" in geojson_copy:
        geojson_copy["title"] += " - cropped"

    # Zone counts by classification type
    geozones_count = len(filtered)
    atm09_count    = sum(1 for f in filtered if f.get("otherReasonInfo") == "ATM09")
    nfz_count      = sum(1 for f in filtered if f.get("otherReasonInfo") == "NFZ")
    notam_count    = sum(1 for f in filtered if f.get("otherReasonInfo") == "NOTAM")

    if "description" in geojson_copy:
        # Strip any previous crop annotations before appending fresh ones
        desc_original = geojson_copy["description"].split(" - GeoZones")[0].strip()
        geojson_copy["description"] = (
            f"{desc_original} - cropped - GeoZones[{geozones_count}] "
            f"- ATM09[{atm09_count}]/NFZ[{nfz_count}]/NOTAM[{notam_count}]"
        )

    return geojson_copy


# ------------------------------------------------------------------
def generate_map_html(geojson: dict) -> str:
    """Build the full HTML page string for the interactive map.

    The page embeds a Folium/Leaflet map with:
    * All UAS zone polygons drawn with altitude-based colour coding.
    * A Leaflet.Draw toolbar restricted to circles only.
    * Three action buttons (Save / Reset / Quit) wired to Flask endpoints
      via ``fetch`` calls.

    Args:
        geojson: GeoJSON dict whose features will be rendered.

    Returns:
        Complete HTML string ready to be served as an HTTP response.

    Raises:
        RuntimeError: If *geojson* contains no valid geometries.
    """
    zones  = []
    shapes = []

    for feature in geojson.get("features", []):
        name = feature.get("name", "Unnamed zone")
        for geom in feature.get("geometry", []):
            zones.append({
                "name":     name,
                "geometry": geom["horizontalProjection"],
                "lower":    geom["lowerLimit"],
                "vref":     geom["lowerVerticalReference"],
                "upper":    geom["upperLimit"],
                "uref":     geom["upperVerticalReference"]
            })
            shapes.append(shape(geom["horizontalProjection"]))

    if not shapes:
        raise RuntimeError("No valid geometries found in GeoJSON")

    # Auto-centre on the collective centroid of all zone shapes
    centroid = GeometryCollection(shapes).centroid

    # Sort descending so that lower (more restrictive) zones render on top
    zones.sort(key=lambda z: z["lower"], reverse=True)

    m = folium.Map(location=[centroid.y, centroid.x], zoom_start=7, tiles="OpenStreetMap")

    # Draw zone polygons
    for z in zones:
        color = get_color(z["lower"], z["vref"])
        folium.GeoJson(
            z["geometry"],
            style_function=lambda x, c=color: {
                "color":       c,
                "fillColor":   c,
                "weight":      2,
                "fillOpacity": 0.45
            },
            tooltip=f"{z['name']} – Lower {z['lower']} {z['vref']}"
        ).add_to(m)

    # Leaflet.Draw toolbar — circles only (other shapes disabled)
    draw = Draw(
        draw_options={
            "circle":       True,
            "polygon":      False,
            "rectangle":    False,
            "polyline":     False,
            "marker":       False,
            "circlemarker": False
        },
        edit_options={"edit": False}
    )
    draw.add_to(m)

    # Embed the Folium-rendered map HTML inside a custom page that adds the
    # action buttons and the JavaScript event handlers.
    map_html = m.get_root().render()

    full_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>UAS Map</title>
        <style>
            #map {{ position: relative; width: 100%; height: 90vh; }}
            #save-btn, #reset-btn, #quit-btn {{
                position: absolute;
                top: 10px;
                z-index: 9999;
                background: white;
                padding: 6px 10px;
                border: 1px solid gray;
                cursor: pointer;
                font-weight: bold;
            }}
            #save-btn  {{ left:  50px; }}
            #reset-btn {{ left: 125px; }}
            #quit-btn  {{ left: 205px; }}
        </style>
    </head>
    <body>
        <div id="save-btn">💾 Save</div>
        <div id="reset-btn">🔄 Reset</div>
        <div id="quit-btn">❌ Quit</div>
        {map_html}
        <script>
            let drawnCircle = null;
            const map = window.{m.get_name()};

            // Store the most recently drawn circle so Save can read it
            map.on(L.Draw.Event.CREATED, function(e) {{
                if (drawnCircle) map.removeLayer(drawnCircle);
                drawnCircle = e.layer;
                map.addLayer(drawnCircle);
            }});

            // Save: send circle centre + radius to /filter, then reload
            document.getElementById('save-btn').onclick = function() {{
                if (!drawnCircle) {{
                    alert('Draw a circle before saving!');
                    return;
                }}
                const center = drawnCircle.getLatLng();
                const radius = drawnCircle.getRadius();
                fetch("/filter", {{
                    method: "POST",
                    headers: {{ "Content-Type": "application/json" }},
                    body: JSON.stringify({{ lat: center.lat, lon: center.lng, radius: radius }})
                }})
                .then(r => r.json())
                .then(resp => {{
                    if (resp.status === "empty") {{
                        alert("No Zones to Save");
                        return;
                    }}
                    window.location.reload();
                }});
            }};

            // Reset: clear filter on the server, then reload full map
            document.getElementById('reset-btn').onclick = function() {{
                fetch("/reset", {{ method: "POST" }}).then(() => window.location.reload());
            }};

            // Quit: shut down the Flask server, then close the browser tab
            document.getElementById('quit-btn').onclick = function() {{
                fetch("/quit", {{ method: "POST" }}).then(() => {{
                    alert('Click OK to close the browser ...');
                    window.close();
                }});
            }};
        </script>
    </body>
    </html>
    """
    return full_html


# ------------------------------------------------------------------
# Flask route handlers
# ------------------------------------------------------------------

@app.route("/")
def index():
    """Serve the interactive map page.

    Renders the currently active filtered dataset if a filter is in effect,
    otherwise renders the full original dataset.
    """
    global CURRENT_GEOJSON
    return generate_map_html(CURRENT_GEOJSON if CURRENT_GEOJSON else ORIGINAL_GEOJSON)


@app.route("/filter", methods=["POST"])
def filter_route():
    """Apply a circle filter from the browser and persist the result.

    Expects JSON body: ``{"lat": float, "lon": float, "radius": float}``
    where *radius* is in metres (as reported by Leaflet).

    Returns:
        ``{"status": "ok"}`` on success.
        ``{"status": "empty", "message": "..."}`` when no zones matched.
    """
    global CURRENT_GEOJSON

    data     = request.json
    filtered = filter_by_circle(
        ORIGINAL_GEOJSON,
        data["lat"],
        data["lon"],
        data["radius"]
    )

    # Inform the browser so it can show an alert instead of reloading
    if not filtered.get("features"):
        return jsonify({
            "status":  "empty",
            "message": "No Zones to Save"
        }), 200

    CURRENT_GEOJSON = filtered

    # Persist the filtered dataset in the working directory
    with open(FILTERED_FILE, "w", encoding="utf-8") as f:
        json_str = json.dumps(
            CURRENT_GEOJSON,
            ensure_ascii=False,
            separators=(",", ":")
        )
        json_str = json_str.replace("},{", "},\n{")
        f.write(json_str)

    return jsonify({"status": "ok"})


@app.route("/reset", methods=["POST"])
def reset_route():
    """Clear the current filter so the next map render shows all zones."""
    global CURRENT_GEOJSON
    CURRENT_GEOJSON = None
    return jsonify({"status": "ok"})


@app.route("/quit", methods=["POST"])
def quit_route():
    """Shut down the Flask server by sending SIGINT to the process."""
    def shutdown():
        os.kill(os.getpid(), signal.SIGINT)

    threading.Thread(target=shutdown).start()
    return jsonify({"status": "quitting"})


# ------------------------------------------------------------------
def main():
    """Load the GeoJSON file and start the Flask server."""
    global ORIGINAL_GEOJSON

    parser = argparse.ArgumentParser(
        description="Interactive UAS zone filter — opens a browser map"
    )
    parser.add_argument("file", help="UAS GeoJSON file to display")
    args = parser.parse_args()

    # Load the full dataset once at startup; never mutated during the session
    with open(args.file, "r", encoding="utf-8-sig") as f:
        ORIGINAL_GEOJSON = json.load(f)

    url = "http://127.0.0.1:5000"

    # Open the browser slightly after the server starts (1 s grace period)
    threading.Timer(1.0, lambda: webbrowser.open(url, new=1)).start()

    app.run(debug=False, use_reloader=False)


# ------------------------------------------------------------------
if __name__ == "__main__":
    main()
