import os, sys, argparse, csv, uuid, requests, json
from mei_to_midi import mei_to_midi
from midi_to_mp3 import midi_to_mp3 
from smat_align import smat_align
from convert_to_rdf import maps_result_to_graph, graph_to_jsonld
import subprocess

# TODO UPDATE CLI in align-directly.ini line 24

PYTHON_VERSION = "python3"

def perform_workflow_split_1(performance_midi, canonical_midi, mei_file, mei_uri, structure_uri, webid, tempdir, audio_fname): 
    print("** Performing SMAT_ALIGN")
    corresp = smat_align(canonical_midi, performance_midi)
    with open(os.path.join(tempdir, "corresp.txt"), 'w') as out:
        out.write(corresp)

    print("** Performing RECONCILIATION")
    subprocess.run([
        "Rscript",
        os.path.join(sys.path[0], "trompa-align.R"), 
        os.path.join(tempdir, "corresp.txt"), 
        os.path.join(tempdir, "maps.json"),
        mei_file
    ])

    print("** Performing AUDIO SYNTHESIS")
    midi_to_mp3(performance_midi, audio_fname, tempdir)
    print("** Success: Created synthesised audio output: ", audio_fname)

