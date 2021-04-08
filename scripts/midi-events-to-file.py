#!/usr/bin/python

from pprint import pprint
from mido import Message, MidiFile, MidiTrack, second2tick, bpm2tempo
import json
import argparse

codesToInclude = [64, 144]
ticks_per_beat = 5000
tempo = bpm2tempo(120)

if __name__ == "__main__": 
    parser = argparse.ArgumentParser()
    parser.add_argument('--midiJson', '-j', help="JSON file containing MIDI event data received from client", required=True)
    parser.add_argument('--output', '-o', help="Name of output MIDI file to generate", required=True)
    args = parser.parse_args()
    midiJson = args.midiJson
    output = args.output

    with open(midiJson, 'r') as j:
        midiBatchJson = j.read()
    midiBatch = json.loads(midiBatchJson)
    midiNotes = list(filter(lambda e: e["data"]["_messageCode"] in codesToInclude, midiBatch))
    midiFile = MidiFile()
    midiFile.ticks_per_beat = ticks_per_beat
        
    track = MidiTrack()
    midiFile.tracks.append(track)

    prevTime = midiNotes[0]["timestamp"] 
    
    for note in midiNotes:
        # write into MIDI file with seconds2ticks for timestamp
        eventType = "UNKNOWN"
        code = note["data"]["_data"]["0"]
        key = note["data"]["_data"]["1"]
        velocity = note["data"]["_data"]["2"]
#        print("timestamp: ", (note["timestamp"] - prevTime) / 1000)
        time = round(second2tick((note["timestamp"]-prevTime) / 1000, ticks_per_beat=ticks_per_beat, tempo=tempo))
#        print("time in ticks: ", time)
        if code == 144:
            eventType = "note_on"
        elif code == 64:
            eventType = "note_off"
        else:
            print("UNHANDLED MIDI CODE: ", code)
        if eventType != "UNKNOWN":
            track.append(Message(eventType, note=key, velocity=velocity, time=time))
        prevTime = note["timestamp"]
    midiFile.save(output)

