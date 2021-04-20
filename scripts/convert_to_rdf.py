import json, os, sys, argparse, csv, urllib.parse
from uuid import uuid4
from pprint import pprint
from rdflib import Graph, plugin
from rdflib.serializer import Serializer
from lxml import etree as ET
from statistics import mean
from datetime import datetime

formatPlaceholder = "____MAPS-FORMAT"

def maps_result_to_graph(maps_result_json, segUri, meiUri, tlUri, scoreUri, audioUri, includePerformance): 
    maps_result = json.loads(maps_result_json)
    rdf = """@prefix mo: <http://purl.org/ontology/mo/> .
@prefix so: <http://www.linkedmusic.org/ontologies/segment/> .
@prefix frbr: <http://purl.org/vocab/frbr/core#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix oa: <http://www.w3.org/ns/oa#> .
@prefix meld: <https://meld.linkedmusic.org/terms/> .
@prefix maps: <https://terms.trompamusic.eu/maps#> .
@prefix tl: <http://purl.org/NET/c4dm/timeline.owl#> .
@prefix tlUri: <{tlUri}#> .
@prefix segUri: <{segUri}#> .
@prefix meiUri: <{meiUri}#> .
@base <{tlUri}> .
""".format(tlUri = tlUri, segUri = segUri, meiUri = meiUri)

    if includePerformance:
        label = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
        rdf += """<{tlUri}> a mo:Performance ;
  mo:performance_of <{scoreUri}> ;
  mo:recorded_as <{tlUri}#Signal> ;
  rdfs:label "{label}" ;
  meld:offset "-0.2" .
<{tlUri}#Signal> mo:available_as <{audioUri}> ;
    mo:time [ 
        a tl:Interval; 
        tl:onTimeLine <{tlUri}#timeline> 
    ] .

""".format(tlUri = tlUri, scoreUri = scoreUri, label = label, audioUri = audioUri)

    rdf += """
<{tlUri}#timeline> a tl:Timeline .
    """.format(segUri = segUri, meiUri = meiUri, tlUri = tlUri)

    for ix, obs in enumerate(maps_result):
        confidence = """maps:confidence "{0}" ;""".format(obs["confidence"]) if "confidence" in obs else ""
        # FIXME HACK -- currently averages note velocities occuring at the same time
        velocity = """maps:velocity "{0}" ;""".format(mean(obs["velocity"])) if "velocity" in obs else "" 
        rdf += """tlUri:{ix} a tl:Instant ;
 tl:onTimeLine <{tlUri}#timeline> ;
 {confidence}{velocity}
 tl:at "P{mean_onset}S" ; """.format(ix = ix, mean_onset = obs["obs_mean_onset"], confidence = confidence, velocity = velocity, tlUri = tlUri)
        # iterate through each associated MEI identifier
        for ix2, xml_id in enumerate(obs["xml_id"]):
            if ix2 == len(obs["xml_id"])-1: 
                term = ".\n"
            else: 
                term = ";"
            rdf += """ frbr:embodimentOf {embodiment_id} {term}""".format(
                    embodiment_id = xml_id.replace("trompa-align_", "maps:") if xml_id.startswith("trompa-align_inserted_") else "meiUri:" + xml_id,
                    term=term
                )
        # iterate through again to annotate velocities for each performed note
        for ix3, velocity in enumerate(obs["velocity"]):
            rdf += """<#velocity{uuid}> a oa:Annotation ; 
    oa:motivatedBy oa:describing ;
    oa:hasTarget <#target{uuid}> ;
    oa:bodyValue "{velocity}" .
<#target{uuid}> oa:hasScope <{tlUri}#timeline> ;
    oa:hasSource {embodiment_id} .\n""".format(
            uuid = str(uuid4()).replace("-", ""), 
            xml_id = obs["xml_id"][ix3], 
            embodiment_id = obs["xml_id"][ix3].replace("trompa-align_", "maps:") if obs["xml_id"][ix3].startswith("trompa-align_inserted_") else "meiUri:" + obs["xml_id"][ix3],
            velocity = velocity,
            tlUri = tlUri
        )

    return Graph().parse(data = rdf, format='n3')

