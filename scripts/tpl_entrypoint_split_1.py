import argparse, tempfile, requests, os, uuid
from mido import Message, MidiFile, MidiTrack, second2tick, bpm2tempo
from trompasolid import client
from performance_alignment_workflow_split_1 import perform_workflow_split_1

ticks_per_beat = 5000
tempo = bpm2tempo(120)

REDIS_HOST = os.environ.get("TPL_AUTH_REDIS_HOST", "localhost")

def main(mei_uri, structure_uri, webid, tempdir, audio_fname, score_midi):
    # build args object
    perform_workflow_split_1(
        os.path.join(tempdir, "performanceMidi.mid"), # performance_midi
        score_midi,
        os.path.join(tempdir, "score.mei"),           # mei_file
        mei_uri,                                      # mei_uri
        structure_uri,                                # structure_uri
        webid,                                        # webid
        tempdir,                                       # tempdir
        audio_fname
    )

def read_from_solid(webid, uri, contenttype):
    client.init_redis(REDIS_HOST)
    identity_provider = lookup_provider_from_profile(webid)
    bearer = client.get_bearer_for_user(identity_provider, webid)
    return requests.get(uri, headers={"authorization": "Bearer %s" % bearer, "content-type": contenttype})

def lookup_provider_from_profile(webid):
    r = requests.options(webid)
    links = r.headers.get('Link')
    if links:
        parsed_links = requests.utils.parse_header_links(links)
        for l in parsed_links:
            if l.get('rel') == 'http://openid.net/specs/connect/1.0/issuer':
                return l['url']

def webmidi_to_midi(webmidi_json, tempdir):
    midiNotes = webmidi_json
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
    parser.add_argument('--performanceMidiUri', required=True)
    parser.add_argument('--isWebMidi', required=False)
    parser.add_argument('--meiUri', required=True)
    parser.add_argument('--scoreMidi', required=True)
    parser.add_argument('--structureUri', required=True)
    parser.add_argument('--webId', required=True)
    parser.add_argument('--audioFilename', required=False)
    meiGroup = parser.add_mutually_exclusive_group(required=True)
    meiGroup.add_argument('--isExternalMei')
    meiGroup.add_argument('--meiFile')

    args = parser.parse_args()
    tempdir = tempfile.mkdtemp()

    if args.audioFilename:
        audio_fname = args.audioFilename
    else: 
        audio_fname = str(uuid.uuid4()) + ".mp3"

    performance_data = read_from_solid(args.webId, args.performanceMidiUri, "application/ld+json").json()

    if args.isWebMidi:
        webmidi_to_midi(performance_data, tempdir)
    else: 
        with open(os.path.join(tempdir,"performanceMidi.mid"), 'wb') as out:
            out.write(performance_data)

    if args.isExternalMei:
        # Solid-hosted, non-CE MEI file. Download it.
        r = read_from_solid(args.webId, args.meiUri, "text/plain")
        r.raise_for_status()
        mei = r.text
    else: 
        with open(args.meiFile, 'r') as f:
            mei = f.read()

    with open(os.path.join(tempdir, "score.mei"), 'w') as out:
        out.write(mei)

    main(args.meiUri, args.structureUri, args.webId, tempdir, audio_fname, args.scoreMidi)
