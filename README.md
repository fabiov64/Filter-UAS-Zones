# UAS Zone GeoJSON Filter and Mapper

This project addresses the need to select a limited number of UAS zones starting from the file distributed by the National Civil Aviation Authority.

The project contains two Python programs:

- **`filter_geojson.py`**: starting from the complete JSON file, selects the UAS zones that are located near a given point and within a specified radius.
- **`map_geojson.py`**: displays the result of the selection operation on a map.

## Usage

1. Set up a Python environment.
2. Install the dependencies listed in `requirements.txt`.
3. Run the scripts.

### `filter_geojson.py`

This script requires as input:
- the name of the file distributed by the national authority,
- the coordinates of the reference point,
- the search radius (in kilometers).

#### Example

```bash
python filter_geojson.py ita_zones.json "45°27'55\"" "9°11'20\"" 30
