#!/usr/bin/env python3
"""
interactive_uas_filter (app).py — Interactive UAS Zone Filter (macOS App bundle)

This is the macOS application variant of ``interactive_uas_filter.py``.
It is identical in behaviour except for two macOS-specific adaptations:

1. **File selection via native dialog** — instead of accepting a CLI argument,
   it calls ``osascript`` to present the system *Open File* dialog so the user
   can pick the GeoJSON file with a standard Finder sheet.

2. **Browser close on Quit** — the ``/quit`` route tries to close the
   front-most browser window using an AppleScript keystroke (⌘W) before
   terminating Flask, giving a cleaner shutdown experience in the app bundle.

3. **Output written next to the input file** — ``filtered.json`` is saved in
   the same directory as the chosen input file rather than the working directory.

All other behaviour (Flask routes, map rendering, colour scheme, filter logic)
is identical to the CLI version.

Usage (when run directly):
    python "interactive_uas_filter (app).py"

This script is normally launched by the macOS ``.app`` bundle produced by
``py2app`` / the packaged binary in ``MacOs binaries/``.

Flask routes:
    GET  /        — render the interactive map HTML
    POST /filter  — apply circle filter, save filtered.json, return JSON status
    POST /reset   — clear the current filter
    POST /quit    — close browser window (AppleScript) then shut down Flask

Outputs:
    filtered.json — written in the same directory as the input file on Save
"""

import json
import argparse
import threading
import webbrowser
import os
import signal
import subprocess
from flask import Flask, request, jsonify
from shapely.geometry import shape, Point, GeometryCollection
from shapely.ops import transform
from pyproj import Transformer
import folium
from folium.plugins import Draw
from pyproj import Geod

# WGS-84 geodetic object for accurate great-circle distance computation
geod = Geod(ellps="WGS84")

# Output filename; written inside INPUT_DIR (same directory as the input file)
FILTERED_FILE = "filtered.json"

# Module-level state loaded at startup.  CURRENT_GEOJSON holds the active
# filter result; None means "show everything".
ORIGINAL_GEOJSON = None
CURRENT_GEOJSON  = None
INPUT_DIR        = None  # directory of the file chosen via the macOS dialog

app = Flask(__name__)

# Coordinate transformer: WGS-84 geographic → Web Mercator (metres).
# Used to construct a metric buffer for the pre-filter step.
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
        polygon:    Shapely geometry (UAS zone horizontal footprint).
        center_lat: Search centre latitude in decimal degrees.
        center_lon: Search centre longitude in decimal degrees.
        radius_m:   Search radius in metres.

    Returns:
        True if the centroid is inside the radius; False on any error.
    """
    try:
        # Repair invalid geometries before computing centroid
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

    For each feature, the function checks every geometry entry and includes the
    feature on the first centroid match (first-match semantics — no duplicates).

    ``startDateTime`` / ``endDateTime`` UTC ``Z`` suffixes are normalised to
    ``+00:00`` for strict ISO-8601 compliance.

    The output dataset's ``title`` and ``description`` are updated with crop
    metadata and zone counts by ``otherReasonInfo`` type (ATM09, NFZ, NOTAM).

    Args:
        geojson:  Original GeoJSON dict (not mutated).
        lat:      Search centre latitude in decimal degrees.
        lon:      Search centre longitude in decimal degrees.
        radius_m: Search radius in metres.

    Returns:
        New GeoJSON dict with only matching features and updated metadata.
    """
    center      = Point(lon, lat)
    center_m    = transform(transformer, center)
    search_area = center_m.buffer(radius_m + 2)  # projected pre-filter area

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

    # Zone counts by classification
    geozones_count = len(filtered)
    atm09_count    = sum(1 for f in filtered if f.get("otherReasonInfo") == "ATM09")
    nfz_count      = sum(1 for f in filtered if f.get("otherReasonInfo") == "NFZ")
    notam_count    = sum(1 for f in filtered if f.get("otherReasonInfo") == "NOTAM")

    if "description" in geojson_copy:
        # Strip any prior crop annotations before appending fresh ones
        desc_original = geojson_copy["description"].split(" - GeoZones")[0].strip()
        geojson_copy["description"] = (
            f"{desc_original} - cropped - GeoZones[{geozones_count}] "
            f"- ATM09[{atm09_count}]/NFZ[{nfz_count}]/NOTAM[{notam_count}]"
        )

    return geojson_copy


