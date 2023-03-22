import json
import os
import requests
import subprocess
import sys

from .convert_to_rdf import maps_result_to_graph, graph_to_jsonld
from .mei_to_midi import mei_to_midi
from .midi_to_mp3 import midi_to_mp3
from . import verovio_midi
from .smat_align import smat_align


def perform_workflow(performance_midi, mei_file, expansion, mei_uri, structure_uri, performance_container,
                     audio_container, tempdir, perf_fname, audio_fname):
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

    allNotes = verovio_midi.generate_notes_from_mei(mei_file, None)
    verovio_json_notes = os.path.join(tempdir, "verovio_note_positions.json")
    with open(verovio_json_notes, "w") as fp:
        json.dump(allNotes, fp)

    print("** Performing RECONCILIATION")
    subprocess.run([
        "Rscript",
        os.path.join(sys.path[0], "trompa-align.R"),
        os.path.join(tempdir, "corresp.txt"),
        os.path.join(tempdir, "maps.json"),
        verovio_json_notes,
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
