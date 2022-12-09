import json

import verovio


def generate_notes_from_mei(mei_file, expansion):
    verovio.enableLog(False)
    tk = verovio.toolkit()
    if expansion:
        tk.setOptions({'expand': f'{expansion}'})

    print('VERSION', tk.getVersion())
    try:
        tk.loadFile(mei_file)
    except:
        print(f'Python: Could not load MEI file: {mei_file}')

    print('Python: Rendering to MIDI')
    # must render to MIDI first or getMIDIValuesForElement won't work
    tk.renderToMIDI()
    print('Python: Rendering to Timemap')

    timemap = json.loads(tk.renderToTimemap())
    allNotes = []
    timemapNoteOns = list(filter(lambda x: 'on' in x, timemap))

    list(map(lambda x: list(map(lambda y: allNotes.append({
        'id': y,
        'tstamp': x['tstamp'],
        'midiPitch': tk.getMIDIValuesForElement(y)['pitch']
    }), x['on'])), timemapNoteOns))

    return allNotes
