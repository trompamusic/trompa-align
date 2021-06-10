#!/usr/bin/python
from midi2audio import FluidSynth
from pydub import AudioSegment
import argparse, uuid, os

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--midiFile', '-m', help="Path to a MIDI file", required=True)
    parser.add_argument('--output', '-o', help="Name of output MP3 file to generate", required=True)
    args = parser.parse_args()

    tmpFile = str(uuid.uuid4()) + ".tmp.wav"

    fs = FluidSynth()
    fs.midi_to_audio(args.midiFile, tmpFile)
    wav = AudioSegment.from_file(tmpFile, format="wav")
    wav.export(args.output, format="mp3")
    try:
        os.remove(tmpFile)
    except Exception as e:
        print("Sorry, couldn't clean up temporary .wav file, please remove manually: ", tmpFile, e)
