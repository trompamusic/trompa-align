#!/usr/bin/python

import argparse
import json

from mido import Message, MidiFile, MidiTrack, second2tick, bpm2tempo

ticks_per_beat = 5000
tempo = bpm2tempo(120)


def midi_json_to_midi(midi_notes):
    midiFile = MidiFile()
    midiFile.ticks_per_beat = ticks_per_beat

    track = MidiTrack()
    midiFile.tracks.append(track)

    prevTime = midi_notes[0]["timestamp"]

    for note in midi_notes:
        # write into MIDI file with seconds2ticks for timestamp
        try:
            eventType = "UNKNOWN"
            code = (note["data"]["_data"]["0"] >> 4) & 0b00000111
            channel = note["data"]["_data"]["0"] & 0b00001111
            key = note["data"]["_data"]["1"]
            velocity = note["data"]["_data"]["2"] & 0b01111111

            print("code: ", code, "channel: ", channel, "key: ", key, "vel: ", velocity)

            time = round(second2tick((note["timestamp"] - prevTime) / 1000, ticks_per_beat=ticks_per_beat, tempo=tempo))
            if code == 0b001:
                eventType = "note_on"
                track.append(Message(eventType, channel=0, note=key, velocity=velocity, time=time))
                print("APPEND NOTE ON: ", eventType, 0, key, velocity, time)
                prevTime = note["timestamp"]
            elif code == 0b000:  # or code == 0b0000:
                eventType = "note_off"
                track.append(Message(eventType, channel=0, note=key, velocity=velocity, time=time))
                print("APPEND NOTE OFF: ", eventType, 0, key, velocity, time)
                prevTime = note["timestamp"]
            elif code == 0b011:
                eventType = "control_change"
                track.append(Message(eventType, channel=0, control=key, value=velocity, time=time))
                print("APPEND CONTROL CHANGE: ", eventType, 0, key, velocity, time)
                prevTime = note["timestamp"]
            elif code == 0b010:
                eventType = "polytouch"
                # track.append(Message(eventType, channel=0, note=key, value=velocity, time=time))
            elif code == 0b101:
                eventType = "aftertouch"
                # track.append(Message(eventType, channel=0, value=key, time=time))
            elif code == 0b110:
                eventType = "pitchwheel"
                # track.append(Message(eventType, channel=0, pitch=key, time=time))
            elif code == 0b111:
                eventType = "sysex"
                # track.append(Message(eventType, data=(key, velocity), time=time))
            else:
                print("UNKNOWN CODE WAS ", code)
            print("EVENT TYPE: ", eventType)
        except ValueError as e:
            print("Problem with: ", note, e)

    return midiFile


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("midiJson", help="JSON file containing MIDI event data received from client")
    parser.add_argument("output", help="Name of output MIDI file to generate")
    args = parser.parse_args()
    output = args.output

    with open(args.midiJson, "r") as fp:
        midi_notes = json.load(fp)

    midi = midi_json_to_midi(midi_notes)
    midi.save(args.output)
