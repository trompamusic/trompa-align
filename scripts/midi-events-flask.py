from flask import Flask, request, jsonify
from flask_cors import CORS
from pprint import pprint
from mido import Message, MidiFile, MidiTrack, second2tick, bpm2tempo

import json

app = Flask(__name__)
CORS(app)

ticks_per_beat = 5000
print("ticks per beat: ", ticks_per_beat)
tempo = bpm2tempo(120)
print("tempo: ", tempo)

@app.route("/midiBatch", methods=['POST'])
def receiveMidiBatch():
    midiBatch = request.get_json()
    #midiNotes = list(filter(lambda e: e["data"]["_messageCode"] in codesToInclude, midiBatch))
    midiNotes = midiBatch
    midiFile = MidiFile()
    midiFile.ticks_per_beat = ticks_per_beat
        
    track = MidiTrack()
    midiFile.tracks.append(track)

    prevTime = midiNotes[0]["timestamp"] 
    
    for note in midiNotes:
        # write into MIDI file with seconds2ticks for timestamp
        try:
            eventType = "UNKNOWN"
            messageCode = int(note["data"]["_messageCode"])
            code = (note["data"]["_data"]["0"] >> 4) & 0b00000111
            channel = note["data"]["_data"]["0"] & 0b00001111
            key = note["data"]["_data"]["1"]
            velocity = note["data"]["_data"]["2"] & 0b01111111

            print("code: ", code, "channel: ", channel, "key: ", key, "vel: ", velocity)

            time = round(second2tick((note["timestamp"]-prevTime)/1000, ticks_per_beat=ticks_per_beat, tempo=tempo))
            if code == 0b001:
                eventType = "note_on"
                track.append(Message(eventType, channel=0, note=key, velocity=velocity, time=time))
                print("APPEND NOTE ON: ", eventType, 0, key, velocity, time)
                prevTime = note["timestamp"]
            elif code == 0b000:# or code == 0b0000:
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
                #track.append(Message(eventType, channel=0, note=key, value=velocity, time=time))
#            elif(code == 192):
#                eventType = "note_on"
#                track.append(Message(eventType, channel=0, note=key, velocity=velocity, time=time))
#                 eventType = "program_change"
                #track.append(Message(eventType, channel=0, program=key, time=time))
            elif code == 0b101:
                eventType = "aftertouch"
                #track.append(Message(eventType, channel=0, value=key, time=time))
            elif code == 0b110:
                eventType = "pitchwheel"
                #track.append(Message(eventType, channel=0, pitch=key, time=time))
            elif code == 0b111:
                eventType = "sysex"
                #track.append(Message(eventType, data=(key, velocity), time=time))
            else:
                print("UNKNOWN CODE WAS ", code)
            print("EVENT TYPE: ", eventType);

            #track.append(Message(eventType, note=key, velocity=velocity, time=time))
            #track.append(Message(code, note=key, velocity=velocity, time=time))
       #     if eventType != "UNKNOWN":
              #  prevTime = note["timestamp"]
        except ValueError as e:
            print("Problem with: ", note, e)
    midiFile.save("test_song.mid")

    return json.dumps({'success':True}), 202, {'ContentType':'application/json'}
