#!/usr/bin/env python3

import json
import argparse
import threading
import webbrowser

from flask import Flask, request, jsonify, render_template_string
from shapely.geometry import shape, Point, GeometryCollection
from shapely.ops import transform
from pyproj import Transformer
import folium
from folium.plugins import Draw

# ==================================================
MAP_FILE = "map.html"
FILTERED_FILE = "filtered.json"

ORIGINAL_GEOJSON = None
CURRENT_GEOJSON = None  # contiene dati filtrati

app = Flask(__name__)

transformer = Transformer.from_crs(
    "EPSG:4326", "EPSG:3857", always_xy=True
).transform

# ==================================================
def get_color(lower, vref):
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

# ==================================================
def filter_by_circle(geojson, lat, lon, radius_m):
    center = Point(lon, lat)
    center_m = transform(transformer, center)
    search_area = center_m.buffer(radius_m)
    filtered = []
    for feature in geojson["features"]:
        for geom in feature["geometry"]:
            polygon = shape(geom["horizontalProjection"])
            polygon_m = transform(transformer, polygon)
            if polygon_m.intersects(search_area):
                # Rimuovo 'applicability' dalla feature
                feature_copy = feature.copy()
                feature_copy.pop("applicability", None)
                filtered.append(feature_copy)
                break
    return {**geojson, "features": filtered}


# ==================================================
def generate_map_html(geojson):
    zones = []
    shapes = []

    for feature in geojson["features"]:
        name = feature.get("name", "Unnamed zone")
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

    if not shapes:
        raise RuntimeError("Nessuna geometria valida trovata")

    centroid = GeometryCollection(shapes).centroid
    zones.sort(key=lambda z: z["lower"], reverse=True)

    m = folium.Map(location=[centroid.y, centroid.x], zoom_start=7, tiles="OpenStreetMap")

    # Disegna le zone
    for z in zones:
        color = get_color(z["lower"], z["vref"])
        folium.GeoJson(
            z["geometry"],
            style_function=lambda x, c=color: {
                "color": c,
                "fillColor": c,
                "weight": 2,
                "fillOpacity": 0.45
            },
            tooltip=f"{z['name']} – Lower {z['lower']} {z['vref']}"
        ).add_to(m)

    # Draw plugin: solo cerchio
    draw = Draw(
        draw_options={
            "circle": True,
            "polygon": False,
            "rectangle": False,
            "polyline": False,
            "marker": False,
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
            #save-btn, #reset-btn {{
                position: absolute;
                top: 10px;
                left: 10px;
                z-index: 9999;
                background: white;
                padding: 6px 10px;
                border: 1px solid gray;
                cursor: pointer;
                font-weight: bold;
                margin-right: 5px;
            }}
            #reset-btn {{
                left: 80px; /* sposta leggermente a destra del save */
            }}
        </style>
    </head>
    <body>
        <div id="save-btn">💾 Save</div>
        <div id="reset-btn">🔄 Reset</div>
        {map_html}
        <script>
            let drawnCircle = null;
            const map = window.{m.get_name()};
            
            map.on(L.Draw.Event.CREATED, function(e) {{
                if (drawnCircle) map.removeLayer(drawnCircle);
                drawnCircle = e.layer;
                map.addLayer(drawnCircle);
            }});

            document.getElementById('save-btn').onclick = function() {{
                if (!drawnCircle) {{
                    alert('Disegna prima un cerchio!');
                    return;
                }}
                const center = drawnCircle.getLatLng();
                const radius = drawnCircle.getRadius();
                fetch("/filter", {{
                    method: "POST",
                    headers: {{ "Content-Type": "application/json" }},
                    body: JSON.stringify({{ lat: center.lat, lon: center.lng, radius: radius }})
                }}).then(() => window.location.reload());
            }};

            document.getElementById('reset-btn').onclick = function() {{
                fetch("/reset", {{ method: "POST" }}).then(() => window.location.reload());
            }};
        </script>
    </body>
    </html>
    """
    return full_html

# ==================================================
@app.route("/")
def index():
    global CURRENT_GEOJSON
    return generate_map_html(CURRENT_GEOJSON if CURRENT_GEOJSON else ORIGINAL_GEOJSON)

@app.route("/filter", methods=["POST"])
def filter_route():
    global CURRENT_GEOJSON
    data = request.json
    CURRENT_GEOJSON = filter_by_circle(
        ORIGINAL_GEOJSON,
        data["lat"],
        data["lon"],
        data["radius"]
    )
    with open(FILTERED_FILE, "w", encoding="utf-8") as f:
        json.dump(CURRENT_GEOJSON, f, indent=2, ensure_ascii=False)
    return jsonify({"status": "ok"})

@app.route("/reset", methods=["POST"])
def reset_route():
    global CURRENT_GEOJSON
    CURRENT_GEOJSON = None
    return jsonify({"status": "ok"})

# ==================================================
def main():
    global ORIGINAL_GEOJSON
    parser = argparse.ArgumentParser()
    parser.add_argument("file", help="GeoJSON UAS file")
    args = parser.parse_args()

    with open(args.file, "r", encoding="utf-8-sig") as f:
        ORIGINAL_GEOJSON = json.load(f)

    url = "http://127.0.0.1:5000"
    threading.Timer(1.0, lambda: webbrowser.open(url, new=1)).start()

    app.run(debug=False, use_reloader=False)

if __name__ == "__main__":
    main()
