import os, sys, argparse, csv

parser = argparse.ArgumentParser()
parser.add_argument('--meiFile', help="Path to local MEI file", required=True)
parser.add_argument('--segmentlineOutput', help="Path to local segment RDF output file", required=True)
parser.add_argument('--meiUri', help="URI of MEI file", required=True)
parser.add_argument('--segmentlineHost', help="Segment line host (URI of directory that will contain the segment RDF output file", required=True)
parser.add_argument('--tpl-out', help="File used by TROMPA Processing Library to identify the segment RDF output", required=True)

args = parser.parse_args()

if args.meiFile is None or args.segmentlineOutput is None or args.meiUri is None or args.segmentlineHost is None or args.tpl_out is None:
    sys.exit("")


# ensure our output file neds in .jsonld
seglineOut = args.segmentlineOutput if args.segmentlineOutput.endswith(".jsonld") else args.segmentlineOutput + ".jsonld"
# build the URI for the generated file, inserting a slash if necessary
segmentlineUri = args.segmentlineHost + seglineOut if args.segmentlineHost.endswith("/") else args.segmentlineHost + "/" + seglineOut
with open(args.tpl_out, 'w') as tplOut:
    tplOut.write("[tplout]\noutput=" + seglineOut)
os.system("python {scriptsPath}/convert_to_rdf.py --format tpl --meiFile {meiFile} --segmentlineOutput {seglineOut} --meiUri {meiUri} --segmentlineUri {segmentlineUri}"
    .format(
        scriptsPath = sys.path[0],
        meiFile = args.meiFile, 
        seglineOut = seglineOut,
        meiUri = args.meiUri,
        segmentlineUri = segmentlineUri
    )
)
