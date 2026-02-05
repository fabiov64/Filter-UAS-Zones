#!/usr/bin/env python3

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
geod = Geod(ellps="WGS84")

# ==================================================

FILTERED_FILE = "filtered.json"

ORIGINAL_GEOJSON = None
CURRENT_GEOJSON = None  # contiene dati filtrati

app = Flask(__name__)

# Trasformazione WGS84 -> Web Mercator per buffer in metri
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

def geometry_matches_search_geodetic(polygon, center_lat, center_lon, radius_m):
    try:
        # ripara geometrie
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
def filter_by_circle(geojson, lat, lon, radius_m):
    center = Point(lon, lat)
    center_m = transform(transformer, center)
    search_area = center_m.buffer(radius_m + 2)

    filtered = []

    for feature in geojson.get("features", []):
        for geom in feature.get("geometry", []):
            polygon = shape(geom["horizontalProjection"])
        
            if geometry_matches_search_geodetic(polygon, lat, lon, radius_m):
           
                feature_copy = feature.copy()

                # Normalizza startDateTime / endDateTime in applicability (Z -> +00:00)
                for app in feature_copy.get("applicability", []):
                    for key in ("startDateTime", "endDateTime"):
                       if key in app and isinstance(app[key], str) and app[key].endswith("Z"):
                          app[key] = app[key].replace("Z", "+00:00")


                filtered.append(feature_copy)

                break

    # ==================================================
    # Aggiornamento title e description
    geojson_copy = {
        **{k: v for k, v in geojson.items() if k != "features"},
        "features": filtered
    }

    # Aggiorna il title aggiungendo " - cropped"
    if "title" in geojson_copy:
        geojson_copy["title"] = geojson_copy["title"] + " - cropped"

    # Conta le features filtrate
    geozones_count = len(filtered)
    atm09_count = sum(
        1 for f in filtered if f.get("otherReasonInfo") == "ATM09"
    )
    nfz_count = sum(
        1 for f in filtered if f.get("otherReasonInfo") == "NFZ"
    )
    notam_count = sum(
        1 for f in filtered if f.get("otherReasonInfo") == "NOTAM"
    )

 
   # Aggiorna description
    if "description" in geojson_copy:
       # Prende solo il testo originale prima di eventuali vecchie info GeoZones
         desc_original = geojson_copy["description"].split(" - GeoZones")[0].strip()
         geojson_copy["description"] = (
           f"{desc_original} - cropped - GeoZones[{geozones_count}] - ATM09[{atm09_count}]/NFZ[{nfz_count}]/NOTAM[{notam_count}]"
       )

    return geojson_copy

# ==================================================
def generate_map_html(geojson):
    zones = []
    shapes = []

    for feature in geojson.get("features", []):
        name = feature.get("name", "Unnamed zone")
        for geom in feature.get("geometry", []):
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
            #save-btn {{ left: 50px; }}
            #reset-btn {{ left: 125px; }}
            #quit-btn {{ left: 205px; }}  /* spostato a destra per non coprire Reset */
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
            
            map.on(L.Draw.Event.CREATED, function(e) {{
                if (drawnCircle) map.removeLayer(drawnCircle);
                drawnCircle = e.layer;
                map.addLayer(drawnCircle);
            }});

                  
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

            document.getElementById('reset-btn').onclick = function() {{
                fetch("/reset", {{ method: "POST" }}).then(() => window.location.reload());
            }};

            document.getElementById('quit-btn').onclick = function() {{
                fetch("/quit", {{ method: "POST" }}).then(() => {{
                    alert('Click to close the browser ...');
                    window.close();  // chiude il browser
                }});
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
    filtered = filter_by_circle(
        ORIGINAL_GEOJSON,
        data["lat"],
        data["lon"],
        data["radius"]
    )

    # 🔴 Nessuna zona trovata
    if not filtered.get("features"):
        return jsonify({
            "status": "empty",
            "message": "No Zones to Save"
        }), 200

    CURRENT_GEOJSON = filtered

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
    global CURRENT_GEOJSON
    CURRENT_GEOJSON = None
    return jsonify({"status": "ok"})

@app.route("/quit", methods=["POST"])
def quit_route():
    # Chiude il server Flask e termina lo script
    def shutdown():
        os.kill(os.getpid(), signal.SIGINT)
    threading.Thread(target=shutdown).start()
    return jsonify({"status": "quitting"})

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

# ==================================================
if __name__ == "__main__":
    main()
