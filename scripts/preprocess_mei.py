import argparse, tempfile, requests, os, uuid, json
from convert_to_rdf import generate_structural_segmentation, segmentation_to_graph, graph_to_jsonld
from mei_to_midi import mei_to_midi

def main(mei_file, mei_uri, structure_uri, structure_out, midi_out):
    # generate structure RDF (jsonld)
    structure_data = generate_structural_segmentation(mei_file)
    g = segmentation_to_graph(structure_data, structure_uri, mei_uri)
    jsonld = json.dumps(graph_to_jsonld(g, ''), indent=2)
    with open(structure_out, 'w') as json_file:
        json_file.write(jsonld)

    # synthesise MIDI from MEI
    with open(mei_file, 'r') as f:
        mei_data = f.read()
    mei_to_midi(mei_data, midi_out)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--meiFile', required=True)
    parser.add_argument('--meiUri', required=True)
    parser.add_argument('--structureUri', required=True)
    parser.add_argument('--structureOutput', required=True)
    parser.add_argument('--midiOutput', required=True)

    args = parser.parse_args()
    
    main(args.meiFile, args.meiUri, args.structureUri, args.structureOutput, args.midiOutput)
