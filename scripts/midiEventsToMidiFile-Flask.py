from flask import Flask, request, jsonify
from flask_cors import CORS
from pprint import pprint
from mido import Message, MidiFile, MidiTrack, second2tick, bpm2tempo

import json

app = Flask(__name__)
CORS(app)

codesToInclude = [64, 144]
ticks_per_beat = 5000
tempo = bpm2tempo(120)

@app.route("/midiBatch", methods=['POST'])
def receiveMidiBatch():
    midiBatch = request.get_json()
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
        print("timestamp: ", (note["timestamp"] - prevTime) / 1000)
        time = round(second2tick((note["timestamp"]-prevTime) / 1000, ticks_per_beat=ticks_per_beat, tempo=tempo))
        print("time in ticks: ", time)
        if code == 144:
            eventType = "note_on"
        elif code == 64:
            eventType = "note_off"
        else:
            print("UNKNOWN CODE WAS ", code)
        if eventType != "UNKNOWN":
            track.append(Message(eventType, note=key, velocity=velocity, time=time))
        prevTime = note["timestamp"]
    midiFile.save("test_song.mid")

    return json.dumps({'success':True}), 202, {'ContentType':'application/json'}
