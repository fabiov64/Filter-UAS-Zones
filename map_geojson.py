import json
import folium
from shapely.geometry import shape, GeometryCollection

INPUT_FILE = "filtered.json"   # <-- tuo file GeoJSON
OUTPUT_FILE = "map.html"


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


# Carica GeoJSON
with open(INPUT_FILE, "r", encoding="utf-8") as f:
    data = json.load(f)

zones = []

# Estrai tutte le zone
for feature in data["features"]:
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

# Ordina: prima le più alte, poi le più basse (le basse prevalgono)
zones.sort(key=lambda z: z["lower"], reverse=True)

# Centro mappa
shapes = [shape(z["geometry"]) for z in zones]
centroid = GeometryCollection(shapes).centroid

m = folium.Map(
    location=[centroid.y, centroid.x],
    zoom_start=10,
    tiles="OpenStreetMap"
)

# Disegno zone
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

# Salva mappa
m.save(OUTPUT_FILE)
print(f"Mappa generata: {OUTPUT_FILE}")
