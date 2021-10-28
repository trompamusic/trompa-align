import os, sys, argparse, csv, uuid, requests, json
from mei_to_midi import mei_to_midi
from midi_to_mp3 import midi_to_mp3 
from smat_align import smat_align
from convert_to_rdf import maps_result_to_graph, graph_to_jsonld
import subprocess

# TODO UPDATE CLI in align-directly.ini line 24

PYTHON_VERSION = "python3"

def perform_workflow(performance_midi, mei_file, expansion, mei_uri, structure_uri, performance_container, audio_container, webid, tempdir, perf_fname, audio_fname): 
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
    with open(os.path.join(tempdir, "corresp.txt"), 'w') as out:
        out.write(corresp)

    print("** Performing RECONCILIATION")
    exp = expansion if bool(expansion) else ""
    subprocess.run([
        "Rscript",
        os.path.join(sys.path[0], "trompa-align.R"), 
        os.path.join(tempdir, "corresp.txt"), 
        os.path.join(tempdir, "maps.json"),
        mei_file,
        exp
    ])

    print("** Performing AUDIO SYNTHESIS")
    midi_to_mp3(performance_midi, os.path.join(tempdir, audio_fname), tempdir)
    print("** Success: Created synthesised audio output: ", os.path.join(tempdir, audio_fname))

    print("** Performing RDF CONVERSION")
    with open(os.path.join(tempdir, "maps.json"), 'rb') as f:
        maps_json = f.read()
    g = maps_result_to_graph(
        maps_json, 
        structure_uri, 
        mei_uri, 
        os.path.join(performance_container, perf_fname),
        structure_uri,
        os.path.join(audio_container, audio_fname),
        True
    )
    jsonld = json.dumps(graph_to_jsonld(g, ''), indent=2)
    with open(os.path.join(tempdir, perf_fname), 'w') as json_file:
        json_file.write(jsonld)
    print("** Success: Created timeline output: ", os.path.join(tempdir, perf_fname))
