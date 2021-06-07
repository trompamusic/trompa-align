import argparse, tempfile, requests, os, uuid
from mido import Message, MidiFile, MidiTrack, second2tick, bpm2tempo
from trompasolid import client
from performance_alignment_workflow import perform_workflow

ticks_per_beat = 5000
tempo = bpm2tempo(120)

def main(mei_uri, structure_uri, performance_container, audio_container, webid, tempdir, perf_fname, audio_fname):
    # download MEI file
    r = requests.get(mei_uri)
    r.raise_for_status()
    mei = r.text
    with open(os.path.join(tempdir, "score.mei"), 'w') as out:
        out.write(mei)
    # build args object
    perform_workflow(
        os.path.join(tempdir, "performanceMidi.mid"), # performance_midi
        os.path.join(tempdir, "score.mei"),           # mei_file
        mei_uri,                                      # mei_uri
        structure_uri,                                # structure_uri
        performance_container,                        # performance_container
        audio_container,                              # audio_container
        webid,                                        # webid
        tempdir,                                       # tempdir
        perf_fname,
        audio_fname
    )
    write_to_solid(webid, tempdir)

def write_to_solid(webid, tempdir):
    print("Now I would have tried to write to Solid with ", webid, tempdir)
#    client.init_redis()
#    identity_provider = solid.lookup_provider_from_profile(web_id)
#    bearer = client.get_bearer_for_user(identity_provider,web_id)
#    r = requests.put("https://alastair.trompa-solid.upf.edu/testfile.txt", data="this is the contents to add to the file", headers={"authorization": "Bearer %s" % bearer, "content-type": "text/plain"})

def webmidi_to_midi(webmidi_json_uri, tempdir):
    r = requests.get(webmidi_json_uri)
    r.raise_for_status()
    midiNotes = r.json()
    midiFile = MidiFile()
    midiFile.ticks_per_beat = ticks_per_beat
        
    track = MidiTrack()
    midiFile.tracks.append(track)

    prevTime = midiNotes[0]["timestamp"] 
    
    for note in midiNotes:
        # write into MIDI file with seconds2ticks for timestamp
        try:
            eventType = "UNKNOWN"
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
                print("webmidi_to_midi: UNKNOWN CODE WAS ", code)
            print("webmidi_to_midi: EVENT TYPE: ", eventType);
        except ValueError as e:
            print("webmidi_to_midi: Problem with: ", note, e)
    midiFile.save(os.path.join(tempdir, "performanceMidi.mid"))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--performanceMidi', required=True)
    parser.add_argument('--isWebMidi', required=False)
    parser.add_argument('--meiUri', required=True)
    parser.add_argument('--structureUri', required=True)
    parser.add_argument('--performanceContainer', required=True)
    parser.add_argument('--audioContainer', required=True)
    parser.add_argument('--webId', required=True)
    parser.add_argument('--performanceFilename', required=False)
    parser.add_argument('--audioFilename', required=False)
    tempdir = tempfile.mkdtemp()
    args = parser.parse_args()
    if args.performanceFilename:
        perf_fname = args.performanceFilename
    else: 
        perf_fname = str(uuid.uuid4()) + ".jsonld"
    if args.audioFilename:
        audio_fname = args.audioFilename
    else: 
        audio_fname = str(uuid.uuid4()) + ".mp3"
    if args.isWebMidi:
        webmidi_to_midi(args.performanceMidi, tempdir)
    else: 
        r = requests.get(args.performanceMidi).content
        if r.status < 400:
            with open(os.path.join(tempdir,"performanceMidi.mid"), 'wb') as out:
                out.write(perfMidi)
        else:
            raise Exception("Could not download performanceMidi: ", args.performanceMidi)
    main(args.meiUri, args.structureUri, args.performanceContainer,
         args.audioContainer, args.webId, tempdir, perf_fname, audio_fname)