# ------------------------------------------------------------------
def generate_map_html(geojson: dict) -> str:
    """Build the full HTML page string for the interactive map.

    Identical to the CLI version except the Quit button does not call
    ``window.close()`` (the server-side shutdown handles the window via
    AppleScript instead).

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

    # Draw zone polygons with altitude-based colour coding
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

    # Leaflet.Draw toolbar — circles only
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

            // Store the most recently drawn circle so Save can read its geometry
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

            // Quit: the server closes the browser via AppleScript; no window.close() needed
            document.getElementById('quit-btn').onclick = function() {{
                fetch("/quit", {{ method: "POST" }});
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
    """Serve the interactive map page (filtered view or full dataset)."""
    return generate_map_html(CURRENT_GEOJSON if CURRENT_GEOJSON else ORIGINAL_GEOJSON)


@app.route("/filter", methods=["POST"])
def filter_route():
    """Apply a circle filter from the browser and write filtered.json.

    Expects JSON body: ``{"lat": float, "lon": float, "radius": float}``
    where *radius* is in metres (as reported by Leaflet).

    The output file is written to *INPUT_DIR* (same folder as the source file).

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

    if not filtered.get("features"):
        return jsonify({
            "status":  "empty",
            "message": "No Zones to Save"
        }), 200

    CURRENT_GEOJSON = filtered

    # Save next to the input file so the result is easy to find in Finder
    output_path = os.path.join(INPUT_DIR, FILTERED_FILE)

    with open(output_path, "w", encoding="utf-8") as f:
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
    """Close the front-most browser window via AppleScript, then stop Flask.

    The AppleScript sends ⌘W to System Events, which closes the browser tab
    without requiring ``window.close()`` from JavaScript (which Safari blocks
    for windows not opened by script).
    """
    def shutdown():
        try:
            # Close the front-most browser window using a system-level keystroke
            subprocess.run([
                "osascript",
                "-e",
                'tell application "System Events" to keystroke "w" using command down'
            ])
        except Exception:
            pass

        # Terminate the Flask server
        os.kill(os.getpid(), signal.SIGINT)

    threading.Thread(target=shutdown).start()
    return jsonify({"status": "quitting"})


# ------------------------------------------------------------------
def choose_file_macos() -> str:
    """Display the macOS native Open File dialog and return the chosen path.

    Uses ``osascript`` to invoke the AppleScript ``choose file`` command,
    which shows the standard system file picker sheet.

    Returns:
        Absolute POSIX path string of the selected file.

    Raises:
        RuntimeError: If the user cancels the dialog or ``osascript`` fails.
    """
    script = '''
    POSIX path of (choose file with prompt "Please select the JSON file")
    '''
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        raise RuntimeError("No file selected")
    return result.stdout.strip()


# ------------------------------------------------------------------
def main():
    """Present the file dialog, load the GeoJSON, and start the Flask server."""
    global ORIGINAL_GEOJSON, INPUT_DIR

    # macOS app: use the system file picker instead of a CLI argument
    input_file = choose_file_macos()
    INPUT_DIR  = os.path.dirname(input_file)

    # Load the full dataset once; never mutated during the session
    with open(input_file, "r", encoding="utf-8-sig") as f:
        ORIGINAL_GEOJSON = json.load(f)

    url = "http://127.0.0.1:5000"

    # Open the browser ~1 s after Flask starts (grace period for bind)
    threading.Timer(1.0, lambda: webbrowser.open(url, new=1)).start()

    app.run(debug=False, use_reloader=False)


# ------------------------------------------------------------------
if __name__ == "__main__":
    main()
