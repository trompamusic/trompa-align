import os, sys, argparse, csv, uuid, requests, json, tempfile, pathlib
from smat_align import smat_align
from write_expanded_mei_data import write_expanded_mei_data
from mei_to_midi import mei_to_midi
import subprocess

def batch_process(midi_files, mei_uri, expansions, outdir, tempdir):
    # fetch MEI
    resp = requests.get(mei_uri)
    mei_data = resp.text
    [process(performance_midi_file, mei_uri, expansions, outdir, tempdir, mei_data) for performance_midi_file in midi_files]

def process(midi, mei_uri, expansions, outdir, tempdir, mei_data):
    print("**PROCESSING ", midi)
    corresp_file = os.path.join(tempdir, midi.name) + ".corresp"
    fewest_inserted_notes = None
    best_expansion = None
    for expansion in expansions:
        print("attempting expansion: ", expansion)
        try: 
            mei_file = pathlib.Path(
                    outdir,
                    pathlib.Path(mei_uri).stem + "." + expansion + ".mei")
            canonical = pathlib.Path(tempdir, expansion + ".canonical.mid")
            if not mei_file.is_file():
                print("Writing expanded mei data")
                write_expanded_mei_data(mei_data, str(mei_file), expansion)
            if not canonical.is_file():
                print("Generating canonical MIDI")
                mei_to_midi(mei_data, str(canonical), expansion)
            corresp = smat_align(str(canonical), midi)
            with open(corresp_file, 'w') as out:
                out.write(corresp)
            maps_file = os.path.join(outdir, midi.name + ".maps." + expansion + ".json")
            inserted_notes_output = subprocess.check_output([
                "Rscript",
                os.path.join(sys.path[0], "trompa-align-local.R"), 
                corresp_file,
                maps_file,
                mei_uri,
                expansion or ""
            ])
            split = inserted_notes_output.split()[1]
            num_inserted_notes = int(split)
            print("COMPLETED RUN: ", num_inserted_notes)
            if fewest_inserted_notes is None or num_inserted_notes < fewest_inserted_notes:
                fewest_inserted_notes = num_inserted_notes
                best_expansion = expansion
                print("current best: ", best_expansion, " ", fewest_inserted_notes)
            else:
                # not the best expansion, so throw away the maps file
                pathlib.Path(maps_file).unlink()
                print("throwing out unused expansion: ", expansion)

        except Exception as e:
            print("!!!!! Could not process ", midi, " -- skipping")
            print("!!!!! Exception was: ", e)
            break



if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--performancedir', help="Directory containing performance MIDI files", required=True)
    parser.add_argument('-m', '--meiuri', help="URI of MEI file being performed", required=True)
    parser.add_argument('-o', '--outputdir', help="Directory to which output maps.json should be written", required=True)
    parser.add_argument('-e', '--expansion', help="Specify a particular Verovio expansion option (overrides standardExpansions)", required=False)
    parser.add_argument('-s', '--standardexpansions', help="Try expansion-default and expansion-minimal, proceed with best one", dest="standard_expansions", action='store_true')
    args = parser.parse_args()
    tempdir = tempfile.mkdtemp()
    print("Tempdir: ", tempdir)
    if args.standard_expansions:
        expansions = ["expansion-default", "expansion-minimal"]
    else: 
        expansions = [args.expansion]
    midi_files = [path for path in pathlib.Path(args.performancedir).rglob('*.mid')]
    print("About to start processing with expansions: ", expansions)
    batch_process(midi_files, args.meiuri, expansions, args.outputdir, tempdir)

    

    


