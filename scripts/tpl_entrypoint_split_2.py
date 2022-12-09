import argparse, tempfile, requests, os
from performance_alignment_workflow_split_2 import perform_workflow_split_2


def main(mei_uri, structure_uri, performance_uri, audio_uri, maps, output):
    # build args object
    perform_workflow_split_2(
        performance_uri,
        mei_uri,
        structure_uri,
        audio_uri,
        maps,
        output
    )


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--maps', required=True)
    parser.add_argument('--performanceUri', required=True)
    parser.add_argument('--meiUri', required=True)
    parser.add_argument('--structureUri', required=True)
    parser.add_argument('--audioUri', required=True)
    parser.add_argument('--outputFilename', required=True)

    args = parser.parse_args()

    main(args.meiUri, args.structureUri, args.performanceUri, args.audioUri, args.maps, args.outputFilename)
