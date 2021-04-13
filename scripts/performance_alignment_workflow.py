import os, sys, argparse, csv, uuid
PYTHON_VERSION = "python3"
parser = argparse.ArgumentParser()
parser.add_argument('--smatPath', help="Absolute path of locally installed Symbolic Music Alignment Tool folder", required=True)
parser.add_argument('--meiUri', help="URI of MEI file being performed", required=True)
parser.add_argument('--structureUri', help="URI of the structural segmentation RDF for the MEI file being performed", required=True)
parser.add_argument('--solidContainer', help="URI of base CLARA folder in user's SOLID Pod", required=True)
parser.add_argument('--tpl-out', help="File used by TROMPA Processing Library to identify the segment RDF output", required=True)
perfMidiGroup = parser.add_mutually_exclusive_group(required=True)
perfMidiGroup.add_argument('--performanceMidi', help="Stringified JSON object containing MIDI event data received from client")
perfMidiGroup.add_argument('--performanceMidiFile', help="Locally stored MIDI file for the performance")
args = parser.parse_args()

myUuid = str(uuid.uuid4())
tmpPrefix = os.path.join(os.getcwd(), "") + myUuid + ".tmp."
outfile = os.path.join(os.getcwd(), "") + myUuid + ".jsonld"

try:
    if args.performanceMidi is not None:
        print("** ALIGNMENT STEP 0: Writing performance MIDI to file")
        ret = os.system("{python} {scriptsPath}/midi-events-to-file.py --midiJson {performanceMidi} --output {midiOut}".format(
                scriptsPath=sys.path[0],
                performanceMidi = args.performanceMidi,
                midiOut = tmpPrefix + "performance.mid",
                python = PYTHON_VERSION
            )
        )


    print("** ALIGNMENT STEP 1: Synthesising canonical (score) MIDI")
    ret = os.system("{python} {scriptsPath}/mei-to-midi.py --meiUri {meiUri} --output {canonicalMidi}".format(
            scriptsPath = sys.path[0],
            meiUri = args.meiUri,
            canonicalMidi = tmpPrefix + "canonical.mid",
            python=PYTHON_VERSION
    )
    )
    if ret:
        sys.exit("** ALIGNMENT FAILED AT STEP 1: Synthesising canonical (score) MIDI ")

    print("** ALIGNMENT STEP 2: Aligning canonical and performance MIDI")
    ret = os.system("{python} {scriptsPath}/smat-align.py -s {smatPath} -c {canonicalMidi} -p {performanceMidi} -o {corresp}".format(
            scriptsPath = sys.path[0],
            smatPath = args.smatPath,
            canonicalMidi = tmpPrefix + "canonical.mid",
            performanceMidi = args.performanceMidiFile if args.performanceMidiFile is not None else tmpPrefix + "performance.mid",
            corresp = tmpPrefix + "corresp",
            python=PYTHON_VERSION

    )
    )
    if ret:
        sys.exit("** ALIGNMENT FAILED AT STEP 2: Aligning canonical and performance MIDI ")

    print("** ALIGNMENT STEP 3: Performing MIDI-to-MEI reconciliation and producing MAPS output")
    ret = os.system("Rscript {scriptsPath}/trompa-align.R {corresp} {maps} {meiUri}".format(
            scriptsPath = sys.path[0],
            corresp = tmpPrefix + "corresp",
            maps = tmpPrefix + "maps.json",
            meiUri = args.meiUri
        )
    )
    if ret:
        sys.exit("** ALIGNMENT FAILED AT STEP 3: MIDI-to-MEI reconciliation ")

    print("** ALIGNMENT STEP 4: Converting MAPS output to aligned timeline Linked Data (JSONLD)")
    ret = os.system("{python} {scriptsPath}/convert_to_rdf.py -m {maps} -c {solidContainer} -t {timelineUri} -u {meiUri} -s {structureUri} -o {timelineOutput} -f tpl".format(
            scriptsPath = sys.path[0],
            maps = tmpPrefix + "maps.json",
            solidContainer = args.solidContainer,
            meiUri = args.meiUri,
            structureUri = args.structureUri,
            timelineOutput = outfile,
            timelineUri = os.path.join(args.solidContainer + myUuid+".jsonld"),
            python=PYTHON_VERSION

    )
    )
    if ret:
        sys.exit("** ALIGNMENT FAILED AT STEP 4: Converting MAPS output to timeline JSONLD ")

    print("** ALIGNMENT SUCCESS! Output produced: ", myUuid + ".jsonld")

finally:
    print("** POST-ALIGNMENT: Deleting temporary file: ", tmpPrefix + "canonical.mid")
    try: 
        os.remove(tmpPrefix + "canonical.mid")
    except:
        print("** Error while tidying up: Couldn't delete ", tmpPrefix + "canonical.mid")

    print("** POST-ALIGNMENT: Deleting temporary file: ", tmpPrefix + "corresp")
    try: 
        os.remove(tmpPrefix + "corresp")
    except:
        print("** Error while tidying up: Couldn't delete ", tmpPrefix + "corresp")

    print("** POST-ALIGNMENT: Deleting temporary file: ", tmpPrefix + "maps.json")
    try: 
        os.remove(tmpPrefix + "maps.json")
    except:
        print("** Error while tidying up: Couldn't delete ", tmpPrefix + "maps.json")
