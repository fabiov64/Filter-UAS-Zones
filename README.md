# UAS Zone GeoJSON Filter and Mapper

A collection of Python tools for filtering and visualising **Unmanned Aircraft System (UAS) restriction zones** from national authority GeoJSON files (ED-269 format).

---

## Overview

National civil aviation authorities distribute UAS zone datasets that can contain thousands of zones covering an entire country. These tools let you extract only the zones relevant to a specific location and visualise them on an interactive map.

### Included Scripts

| Script | Description |
|---|---|
| [`filter_geojson.py`](#filter_geojsonpy) | Filter zones by location + radius → `filtered.json` |
| [`map_geojson.py`](#map_geojsonpy) | Render `filtered.json` as an interactive HTML map |
| [`filter_map_geojson.py`](#filter_map_geojsonpy) | Filter + map in a single step |
| [`interactive_uas_filter.py`](#interactive_uas_filterpy) | Draw a circle on a live map to filter interactively (CLI) |
| [`MacOS Application/interactive_uas_filter (app).py`](#macos-application) | Same as above but packaged as a macOS .app (native file dialog) |
| [`compare.py`](#comparepy) | Diff two ED-269 files by zone identifier |

---

## Requirements

| Package | Version |
|---|---|
| Flask | 3.1.2 |
| folium | 0.20.0 |
| pyproj | 3.7.2 |
| Shapely | 2.1.2 |

Install all dependencies:

```bash
pip install -r requirements.txt
```

---

## Colour Legend

All map scripts use the same altitude-based colour scheme:

| Colour | Lower limit | Vertical ref | Meaning |
|---|---|---|---|
| Red | 0 | AGL | Ground-level restriction (most restrictive) |
| Orange | 25 | any | 25 m/ft floor |
| Yellow | 45 | any | 45 m/ft floor |
| Light-blue | 60 | any | 60 m/ft floor |
| Purple | other | any | Non-standard altitude |

Zones are drawn from highest to lowest so that more restrictive (lower) zones appear on top.

---

## filter_geojson.py

Reads a full national UAS GeoJSON file, keeps only the zones whose polygon centroid falls within a given geodetic radius from a reference point, and writes the result to `filtered.json`.

### Usage

```bash
python filter_geojson.py <file> <latitude_dms> <longitude_dms> <radius_km>
```

### Arguments

| Argument | Description |
|---|---|
| `file` | Path to the input ED-269 GeoJSON file |
| `latitude_dms` | Reference latitude in DMS notation |
| `longitude_dms` | Reference longitude in DMS notation |
| `radius_km` | Search radius in kilometres |

### DMS Coordinate Format

Coordinates can be written in any of these equivalent forms:

```
45°50'34"N
45 50 34 N
45°50'34"
```

### Example

```bash
python filter_geojson.py ita_zones.json "45 27 55N" "9 11 20E" 30
```

Selects all UAS zones within 30 km of the centre of Milan.

### Output

```
filtered.json   (written in the current working directory)
```

The output file preserves all ED-269 metadata. Two fields are updated:
- `title` — the suffix `" - cropped"` is appended.
- `description` — updated with zone counts: `GeoZones[N] - ATM09[N]/NFZ[N]/NOTAM[N]`.

### How the filter works

For each feature in the input file the script iterates over its `geometry` array.  The feature is included in the output as soon as **any single geometry's centroid** is within the search radius.  Distance is measured on the **WGS-84 ellipsoid** using `pyproj.Geod`, giving accurate results at all latitudes.

---

## map_geojson.py

Reads `filtered.json` (the output of `filter_geojson.py`) and generates an interactive HTML map using [Folium](https://python-visualization.github.io/folium/) / Leaflet.js.

### Usage

```bash
python map_geojson.py
```

The input and output filenames are hard-coded at the top of the script (`INPUT_FILE` / `OUTPUT_FILE`). Edit them there if needed.

### Output

```
map.html    (interactive Leaflet map, open in any browser)
```

### Map features

- Each UAS zone is rendered as a semi-transparent filled polygon.
- **Hover** over a zone to see its name and lower altitude limit.
- **Click** a zone for a popup with full altitude range (lower + upper limit).
- Zones with lower limits are drawn on top of higher-floor zones.

---

## filter_map_geojson.py

Combines the filter and map steps into one command. Equivalent to running `filter_geojson.py` followed by `map_geojson.py`.

### Usage

```bash
python filter_map_geojson.py <file> <latitude_dms> <longitude_dms> <radius_km>
```

### Arguments

Same as `filter_geojson.py`.

### Example

```bash
python filter_map_geojson.py ita_zones.json "45 27 55N" "9 11 20E" 30
```

### Output

```
filtered.json   (zones within the search radius)
map.html        (interactive map of those zones)
```

---

## interactive_uas_filter.py

Starts a local web server and opens a browser with an interactive map of **all** zones in the input file. The user draws a circle on the map to define the search area and clicks **Save** to produce `filtered.json`.

### Usage

```bash
python interactive_uas_filter.py <file>
```

### Workflow

1. Run the script with your GeoJSON file.
2. The browser opens automatically at `http://127.0.0.1:5000`.
3. Click the **circle draw tool** in the left toolbar.
4. Click on the map to set the centre, then drag to set the radius.
5. Click **💾 Save** — `filtered.json` is written and the map reloads showing only the filtered zones.
6. Click **🔄 Reset** to discard the filter and return to the full map.
7. Click **❌ Quit** to shut down the server.

### Output

```
filtered.json   (written in the current working directory)
```

### Flask API endpoints

| Method | Route | Description |
|---|---|---|
| GET | `/` | Serve the interactive map HTML |
| POST | `/filter` | Apply circle filter; body: `{"lat", "lon", "radius"}` (metres) |
| POST | `/reset` | Clear the current filter |
| POST | `/quit` | Gracefully terminate the Flask server |

---

## MacOS Application

`MacOS Application/interactive_uas_filter (app).py` is the macOS-specific variant of `interactive_uas_filter.py`, packaged as a `.app` bundle.

### Differences from the CLI version

| Feature | CLI version | macOS app version |
|---|---|---|
| File selection | Command-line argument | Native macOS Open File dialog (via AppleScript) |
| Output location | Current working directory | Same directory as the input file |
| Quit behaviour | SIGINT only | AppleScript ⌘W closes browser, then SIGINT |

### Usage

Double-click the `.app` bundle in Finder, or run the script directly:

```bash
python "interactive_uas_filter (app).py"
```

A native file picker will appear. Select your ED-269 JSON file to proceed.

### Pre-built binaries

Ready-to-run macOS binaries (no Python installation required) are available in `MacOs binaries/`:

| Binary | Description |
|---|---|
| `filter_geojson` | CLI filter tool |
| `filter_map_geojson` | CLI filter + map tool |
| `map_geojson` | CLI map renderer |
| `interactive_uas_filter` | Interactive filter (CLI) |

---

## compare.py

Compares the zone identifiers between two ED-269 GeoJSON files and prints the symmetric difference — zones present in one file but absent in the other.

### Usage

```bash
python compare.py <file1> <file2>
```

### Example

```bash
python compare.py ita_zones.json filtered.json
```

### Example output

```
Features only in ita_zones.json (1423):
  ITA-001
  ITA-002
  ...

Features only in filtered.json (0):
```

### Use cases

- Verify that a filtered subset contains only zones from the master file.
- Detect additions or removals between two versions of the same national dataset.
- Audit that no zones were accidentally dropped or duplicated during processing.

---

## Data Format

All scripts expect the input to be an **ED-269** UAS zone GeoJSON file as distributed by national civil aviation authorities (e.g. ENAC in Italy).

Each feature in the file is expected to have:

```json
{
  "identifier": "ITA-XXXX",
  "name": "Zone Name",
  "otherReasonInfo": "ATM09",
  "geometry": [
    {
      "horizontalProjection": { "type": "Polygon", "coordinates": [...] },
      "lowerLimit": 0,
      "lowerVerticalReference": "AGL",
      "upperLimit": 120,
      "upperVerticalReference": "AGL"
    }
  ],
  "applicability": [
    {
      "startDateTime": "2024-01-01T00:00:00+00:00",
      "endDateTime":   "2024-12-31T23:59:59+00:00"
    }
  ]
}
```

`otherReasonInfo` values counted in zone statistics:

| Value | Meaning |
|---|---|
| `ATM09` | Air Traffic Management restriction |
| `NFZ` | No-Fly Zone |
| `NOTAM` | Notice to Airmen |

---

## Architecture Notes

### Geodetic distance

All spatial filtering uses `pyproj.Geod(ellps="WGS84").inv()` to compute great-circle distance on the WGS-84 ellipsoid.  This gives accurate results regardless of latitude and avoids the distortion that flat-Earth (projected) distance measurements introduce at high latitudes or over large radii.

### Geometry validity

Before computing a centroid, each polygon is checked with Shapely's `is_valid`.  Invalid geometries (e.g. self-intersecting rings) are repaired with `.buffer(0)` so they do not cause errors or incorrect results.

### Timestamp normalisation

Some authority files use the `Z` suffix for UTC timestamps (`2024-01-01T00:00:00Z`).  All scripts normalise these to `+00:00` to ensure strict ISO-8601 compliance and compatibility with downstream parsers.
