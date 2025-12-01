#!/usr/bin/env python3

import json
import csv
import io
from collections import defaultdict


def generate_maps_result_json(corresp_string, attrs, output_file, threshold=5):
    """Generate a MAPS result object from a corresp string.

    Args:
        corresp_string (str): The corresp data as a TSV string
        attrs (dict): The Verovio notes data
        output_file (str): Path to write the output JSON file
        threshold (int): Alignment threshold in milliseconds (default=5)
    """
    # Process corresp string
    corresp_string = corresp_string.replace("*", "-1")
    corresp_reader = csv.reader(io.StringIO(corresp_string), delimiter="\t")
    next(corresp_reader)  # Skip header

    # Convert to list of dictionaries
    corresp = []
    for row in corresp_reader:
        if len(row) >= 10:  # Ensure we have enough columns
            corresp.append(
                {
                    "alignID": row[0],
                    "alignOntime": float(row[1]),
                    "alignSitch": row[2],
                    "alignPitch": int(row[3]),
                    "alignOnvel": int(row[4]),
                    "refID": row[5],
                    "refOntime": float(row[6]),
                    "refSitch": row[7],
                    "refPitch": int(row[8]),
                    "refOnvel": int(row[9]),
                    "tstamp": float(row[6]) * 1000,  # Convert to milliseconds
                }
            )

    # Separate inserted notes
    inserted_notes = [note for note in corresp if note["refID"] == "-1"]
    print(f"Inserted notes detected: {len(inserted_notes)}")

    # Get SMAT aligned notes
    smat_aligned_notes = [note for note in corresp if note["refID"] != "-1"]

    # Convert attrs to list of dictionaries for easier manipulation
    attrs_list = attrs if isinstance(attrs, list) else [attrs]

    # Index attributes by MIDI pitch to avoid scanning the entire list each time
    attrs_by_pitch = defaultdict(list)
    for attr in attrs_list:
        pitch = attr.get("midiPitch")
        if pitch is None or attr.get("tstamp") is None or attr.get("id") is None:
            continue
        attrs_by_pitch[pitch].append(attr)

    # Build candidate matches (equivalent to difference_inner_join + pitch filter)
    candidate_matches = []
    for note in smat_aligned_notes:
        for attr in attrs_by_pitch.get(note["refPitch"], []):
            dist = abs(note["tstamp"] - attr["tstamp"])
            if dist <= threshold:
                combined = {**note, **attr}
                combined["dist"] = dist
                candidate_matches.append(combined)

    # Choose the closest candidate for each MEI note id
    matched = {}
    for candidate in candidate_matches:
        mei_id = candidate["id"]
        if mei_id not in matched or candidate["dist"] < matched[mei_id]["dist"]:
            matched[mei_id] = candidate

    # Find non-reconciled notes
    matched_ref_ids = {note["refID"] for note in matched.values()}
    non_reconciled = [note for note in smat_aligned_notes if note["refID"] not in matched_ref_ids]
    print(f"{len(non_reconciled)} match failures.")

    # Prepare MAPS export
    grouped_by_onset = {}
    for note in sorted(matched.values(), key=lambda n: (n["alignOntime"], n["dist"], n["id"])):
        onset = note["alignOntime"]
        entry = grouped_by_onset.setdefault(
            onset, {"obs_mean_onset": onset, "xml_id": [], "velocity": [], "confidence": 0}
        )
        entry["xml_id"].append(note["id"])
        entry["velocity"].append(note["alignOnvel"])

    maps_export = sorted(grouped_by_onset.values(), key=lambda item: item["obs_mean_onset"])

    # Add inserted notes (these remain scalar fields, matching the R script)
    for note in inserted_notes:
        maps_export.append(
            {
                "obs_mean_onset": note["alignOntime"],
                "xml_id": f"trompa-align_inserted_{note['alignSitch'].replace('#', 's')}",
                "velocity": note["alignOnvel"],
                "confidence": 0,
            }
        )

    # Add observation numbers
    for i, note in enumerate(maps_export, 1):
        note["obs_num"] = i

    # Write to JSON file
    with open(output_file, "w") as f:
        json.dump(maps_export, f)

    print(f"MAPS file written: {output_file}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 4 or len(sys.argv) > 5:
        print(
            "Invoke as: python trompa-align.py $CORRESP_FILE $OUTPUT_FILE $VEROVIO_NOTES_JSON {threshold-in-ms (default=5)}"
        )
        sys.exit(1)

    corresp_file = sys.argv[1]
    output_file = sys.argv[2]
    verovio_notes_json_file = sys.argv[3]
    threshold = 5 if len(sys.argv) == 4 else float(sys.argv[4])

    # Read corresp file
    with open(corresp_file, "r") as f:
        corresp_string = f.read()

    # Read Verovio JSON
    with open(verovio_notes_json_file, "r") as f:
        attrs = json.load(f)

    # Generate MAPS result
    generate_maps_result_json(corresp_string, attrs, output_file, threshold)
