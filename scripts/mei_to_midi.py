#!/usr/bin/python

import argparse
import requests
import sys

import verovio

verovio.enableLog(False)


def mei_to_midi(mei, fname, expansion):
    vrv = verovio.toolkit()
    if bool(expansion):
        vrv.setOption('expand', expansion)
    vrv.loadData(mei)
    vrv.renderToMIDIFile(fname)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--meiUri', '-u', help="URI of a publicly accessible MEI file", required=False)
    parser.add_argument('--meiFile', '-m', help="Path to an MEI file", required=False)
    parser.add_argument('--expansion', '-e', help="Value to send to Verovio expansion parameter", required=False)
    parser.add_argument('--output', '-o', help="Name of output MIDI file to generate", required=True)
    args = parser.parse_args()
    meiUri = args.meiUri
    meiFile = args.meiFile
    output = args.output
    if not bool(output):
        sys.exit("Please supply an --output file name for your MIDI file")
    if bool(meiUri) and bool(meiFile):
        sys.exit("Please specify EITHER --meiUri OR --meiFile")
    elif not (bool(meiUri) or bool(meiFile)):
        sys.exit("Please specify EITHER --meiUri OR --meiFile")
    if bool(meiFile):
        with open(meiFile, 'r') as f:
            data = f.read()
    else:
        resp = requests.get(meiUri)
        data = resp.text
    mei_to_midi(data, output, args.expansion)
