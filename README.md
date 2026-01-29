# UAS Zone GeoJSON Filter and Mapper

This project addresses the need to select a limited number of UAS zones starting from the file distributed by the National Civil Aviation Authority.

The project contains two Python programs:

* **`filter_geojson.py`**: starting from the complete JSON file, selects the UAS zones that are located near a given point and within a specified radius. It creates a file containing the filtered UAS zones.
* **`map_geojson.py`**: displays the result of the selection operation on a map. It creates a map.htm file thatcan be browsed
* **`filter_map_geojson.py`**: starting from the complete JSON file, selects the UAS zones that are located near a given point and within a specified radius. It creates a file containing the filtered UAS zones and a map.htm file that can be browsed.
* **`interactive_uas_filter.py`**: allows to select on an interactive map the area to be extracted.
* **`compare.py`**: compares two files containing UAS zones, showing the differences.


## Usage

1. Set up a Python environment.
2. Install the dependencies listed in `requirements.txt`.
3. Run the scripts.

## `filter_geojson.py`

This script requires as input:

* the name of the file distributed by the national authority,
* the coordinates of the reference point,
* the search radius (in kilometers).

### Example

```bash
python filter_geojson.py ita_zones.json "45 27 55N" "9 11 20E" 30
```

This command selects the UAS zones within 30 km of the center of Milan.

The output file generated is:

```
filtered.json
```

## `map_geojson.py`

This script plots the zones included in `filtered.json` on an interactive map, generating the file:

```
map.html
```
## `filter_map_geojson.py`

This script requires as input:

* the name of the file distributed by the national authority,
* the coordinates of the reference point,
* the search radius (in kilometers).

It generates two output files:

```
filtered.json
```
and

```
map.html
```

### Example

```bash
python filter_map_geojson.py ita_zones.json "45 27 55N" "9 11 20E" 30
```

This command selects the UAS zones within 30 km of the center of Milan and generates the filterend json output and the map file.

## `interactive_uas_filter.py`

This script requires as input:

* the name of the file distributed by the national authority

### Example

```bash
python interactive_uas_filter.py ita_zones.json
```

It opens a browser showing an interactive map of all the UAS zones included into the JSON file. A button on the left side allows to start drawing a circle, selecting a point and drawing the radius. After drawing the circle, the button Save creates the filtered.json file with the UAS zones intersecting the circle. The map is updated, showing these zones. The Reset button allows to relaoad the initial map and to draw a different circle. The Quit button closes the browser and the script.

The output file generated is:

```
filtered.json
```

## `compare.py`

This script requires as input:

* the name of two json files containing UAS zones

### Example

```bash
python compare.py ita_zones.json filtered.json
```

it show the difference between the files: the features included in one file and missing in the other one.
