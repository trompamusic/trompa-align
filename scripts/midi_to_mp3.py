#!/usr/bin/python
import argparse
import os
import tempfile

from midi2audio import FluidSynth
from pydub import AudioSegment


def midi_to_mp3(midifile, output, tempdir):
    tempfile = os.path.join(tempdir, "synthAudio.wav")
    fs = FluidSynth()
    fs.midi_to_audio(midifile, tempfile)
    wav = AudioSegment.from_file(tempfile, format="wav")
    wav.export(output, format="mp3")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--midiFile", "-m", help="Path to a MIDI file", required=True)
    parser.add_argument("--output", "-o", help="Name of output MP3 file to generate", required=True)
    args = parser.parse_args()
    midi_to_mp3(args.midiFile, args.output, tempfile.mkdtemp())
