import os, sys, argparse, csv, uuid, requests, json, tempfile, pathlib
from smat_align import smat_align
from mei_to_midi import mei_to_midi
import subprocess

def batch_process(midi_files, mei_uri, expansion, outdir, tempdir):
    # fetch MEI
    resp = requests.get(mei_uri)
    mei_data = resp.text
    mei_file = os.path.join(tempdir, "score.mei")
    canonical_midi_file = os.path.join(tempdir, "canonical.mid")
    with open(mei_file, 'w') as out:
        out.write(mei_data)

    mei_to_midi(mei_data, canonical_midi_file, expansion)
    print("**GENERATED CANONICAL MIDI")
    [process(performance_midi_file, canonical_midi_file, mei_uri, expansion, outdir, tempdir) for performance_midi_file in midi_files]

def process(midi, canonical, mei_uri, expansion, outdir, tempdir):
    print("**PROCESSING ", midi)
    corresp_file = os.path.join(tempdir, midi.name) + ".corresp"
    try: 
        corresp = smat_align(canonical, midi)
        print("**Finished SMAT align")
        with open(corresp_file, 'w') as out:
            out.write(corresp)
        print("Running R...", corresp_file, os.path.join(outdir, midi.name) + ".maps.json", mei_uri)
        subprocess.run([
            "Rscript",
            os.path.join(sys.path[0], "trompa-align-local.R"), 
            corresp_file,
            os.path.join(outdir, midi.name) + ".maps.json",
            mei_uri,
            expansion or ""
        ])
    except:
        print("!!!!! Could not process ", midi, " -- skipping")



if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--performancedir', help="Directory containing performance MIDI files", required=True)
    parser.add_argument('-m', '--meiuri', help="URI of MEI file being performed", required=True)
    parser.add_argument('-o', '--outputdir', help="Directory to which output maps.json should be written", required=True)
    parser.add_argument('-e', '--expansion', help="Verovio expansion option", required=False)
    args = parser.parse_args()
    tempdir = tempfile.mkdtemp()
    print("Tempdir: ", tempdir)
    midi_files = [path for path in pathlib.Path(args.performancedir).rglob('*.mid')]
    batch_process(midi_files, args.meiuri, args.expansion, args.outputdir, tempdir)

    

    


