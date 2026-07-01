#!/usr/bin/env python3
"""
compare.py — UAS GeoJSON File Comparator

Compares two ED-269 UAS zone GeoJSON files and reports which zone identifiers
are present in one file but missing in the other.  Useful for verifying that
a filtered subset is consistent with a master dataset, or for detecting
additions / removals between two versions of the same national authority file.

Usage::

    python compare.py <file1> <file2>

Example::

    python compare.py ita_zones.json filtered.json

Output (printed to stdout):
    Two sections listing zone identifiers that appear exclusively in each file.
    Identifiers are sorted alphabetically for easy visual scanning.
"""

import json
import argparse


# ------------------------------------------------------------------
def load_identifiers(file_path: str) -> set:
    """Load all zone ``identifier`` values from an ED-269 GeoJSON file.

    Args:
        file_path: Path to the GeoJSON file to read.

    Returns:
        Set of identifier strings found across all features in the file.
        Features without an ``identifier`` key are silently skipped.
    """
    with open(file_path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

    features    = data.get("features", [])
    identifiers = set()

    for f in features:
        ident = f.get("identifier")
        if ident:
            identifiers.add(ident)

    return identifiers


# ------------------------------------------------------------------
def main(file1: str, file2: str) -> None:
    """Compare identifiers between two GeoJSON files and print the diff.

    Performs a symmetric set difference: zones only in *file1* and zones only
    in *file2* are printed in separate sections.

    Args:
        file1: Path to the first GeoJSON file.
        file2: Path to the second GeoJSON file.
    """
    ids1 = load_identifiers(file1)
    ids2 = load_identifiers(file2)

    only_in_file1 = ids1 - ids2  # present in file1, absent in file2
    only_in_file2 = ids2 - ids1  # present in file2, absent in file1

    print(f"Features only in {file1} ({len(only_in_file1)}):")
    for ident in sorted(only_in_file1):
        print(f"  {ident}")

    print(f"\nFeatures only in {file2} ({len(only_in_file2)}):")
    for ident in sorted(only_in_file2):
        print(f"  {ident}")


# ------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Compare two ED-269 GeoJSON files and list missing features"
    )
    parser.add_argument("file1", help="First ED-269 JSON file")
    parser.add_argument("file2", help="Second ED-269 JSON file")
    args = parser.parse_args()

    main(args.file1, args.file2)
