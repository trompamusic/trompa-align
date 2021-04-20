from flask import Flask, request, jsonify
from flask_cors import CORS
from pprint import pprint
from mido import Message, MidiFile, MidiTrack, second2tick, bpm2tempo

import json, uuid, os, sys

# set up parameters
PYTHON_VERSION="python3"
SMAT_PATH="/home/weigl/repos/trompa-align-packaged-for-tpl/trompa-align/AlignmentTool_v190813"
MEI_URI="https://raw.githubusercontent.com/trompamusic-encodings/Schumann-Clara_Romanze-in-a-Moll/master/Schumann-Clara_Romanze-ohne-Opuszahl_a-Moll.mei"
STRUCTURE_URI="https://clara.trompa-solid.upf.edu/clara.trompamusic.folder/structure/Schumann-Clara_Romanze-ohne-Opuszahl_A-Moll.jsonld" 
SOLID_CONTAINER="https://clara-test.trompa-solid.upf.edu/private/test1"
SCORE_URI="https://clara.trompa-solid.upf.edu/clara.trompamusic.folder/score/SchumannClara_Romanze.jsonld" 
AUDIO_CONTAINER="https://clara-test.trompa-solid.upf.edu/private/audio/"

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
            code = 0b11110000 & note["data"]["_data"]["0"];
            channel = 1 + (0b00001111 & note["data"]["_data"]["0"]) 
            key = note["data"]["_data"]["1"]
            velocity = note["data"]["_data"]["2"] 

            time = round(second2tick((note["timestamp"]-prevTime)/1000, ticks_per_beat=ticks_per_beat, tempo=tempo))
            if code == 0b10000000:
                eventType = "note_off"
                track.append(Message(eventType, channel=channel, note=key, velocity=velocity, time=time))
                print("APPEND NOTE OFF: code ", format(code, '08b'), "eventType: ", eventType, "channel: ", channel, "key: ", key, "vel: ", velocity, " time: ",time)
                prevTime = note["timestamp"]
            elif code == 0b10010000:
                eventType = "note_on"
                track.append(Message(eventType, channel=channel, note=key, velocity=velocity, time=time))
                print("APPEND NOTE ON: code ", format(code, '08b'), "eventType: ", eventType, "channel: ", channel, "key: ", key, "vel: ", velocity, " time: ",time)
                prevTime = note["timestamp"]
            elif code == 0b10110000:
                eventType = "control_change"
                track.append(Message(eventType, channel=channel, control=key, value=velocity, time=time))
                print("APPEND CONTROL CHANGE: code ", format(code, '08b'), "eventType: ", eventType, "channel: ", channel, "key: ", key, "vel: ", velocity, " time: ",time)
                prevTime = note["timestamp"]
            elif code == 0b10100000:
                eventType = "polytouch"
                #track.append(Message(eventType, channel=0, note=key, value=velocity, time=time))
#            elif(code == 192):
#                eventType = "note_on"
#                track.append(Message(eventType, channel=0, note=key, velocity=velocity, time=time))
#                 eventType = "program_change"
                #track.append(Message(eventType, channel=0, program=key, time=time))
            elif code == 0b11010000:
                eventType = "aftertouch"
                #track.append(Message(eventType, channel=0, value=key, time=time))
            elif code == 0b11100000:
                eventType = "pitchwheel"
                #track.append(Message(eventType, channel=0, pitch=key, time=time))
            elif code == 0b11110000:
                eventType = "sysex"
                #track.append(Message(eventType, data=(key, velocity), time=time))
            else:
                print("UNKNOWN CODE WAS ", format(code, '08b'))

            #track.append(Message(eventType, note=key, velocity=velocity, time=time))
            #track.append(Message(code, note=key, velocity=velocity, time=time))
       #     if eventType != "UNKNOWN":
              #  prevTime = note["timestamp"]
        except ValueError as e:
            print("Problem with: ", note, e)
    myUuid = str(uuid.uuid4())
    midiFile.save(myUuid + ".mid")
    ret = os.system("{python} performance_alignment_workflow.py --smatPath {smatPath} --meiUri {meiUri} --structureUri  {structureUri} --solidContainer {solidContainer} --tpl-out {scriptsPath}/{uuid}-tplOut.jsonld --performanceMidiFile {scriptsPath}/{uuid}.mid --scoreUri {scoreUri} --audioContainer {audioContainer} --uuid {uuid}".format(
            python=PYTHON_VERSION,
            smatPath=SMAT_PATH,
            meiUri=MEI_URI,
            structureUri=STRUCTURE_URI,
            solidContainer=SOLID_CONTAINER,
            uuid=myUuid,
            scoreUri=SCORE_URI,
            audioContainer=AUDIO_CONTAINER,
            scriptsPath=sys.path[0]
    ))
    if ret:
        print("FAILED TO PERFORM ALIGNMENT WORKFLOW WITH UUID:", myUuid, ret)
    else:
        print("PERFORMANCE ALIGNMENT WORKFLOW SUCCESS: ", myUuid)

    return json.dumps({'success':True}), 202, {'ContentType':'application/json'}