def performances_to_graphs(performances_tsv, segUri, meiUri, tlUri, recordingUri, performancesUri, worksUri):
    graphs = []
    with open(performances_tsv, 'r') as tsvFile:
        tsv = csv.DictReader(tsvFile, delimiter="\t")
        for row in tsv:
            # attempt to read MAPS result
            mapsResultFile = "data/{lastName}-{work}.boe_corresp.txt.maps.json".format(lastName = row['lastName'], work = row['Work'])
            with open(mapsResultFile, 'rb') as f:
                try: 
                    maps_result_json = f.read()
                except IOError: 
                    print("Warning: Skipping file (could not read): ", fName)
                    continue
            graphs.append({
                # generate performance RDF
                "performance": performance_to_graph(row, tlUri, recordingUri, performancesUri, worksUri),
                # generate timeline RDF
                "timeline": maps_result_to_graph(maps_result_json, segUri, meiUri, tlUri + "/" + row["PerformanceID"] + formatPlaceholder, False),
                "performanceID": row["PerformanceID"]
            })
            
    return graphs

def performance_to_graph(perf_dict, tlUri, recordingUri, performancesUri, worksUri):
    rdf = """@prefix mo: <http://purl.org/ontology/mo/> .
@prefix so: <http://www.linkedmusic.org/ontologies/segment/> .
@prefix frbr: <http://purl.org/vocab/frbr/core#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix meld: <https://meld.linkedmusic.org/terms/> .
@prefix maps: <https://terms.trompamusic.eu/maps#> .
@prefix tl: <http://purl.org/NET/c4dm/timeline.owl#> .
@prefix mo: <http://purl.org/ontology/mo/> .

<{perfPath}/{performanceID}{formatPlaceholder}> a mo:Performance ;
    mo:performance_of <{worksUri}/{pieceLabel}{formatPlaceholder}> ;
    mo:recorded_as <{perfPath}/{performanceID}{formatPlaceholder}#Signal> ;
    meld:offset "{offset}" ;
    rdfs:label "{firstName} {lastName} - {pieceLabel}" .

<{perfPath}/{performanceID}{formatPlaceholder}#Signal> mo:available_as <{recordingUri}/{media}> ;
    mo:time [ a tl:Interval ;
    tl:onTimeLine <{perftl}/{performanceID}{formatPlaceholder}>
] .
""".format( 
        perftl = tlUri,
        firstName = perf_dict["firstName"],
        lastName = perf_dict["lastName"],
        PID = urllib.parse.quote(perf_dict["PID"]),
        pieceLabel = perf_dict["Work"],
        performanceID = perf_dict["PerformanceID"],
        recordingUri = recordingUri,
        media = urllib.parse.quote(perf_dict["mediaName"]),
        perfPath = performancesUri,
        worksUri = worksUri,
        offset = perf_dict["mediaOffset"],
        formatPlaceholder = formatPlaceholder
    )
    return Graph().parse(data = rdf, format='n3')



def graph_to_jsonld(g, extension):
    return json.loads(g.serialize(format='json-ld').decode("utf8").replace(formatPlaceholder, extension))

def graph_to_turtle(g):
    n3String = g.serialize(format='n3').decode("utf8")
    n3String = n3String.replace(formatPlaceholder, ".ttl")
    return n3String

