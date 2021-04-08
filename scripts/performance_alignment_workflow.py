import os, sys, argparse, csv, uuid
PYTHON_VERSION = "python3"
parser = argparse.ArgumentParser()
parser.add_argument('--smatPath', help="Absolute path of locally installed Symbolic Music Alignment Tool folder", required=True)
parser.add_argument('--meiUri', help="URI of MEI file being performed", required=True)
parser.add_argument('--structureUri', help="URI of the structural segmentation RDF for the MEI file being performed", required=True)
parser.add_argument('--timelineOutput', help="Path to the alignment timeline JSONLD file to be generated", required=True)
parser.add_argument('--solidClaraBaseUri', help="URI of base CLARA folder in user's SOLID Pod", required=True)
parser.add_argument('--tpl-out', help="File used by TROMPA Processing Library to identify the segment RDF output", required=True)
perfMidiGroup = parser.add_mutually_exclusive_group(required=True)
perfMidiGroup.add_argument('--performanceMidi', help="Stringified JSON object containing MIDI event data received from client")
perfMidiGroup.add_argument('--performanceMidiFile', help="Locally stored MIDI file for the performance")
args = parser.parse_args()

tmpUuid = os.path.join(os.getcwd(), "") + str(uuid.uuid4()) + ".tmp."

try:
    if args.perfMidi is not None:
        print("** ALIGNMENT STEP 0: Writing performance MIDI to file")
        ret = os.system("{python} {scriptsPath}/midi-events-to-file.py --midiJson {performanceMidi} --output {midiOut}".format(
                scriptsPath=sys.path[0],
                performanceMidi = args.performanceMidi,
                midiOut = tmpUuid + "performance.mid",
                python = PYTHON_VERSION
            )
        )


    print("** ALIGNMENT STEP 1: Synthesising canonical (score) MIDI")
    ret = os.system("{python} {scriptsPath}/mei-to-midi.py --meiUri {meiUri} --output {canonicalMidi}".format(
            scriptsPath = sys.path[0],
            meiUri = args.meiUri,
            canonicalMidi = tmpUuid + "canonical.mid",
            python=PYTHON_VERSION
    )
    )
    if ret:
        sys.exit("** ALIGNMENT FAILED AT STEP 1: Synthesising canonical (score) MIDI ")

    print("** ALIGNMENT STEP 2: Aligning canonical and performance MIDI")
    ret = os.system("{python} {scriptsPath}/smat-align.py -s {smatPath} -c {canonicalMidi} -p {performanceMidi} -o {corresp}".format(
            scriptsPath = sys.path[0],
            smatPath = args.smatPath,
            canonicalMidi = tmpUuid + "canonical.mid",
            performanceMidi = args.performanceMidiFile if args.performanceMidiFile is not None else tmpUuid + "performance.mid",
            corresp = tmpUuid + "corresp",
            python=PYTHON_VERSION

    )
    )
    if ret:
        sys.exit("** ALIGNMENT FAILED AT STEP 2: Aligning canonical and performance MIDI ")

    print("** ALIGNMENT STEP 3: Performing MIDI-to-MEI reconciliation and producing MAPS output")
    ret = os.system("Rscript {scriptsPath}/trompa-align.R {corresp} {maps} {meiUri}".format(
            scriptsPath = sys.path[0],
            corresp = tmpUuid + "corresp",
            maps = tmpUuid + "maps.json",
            meiUri = args.meiUri
        )
    )
    if ret:
        sys.exit("** ALIGNMENT FAILED AT STEP 3: MIDI-to-MEI reconciliation ")

    print("** ALIGNMENT STEP 4: Converting MAPS output to aligned timeline Linked Data (JSONLD)")
    ret = os.system("{python} {scriptsPath}/convert_to_rdf.py -m {maps} -c {solidClaraBaseUri} -u {meiUri} -s {structureUri} -o {timelineOutput} -f tpl".format(
            scriptsPath = sys.path[0],
            maps = tmpUuid + "maps.json",
            solidClaraBaseUri = args.solidClaraBaseUri,
            meiUri = args.meiUri,
            structureUri = args.structureUri,
            timelineOutput = args.timelineOutput,
            python=PYTHON_VERSION

    )
    )
    if ret:
        sys.exit("** ALIGNMENT FAILED AT STEP 4: Converting MAPS output to timeline JSONLD ")

    print("** ALIGNMENT SUCCESS! Output produced: ", args.timelineOutput)

finally:
    print("** POST-ALIGNMENT: Deleting temporary file: ", tmpUuid + "canonical.mid")
    try: 
        os.remove(tmpUuid + "canonical.mid")
    except:
        print("** Error while tidying up: Couldn't delete ", tmpUuid + "canonical.mid")

    print("** POST-ALIGNMENT: Deleting temporary file: ", tmpUuid + "corresp")
    try: 
        os.remove(tmpUuid + "corresp")
    except:
        print("** Error while tidying up: Couldn't delete ", tmpUuid + "corresp")

    print("** POST-ALIGNMENT: Deleting temporary file: ", tmpUuid + "maps.json")
    try: 
        os.remove(tmpUuid + "maps.json")
    except:
        print("** Error while tidying up: Couldn't delete ", tmpUuid + "maps.json")
