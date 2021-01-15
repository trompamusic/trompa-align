import os, sys, shutil, argparse, uuid, glob

if __name__ == "__main__": 
    parser = argparse.ArgumentParser()
    parser.add_argument('--canonicalMIDI', '-c', help="Absolute path to a canonical MIDI file (e.g., generated from MEI)", required=True)
    parser.add_argument('--performanceMIDI', '-p', help="Absolute path to a MIDI file recording a performance", required=True)
    parser.add_argument('--SMAT', '-s', help="Absolute path of unzipped Symbolic Music Alignment Tool directory", required=True)
    parser.add_argument('--out', '-o', help="Absolute path of corresp file to generate as output", required=True)
    args = parser.parse_args()

    if not(
        os.path.isabs(args.canonicalMIDI) and 
        os.path.isabs(args.performanceMIDI) and 
        os.path.isabs(args.SMAT)
        ):
        sys.exit("Please supply all parameters as absolute paths")
    # SMAT expects MIDI files to live inside the SMAT directory. 
    # Copy them over there temporarily, do the alignment, then delete the tmp files
    tmpUuid = str(uuid.uuid4()) + ".tmp."
    smatPath = os.path.join(args.SMAT, "")
    try:
        shutil.copy(args.canonicalMIDI, smatPath + tmpUuid + "canonical.mid")
        shutil.copy(args.performanceMIDI, smatPath + tmpUuid + "performance.mid")
    except IOError as e:
        sys.exit("Unable to copy MIDI files to SMAT directory. Please ensure SMAT directory is writeable. %s" % e)
    except:
        sys.exit("Unexpected error:", sys.exc_info())
    mainDir = os.getcwd()
    os.chdir(smatPath)
    os.system("./MIDIToMIDIAlign.sh {c} {p}"
        .format(
            SMAT = args.SMAT,
            c = tmpUuid + "canonical",
            p = tmpUuid + "performance"
        )
    )
    # Hopefully SMAT has generated a corresp file, along with a bunch of other stuff
    # We only need the corresp file. Copy it out to our output path 
    os.chdir(mainDir)
    try: 
        shutil.copy(smatPath + tmpUuid + "performance_corresp.txt", args.out)
    except IOError as e:
        sys.exit("Unable to copy corresp file to output path. Did corresp get generated? %s" % e)
    except:
        sys.exit("Unexpected error copying corresp file:", sys.exc_info())
    # Now tidy up by deleting the other files generated by SMAT
    toDelete = glob.glob(smatPath + tmpUuid + "*")
    for f in toDelete:
        try: 
            os.remove(f)
        except:
            print("Error while tidying up: Couldn't delete ", f)

    

