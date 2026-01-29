#!/usr/bin/env python3
import json
import argparse

def load_identifiers(file_path):
    """Carica tutti gli identifier dal file ED-269"""
    with open(file_path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    features = data.get("features", [])
    identifiers = set()
    for f in features:
        ident = f.get("identifier")
        if ident:
            identifiers.add(ident)
    return identifiers

def main(file1, file2):
    ids1 = load_identifiers(file1)
    ids2 = load_identifiers(file2)

    only_in_file1 = ids1 - ids2
    only_in_file2 = ids2 - ids1

    print(f"Feature presenti solo in {file1} ({len(only_in_file1)}):")
    for ident in sorted(only_in_file1):
        print(f"  {ident}")

    print(f"\nFeature presenti solo in {file2} ({len(only_in_file2)}):")
    for ident in sorted(only_in_file2):
        print(f"  {ident}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Confronta due file ED-269 e identifica feature mancanti")
    parser.add_argument("file1", help="Primo file ED-269 JSON")
    parser.add_argument("file2", help="Secondo file ED-269 JSON")
    args = parser.parse_args()

    main(args.file1, args.file2)

