import os, sys, shutil
from midi_to_mp3 import midi_to_mp3
from smat_align import smat_align
import subprocess

# TODO UPDATE CLI in align-directly.ini line 24

PYTHON_VERSION = "python3"

def perform_workflow_split_1(performance_midi, canonical_midi, mei_file, tempdir, audio_fname, maps_fname):
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
    shutil.copyfile(os.path.join(tempdir, "maps.json"), maps_fname)
    print("** Performing AUDIO SYNTHESIS")
    midi_to_mp3(performance_midi, audio_fname, tempdir)
    print("** Success: Created synthesised audio output: ", audio_fname)

