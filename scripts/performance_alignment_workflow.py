import json
import os
import requests
import subprocess
import sys
import csv
import io
from pathlib import Path

from .convert_to_rdf import maps_result_to_graph, performance_to_graph
from .mei_to_midi import mei_to_midi
from .midi_to_mp3 import midi_to_mp3
from . import verovio_midi
from .smat_align import smat_align
from .trompa_align import generate_maps_result_json


def validate_alignment_outputs(r_output_path, py_output_path):
    """Validate that R and Python alignment outputs match.

    Args:
        r_output_path (str): Path to the R version output JSON file
        py_output_path (str): Path to the Python version output JSON file

    Raises:
        Exception: If the outputs differ in any way
    """
    with open(r_output_path, "r") as f:
        r_data = json.load(f)
    with open(py_output_path, "r") as f:
        py_data = json.load(f)

    # Sort both lists by obs_num for consistent comparison
    r_data_sorted = sorted(r_data, key=lambda x: x["obs_num"])
    py_data_sorted = sorted(py_data, key=lambda x: x["obs_num"])

    if r_data_sorted != py_data_sorted:
        print("ERROR: R and Python outputs differ!")
        print("R output length:", len(r_data_sorted))
        print("Python output length:", len(py_data_sorted))

        # Find the first difference
        for i, (r_item, py_item) in enumerate(zip(r_data_sorted, py_data_sorted)):
            if r_item != py_item:
                print(f"First difference at index {i}:")
                print("R output:", r_item)
                print("Python output:", py_item)
                break

        raise Exception("R and Python implementations produced different outputs")

    print("** Verification successful: R and Python outputs match")


def perform_workflow(
    performance_midi,
    mei_file,
    expansion,
    mei_uri,
    score_uri,
    performance_container,
    timeline_container,
    audio_container,
    tempdir,
    perf_fname,
    audio_fname,
):
    """Do an alignment of a performance vs the score

    :param performance_midi: path to midi file of the performance
    :param mei_file: path to mei file
    :param expansion: which expansion to perform (None for all, or a specific number)
    :param mei_uri: url of the external MEI file which is being performed
    :param score_uri: URL of the score URL describing the score
    :param performance_container: Location of a container in user's solid pod, where data for this performance will be
    :param timeline_container: Location of a container in the user's pod where the timeline will be
    :param audio_container: Location of a container in the user's pod where the audio will be
    :param tempdir: temporary working directory to put files
    :param perf_fname: basename of the resource in performance_container
    :param audio_fname: basename of the resource in audio_container
    :return:
    """
    if mei_file is not None:
        with open(mei_file, 'r') as f:
            mei_data = f.read()
    else:
        resp = requests.get(mei_uri)
        mei_data = resp.text
        with open(os.path.join(tempdir, "score.mei"), 'w') as out:
            out.write(mei_data)
        mei_file = os.path.join(tempdir, "score.mei")
    print("** Performing MEI_TO_MIDI")
    mei_to_midi(mei_data, os.path.join(tempdir, "canonical.mid"), expansion)

    print("** Performing SMAT_ALIGN")
    print("performance_midi: ", performance_midi)
    corresp = smat_align(os.path.join(tempdir, "canonical.mid"), performance_midi)

    # Save corresp to file for R version
    with open(os.path.join(tempdir, "corresp.txt"), "w") as out:
        out.write(corresp)

    allNotes = verovio_midi.generate_notes_from_mei(mei_file, None)
    verovio_json_notes = os.path.join(tempdir, "verovio_note_positions.json")
    with open(verovio_json_notes, "w") as fp:
        json.dump(allNotes, fp)

    print("** Performing RECONCILIATION")

    # Run R version
    r_output = os.path.join(tempdir, "maps_r.json")
    subprocess.run(
        [
            "Rscript",
            os.path.join(os.path.dirname(__file__), "trompa-align.R"),
            os.path.join(tempdir, "corresp.txt"),
            r_output,
            verovio_json_notes,
        ]
    )

    # Run Python version
    py_output = os.path.join(tempdir, "maps_py.json")
    generate_maps_result_json(corresp, allNotes, py_output)

    # Validate outputs
    validate_alignment_outputs(r_output, py_output)

    # Use the Python output as the final result
    os.rename(py_output, os.path.join(tempdir, "maps.json"))

    print("** Performing AUDIO SYNTHESIS")
    midi_to_mp3(performance_midi, os.path.join(tempdir, audio_fname), tempdir)
    print(
        "** Success: Created synthesised audio output: ",
        os.path.join(tempdir, audio_fname),
    )

    print("** Performing RDF CONVERSION")
    with open(os.path.join(tempdir, "maps.json"), "rb") as f:
        maps_json = f.read()

    audio_uri = os.path.join(audio_container, audio_fname)
    performance_uri = os.path.join(performance_container, perf_fname)
    timeline_uri = os.path.join(timeline_container, perf_fname)

    timeline_graph = maps_result_to_graph(
        maps_json, mei_uri, timeline_uri, score_uri, audio_uri, includePerformance=False
    )

    performance_graph = performance_to_graph(
        performance_uri, timeline_uri, score_uri, audio_uri
    )
    print("** Success: Created timeline output: ", perf_fname)
    return performance_graph, timeline_graph
