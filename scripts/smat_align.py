import argparse
import glob
import os
import shutil
import subprocess
import sys
import tempfile
import uuid


class SmatException(Exception):
    """Raised when a SMAT alignment step fails."""

    def __init__(self, stage: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage


def smat_align(file1, file2):
    # Align 2 midi files. This is a python port of MIDIToMIDIAlign.sh from SMAT
    # It assumes that the compiled tools are in $PATH
    # Because we use a temporary directory, we don't bother to clean up anything
    with tempfile.TemporaryDirectory() as tempdir:
        shutil.copy(file1, tempdir)
        shutil.copy(file2, tempdir)
        file1_stem = os.path.splitext(os.path.basename(file1))[0]
        file2_stem = os.path.splitext(os.path.basename(file2))[0]

        # Generate pianoroll. Assumes that files are in tempdir. Argument doesn't include
        # extension. Output filename is {stem}_spr.txt
        subprocess.run(["midi2pianoroll", "0", file1_stem], cwd=tempdir)
        subprocess.run(["midi2pianoroll", "0", file2_stem], cwd=tempdir)

        if not os.path.exists(os.path.join(tempdir, f"{file1_stem}_spr.txt")):
            raise SmatException("midi2pianoroll", f"spr of first file, {file1_stem}_spr.txt, doesn't exist")
        if not os.path.exists(os.path.join(tempdir, f"{file2_stem}_spr.txt")):
            raise SmatException("midi2pianoroll", f"spr of second file, {file2_stem}_spr.txt, doesn't exist")

        subprocess.run(["SprToFmt3x", f"{file1_stem}_spr.txt", f"{file1_stem}_fmt3x.txt"], cwd=tempdir)
        if not os.path.exists(os.path.join(tempdir, f"{file1_stem}_fmt3x.txt")):
            raise SmatException("SprToFmt3x", f"fmt3x of first file, {file1_stem}_fmt3x.txt, doesn't exist")

        subprocess.run(["Fmt3xToHmm", f"{file1_stem}_fmt3x.txt", f"{file1_stem}_hmm.txt"], cwd=tempdir)
        if not os.path.exists(os.path.join(tempdir, f"{file1_stem}_hmm.txt")):
            raise SmatException("Fmt3xToHmm", f"hmm of first file, {file1_stem}_hmm.txt, doesn't exist")

        subprocess.run(
            [
                "ScorePerfmMatcher",
                f"{file1_stem}_hmm.txt",
                f"{file2_stem}_spr.txt",
                f"{file2_stem}_pre_match.txt",
                "0.001",
            ],
            cwd=tempdir,
        )
        if not os.path.exists(os.path.join(tempdir, f"{file2_stem}_pre_match.txt")):
            raise SmatException(
                "ScorePerfmMatcher", f"pre_match of second file, {file2_stem}_pre_match.txt, doesn't exist"
            )

        subprocess.run(
            [
                "ErrorDetection",
                f"{file1_stem}_fmt3x.txt",
                f"{file1_stem}_hmm.txt",
                f"{file2_stem}_pre_match.txt",
                f"{file2_stem}_err_match.txt",
                "0",
            ],
            cwd=tempdir,
        )
        if not os.path.exists(os.path.join(tempdir, f"{file2_stem}_err_match.txt")):
            raise SmatException(
                "ErrorDetection", f"err_match of second file, {file2_stem}_err_match.txt, doesn't exist"
            )

        subprocess.run(
            [
                "RealignmentMOHMM",
                f"{file1_stem}_fmt3x.txt",
                f"{file1_stem}_hmm.txt",
                f"{file2_stem}_err_match.txt",
                f"{file2_stem}_realigned_match.txt",
                "0.3",
            ],
            cwd=tempdir,
        )
        if not os.path.exists(os.path.join(tempdir, f"{file2_stem}_realigned_match.txt")):
            raise SmatException(
                "RealignmentMOHMM", f"realigned_match of second file, {file2_stem}_realigned_match.txt, doesn't exist"
            )

        subprocess.run(
            [
                "MatchToCorresp",
                f"{file2_stem}_realigned_match.txt",
                f"{file1_stem}_spr.txt",
                f"{file2_stem}_corresp.txt",
            ],
            cwd=tempdir,
        )
        if not os.path.exists(os.path.join(tempdir, f"{file2_stem}_corresp.txt")):
            raise SmatException(
                "MatchToCorresp", f"end result of second file, {file2_stem}_corresp.txt.txt, doesn't exist"
            )

        with open(os.path.join(tempdir, f"{file2_stem}_corresp.txt")) as fp:
            return fp.read()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--canonicalMIDI", "-c", help="Absolute path to a canonical MIDI file (e.g., generated from MEI)", required=True
    )
    parser.add_argument(
        "--performanceMIDI", "-p", help="Absolute path to a MIDI file recording a performance", required=True
    )
    parser.add_argument(
        "--SMAT", "-s", help="Absolute path of unzipped Symbolic Music Alignment Tool directory", required=True
    )
    parser.add_argument("--out", "-o", help="Absolute path of corresp file to generate as output", required=True)
    args = parser.parse_args()

    if not (os.path.isabs(args.canonicalMIDI) and os.path.isabs(args.performanceMIDI) and os.path.isabs(args.SMAT)):
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
    except Exception:
        sys.exit("Unexpected error:", sys.exc_info())
    mainDir = os.getcwd()
    os.chdir(smatPath)
    os.system("./MIDIToMIDIAlign.sh {c} {p}".format(c=tmpUuid + "canonical", p=tmpUuid + "performance"))
    # Hopefully SMAT has generated a corresp file, along with a bunch of other stuff
    # We only need the corresp file. Copy it out to our output path
    os.chdir(mainDir)
    try:
        shutil.copy(smatPath + tmpUuid + "performance_corresp.txt", args.out)
    except IOError as e:
        sys.exit("Unable to copy corresp file to output path. Did corresp get generated? %s" % e)
    except Exception:
        sys.exit("Unexpected error copying corresp file:", sys.exc_info())
    # Now tidy up by deleting the other files generated by SMAT
    toDelete = glob.glob(smatPath + tmpUuid + "*")
    for f in toDelete:
        os.remove(f)
