import argparse
import os
import sys



os.system(
    "python {scriptsPath}/convert_to_rdf.py --format tpl --meiFile {meiFile} --segmentlineOutput {seglineOut} --meiUri {meiUri} --segmentlineUri {segmentlineUri}"
    .format(
        scriptsPath=sys.path[0],
        meiFile=args.meiFile,
        seglineOut=seglineOut,
        meiUri=args.meiUri,
        segmentlineUri=segmentlineUri
    )
)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--meiFile', help="Path to local MEI file", required=True)
    parser.add_argument('--segmentlineOutput', help="Path to local segment RDF output file", required=True)
    parser.add_argument('--meiUri', help="URI of MEI file", required=True)
    parser.add_argument('--segmentlineHost',
                        help="Segment line host (URI of directory that will contain the segment RDF output file",
                        required=True)

    args = parser.parse_args()

    # ensure our output file ends in .jsonld
    seglineOut = args.segmentlineOutput if args.segmentlineOutput.endswith(
        ".jsonld") else args.segmentlineOutput + ".jsonld"
    # build the URI for the generated file, inserting a slash if necessary
    segmentlineUri = args.segmentlineHost + seglineOut if args.segmentlineHost.endswith(
        "/") else args.segmentlineHost + "/" + seglineOut

