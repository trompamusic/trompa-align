import os, sys, argparse, csv, uuid, requests, json
from mei_to_midi import mei_to_midi
from midi_to_mp3 import midi_to_mp3 
from smat_align import smat_align
from convert_to_rdf import maps_result_to_graph, graph_to_jsonld
import subprocess

# TODO UPDATE CLI in align-directly.ini line 24

PYTHON_VERSION = "python3"

def perform_workflow_split_2(performance_uri, mei_uri, structure_uri, audio_uri, maps, output): 
    print("** Performing RDF CONVERSION")
    with open(maps, 'rb') as f:
        maps_json = f.read()
    g = maps_result_to_graph(
        maps_json, 
        structure_uri, 
        mei_uri, 
        performance_uri,
        mei_uri,
        audio_uri,
        True
    )
    jsonld = json.dumps(graph_to_jsonld(g, ''), indent=2)
    with open(output, 'w') as json_file:
        json_file.write(jsonld)
    print("** Success: Created timeline output: ", output)
