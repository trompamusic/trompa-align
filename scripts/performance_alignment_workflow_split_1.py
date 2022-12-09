import json
import os
import subprocess
import sys

import verovio_midi
from midi_to_mp3 import midi_to_mp3
from smat_align import smat_align


def perform_workflow_split_1(performance_midi, canonical_midi, mei_file, tempdir, audio_fname, maps_fname):
    print("** Performing SMAT_ALIGN")
    corresp = smat_align(canonical_midi, performance_midi)
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
        maps_fname,
        verovio_json_notes,
    ])

    print("** Performing AUDIO SYNTHESIS")
    midi_to_mp3(performance_midi, audio_fname, tempdir)
    print("** Success: Created synthesised audio output: ", audio_fname)