def generate_structural_segmentation(meiFile):
    seg_data = []
    first_note_per_section = {}
    last_note_per_section = {} 
    tree = ET.parse(meiFile)
    root = tree.getroot()
    ns = {'mei': 'http://www.music-encoding.org/ns/mei', 'xml': 'http://www.w3.org/XML/1998/namespace'}
    notes = root.findall('.//mei:note', ns)
    noteIds = [ note.get('{http://www.w3.org/XML/1998/namespace}id') for note in notes ]    
    parentMeasureIterators = [ note.iterancestors(tag='{http://www.music-encoding.org/ns/mei}measure') for note in notes ]
    parentSectionIterators = [ note.iterancestors(tag='{http://www.music-encoding.org/ns/mei}section') for note in notes ]
    for ix, note in enumerate(noteIds):
        noteMeasure = [ measure.get('{http://www.w3.org/XML/1998/namespace}id') for measure in parentMeasureIterators[ix] ] 
        noteSections = [ section.get('{http://www.w3.org/XML/1998/namespace}id') for section in parentSectionIterators[ix] ]
        seg_data.append({ 
            "noteId": note,
            "measure": noteMeasure,
            "section": noteSections
        })
    i = 0
    for obj in seg_data:
        if obj["section"][0] not in first_note_per_section:
            first_note_per_section[obj["section"][0]] = {"first": obj["noteId"], "order":i}
            i+=1
    i=0
    for obj in reversed(seg_data):
        if obj["section"][0] not in last_note_per_section:
            last_note_per_section[obj["section"][0]] = {"last": obj["noteId"], "order":i}
            i+=1
    for n in first_note_per_section:
        first_note_per_section[n]["last"] = last_note_per_section[n]["last"]
        # identify the note IDs for all objects in section n
        first_note_per_section[n]["notes"] = set(list(map(lambda x: x["noteId"], filter(lambda y: n in y["section"], seg_data))))
        # identify the measures for all objects in section n
        first_note_per_section[n]["measures"] = set(list(map(lambda x: x["measure"][0], filter(lambda y: n in y["section"], seg_data))))
    return first_note_per_section

def segmentation_to_graph(seg_data, segUri, meiUri):
    rdf = """@prefix mo: <http://purl.org/ontology/mo/> .
@prefix so: <http://www.linkedmusic.org/ontologies/segment/> .
@prefix frbr: <http://purl.org/vocab/frbr/core#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix meld: <https://meld.linkedmusic.org/terms/> .
@prefix struct: <http://localhost:8080/structure/> .
@prefix WoO80: <http://localhost:8080/segment/WoO80/> .
@base <{segUri}{formatPlaceholder}> .

<{meiUri}> a mo:PublishedScore .

<> a so:SegmentLine .
    """.format(segUri = segUri, meiUri = meiUri, formatPlaceholder = formatPlaceholder)
    for ix, seg in enumerate(seg_data):
        rdf += """<#{segId}> a so:Segment ; 
    so:onSegmentLine <> ;
    meld:order "{ix}" ;
    frbr:embodiment [ a meld:MEIManifestation, rdf:Bag ;
    rdfs:member <{sectionId}> ;
    meld:notes {notes} ;
    meld:measures {measures} ;
    meld:startsWith {first} ;
    meld:endsWith {last} ] {endterm}
    {before}
    {after}""".format(
        ix = ix,
        segUri = segUri,
        segId = seg,
        sectionId = meiUri + "#" + seg,
        first = "<" + meiUri + "#" + seg_data[seg]["first"] + ">",
        last = "<" + meiUri + "#" + seg_data[seg]["last"] + ">",
        # take this segment's map object for notes / measures built up in generate_structural_segmentation
        # convert it to a list
        # iterate through it decorating URI's with comma-separated <>
        # remove the last comma (for valid turtle)
        notes = "".join(["<" + meiUri + "#" + n + ">, " for n in seg_data[seg]["notes"]]).rpartition(", ")[0],
        measures = "".join(["<" + meiUri + "#" + n + ">, " for n in seg_data[seg]["measures"]]).rpartition(", ")[0],
        endterm = ".",
        before = "",
        after = "")
    return Graph().parse(data = rdf, format="n3")


if __name__ == "__main__": 
    parser = argparse.ArgumentParser()
    parser.add_argument('--maps', '-m', help="Path to MAPS result file", required=False)
    parser.add_argument('--segmentlineUri', '-s', help="Score segmentline URI", required=False)
    parser.add_argument('--timelineUri', '-t', help="Performance timeline URI", required=False)
    parser.add_argument('--format', '-f', help="Output format type (ttl, jsonld, both, tpl). tpl will generate a jsonld file without adding a .jsonld suffix to the filename.", required=True)
    parser.add_argument('--timelineOutput', '-o', help="Performance timeline output file name (will be suffixed with .ttl or .jsonld", required=False)
    parser.add_argument('--meiFile', '-e', help="If provided, generate a structural segmentation for the MEI file", required=False)
    parser.add_argument('--meiUri', '-u', help="MEI file URI", required=False)
    parser.add_argument('--segmentlineOutput', '-p', help="Structural segmentation output", required=False)
    parser.add_argument('--solidContainer', '-c', help="Root URI of CLARA folder in user's Solid POD. Replaces --performancesUri and --timelineUri.", required=False)
    parser.add_argument('--performancesFile', '-P', help="Performance metadata TSV file", required=False)
    parser.add_argument('--performancesUri', '-q', help="Prefix URI for generated performances RDF", required=False)
    parser.add_argument('--recordingUri', '-r', help="URI of recorded media directory for these performances", required=False)
    parser.add_argument('--worksUri', '-w', help="Prefix URI for works", required=False)
    parser.add_argument('--includePerformance', '-i', help="Flag to determine whether performance info should be written alongside timeline output", action="store_true")
    parser.add_argument('--scoreUri', '-z', help="Score definition URI; required if includePerforance is true", required=False)
    parser.add_argument('--audioUri', '-a', help="Audio URI; required if includePerforance is true", required=False)

    args = parser.parse_args()


    fName = args.maps if "maps" in args else None
    segUri = args.segmentlineUri if "segmentlineUri" in args else None
    tlUri = args.timelineUri if "timelineUri" in args else None
    outputFormat = args.format if "format" in args else None
    outputFName = args.timelineOutput if "timelineOutput" in args else None
    meiFile = args.meiFile if "meiFile" in args else None
    segmentlineOutput = args.segmentlineOutput if "segmentlineOutput" in args else None
    meiUri = args.meiUri if "meiUri" in args else None
    performancesFile = args.performancesFile if "performancesFile" in args else None
    performancesUri = args.performancesUri if "performancesUri" in args else None
    recordingUri = args.recordingUri if "recordingUri" in args else None
    worksUri = args.worksUri if "worksUri" in args else None
    solidContainer = args.solidContainer if "solidContainer" in args else None
    includePerformance = True if "includePerformance" in args else False
    scoreUri = args.scoreUri if "scoreUri" in args else None 
    audioUri = args.audioUri if "audioUri" in args else None 

    if includePerformance and (scoreUri is None or audioUri is None):
        sys.exit("You must provide each of --scoreUri and --audioUri if includePerformance is requested")
    if solidContainer is not None:
        solidContainer = os.path.join(solidContainer, "")
        performancesUri = os.path.join(solidContainer, "performance", os.path.basename(outputFName))
        tlUri = os.path.join(solidContainer, os.path.basename(outputFName))
        print("2: ", solidContainer, outputFName, tlUri)
    elif performancesUri is not None:
        solidContainer = os.path.dirname(performancesUri)
    if recordingUri is None and solidContainer is not None:
        recordingUri = os.path.join(solidContainer, "recording/")

    if performancesFile is not None:
        if segUri is None or meiUri is None or tlUri is None or recordingUri is None or performancesUri is None or worksUri is None:
            sys.exit("You must provide each of --segmentlineUri, --meiUri, --timelineUri, --performancesUri, --recordingUri, and --worksUri when a performances metadata TSV file is specified")
        #performance TSV file specified, generate performance graph for each row
        performances = performances_to_graphs(performancesFile, segUri, meiUri, tlUri, recordingUri, performancesUri, worksUri)
        for perf in performances:
            if(outputFormat == 'ttl' or outputFormat == 'both'):
                perfTtl = graph_to_turtle(perf["performance"])
                with open("performance/" + perf["performanceID"] + ".ttl", "w") as ttl_file:
                    ttl_file.write(perfTtl)
                    print("Performance description (turtle) written: performance/" + perf["performanceID"] + ".ttl")
                tlTtl = graph_to_turtle(perf["timeline"])
                with open("timeline/" + perf["performanceID"] + ".ttl", "w") as ttl_file:
                    ttl_file.write(tlTtl)
                    print("Performance description (turtle) written: timeline/" + perf["performanceID"] + ".ttl")

            if(outputFormat == 'json' or outputFormat == 'jsonld' or outputFormat == 'tpl' or outputFormat == 'both'):
                extension = '' if outputFormat == 'tpl' else '.jsonld'
                perfJsonld = json.dumps(graph_to_jsonld(perf["performance"], extension), indent=2)
                with open("performance/" + perf["performanceID"] + extension, "w") as json_file:
                    json_file.write(perfJsonld)
                    print("Performance description (json-ld) written: performance/" + perf["performanceID"] + extension)
                tlJsonld = json.dumps(graph_to_jsonld(perf["timeline"], extension), indent=2)
                with open("timeline/" + perf["performanceID"] + extension, "w") as json_file:
                    json_file.write(tlJsonld)
                    print("Performance description (json-ld) written: timeline/" + perf["performanceID"] + extension)

    elif fName is not None:
        # maps result file specified...
        if segUri is None or tlUri is None or meiUri is None or outputFName is None:
            sys.exit("You must provide each of --segmentlineUri, --meiUri, --timelineUri, and --timelineOutput when a MAPS result file is specified")
        if os.path.exists(fName):
            with open(fName, 'rb') as f:
                try: 
                    maps_result_json = f.read()
                except IOError: 
                    print("Could not read file: ", fName)
                    sys.exit()
                g = maps_result_to_graph(maps_result_json, segUri, meiUri, tlUri, scoreUri, audioUri, includePerformance)
                if(outputFormat == 'ttl' or outputFormat == 'both'):
                    ttl = graph_to_turtle(g)
                    with open(outputFName + ".ttl", "w") as ttl_file:
                        ttl_file.write(ttl.decode("utf-8"))
                        print("Performance timeline (turtle) written: " + outputFName + ".ttl")
                if(outputFormat == 'json' or outputFormat == 'jsonld' or outputFormat == 'tpl' or outputFormat == 'both'):
                    extension = '' if outputFormat == 'tpl' else '.jsonld'
                    jsonld = json.dumps(graph_to_jsonld(g, extension), indent=2)
                    with open(outputFName + extension, "w") as json_file:
                        json_file.write(jsonld)
                        print("Performance timeline (json-ld) written: " + outputFName + extension)
        else: 
            print("File does not exist: ", fName)
    if meiFile is not None:
        # mei file specified, generate structural segmentation for it
        if segmentlineOutput is None or segUri is None or meiUri is None:
            sys.exit("You must provide --segmentlineOutput, --segmentlineUri, and --meiUri when a MEI file is specified")
        seg_data = generate_structural_segmentation(meiFile)
        g = segmentation_to_graph(seg_data, segUri, meiUri)
        if(outputFormat == 'ttl' or outputFormat == 'both'):
            ttl = graph_to_turtle(g)
            with open(segmentlineOutput+ ".ttl", "w") as ttl_file:
                ttl_file.write(ttl)
                print("MEI score segmentation (ttl) written: " + segmentlineOutput + ".ttl")
        if(outputFormat == 'json' or outputFormat == 'jsonld' or outputFormat == 'tpl' or outputFormat == 'both'):
            extension = '' if outputFormat == 'tpl' else '.jsonld'
            jsonld = json.dumps(graph_to_jsonld(g, extension), indent=2)
            with open(segmentlineOutput+extension, "w") as json_file:
                json_file.write(jsonld)
                print("MEI score segmentation (json-ld) written: " + segmentlineOutput + extension)
