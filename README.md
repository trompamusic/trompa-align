TO INSTALL
1. Rscript scripts/install-packages.R 
2. pip install -r requirements.txt
3. Install the Symbolic Music Alignment Tool (SMAT):
    * Download the latest version (zip file) from https://midialignment.github.io/demo.html 
    * Unzip it and store the absolute path as `SMAT_PATH`
    * Compile it with: `cd SMAT_PATH; ./compile.sh`

TO RUN

First, prepare environment variables:
    `export SMAT_PATH=/local/path/to/SMAT` (as in installation step 3)
    `export PERFORMANCE_MIDI=/local/path/to/performance.midi`
    `export CANONICAL_MIDI=/local/path/to/canonical.midi` (file content generated in step 1: mei-to-midi)
    `export CORRESP_FILE=/local/path/to/correspFile` (file content generated in step 2: SMAT-alignment)
    `export MAPS_FILE=/local/path/to/mapsFile` (file content generated in step 3: MIDI-to-MEI reconciliation)
    `export LD_OUT=/local/path/to/timeline/rdf/outputFile.jsonld` (file content generated in step 4: MAPS-to-RDF conversion)
    `export MEI_URI=http://uri.of.my/meiFile.mei`  (URI of MEI file being performed)
    `export STRUCTURE_URI=http://uri.of.my/meiFile_structure.jsonld` (generated in a separate TPL task on ingest of a new MEI file to CE)
    `export SOLID_CLARA_BASE=http://users.solid.pod/path/to/clara.trompamusic.folder/` (URI of CLARA folder in user's Solid POD)
    
TO RUN THE FULL ALIGNMENT-WORKFLOW: (from the trompa-align root directory):

`python scripts/performance_alignment_workflow.py --smatPath $SMAT_PATH --meiUri $MEI_URI --structureUri $STRUCTURE_URI --performanceMidi $PERFORMANCE_MIDI --timelineOutput $LD_OUT --solidClaraBaseUri $SOLID_CLARA_BASE`

If successful, your output should be available at $LD_OUT. 

TO RUN EACH STAGE OF THE WORKFLOW: (from the trompa-align root directory):

1. Generate canonical MIDI from web-hosted MEI: 
  `python scripts/mei-to-midi.py --meiUri $MEI_URI --output $CANONICAL_MIDI`
  
2. Use SMAT to align the canonical MIDI with your performance MIDI, generating a corresp file:
  
  `python scripts/smat-align.py -s $SMAT_PATH -c $CANONICAL_MIDI -p $PERFORMANCE_MIDI -o $CORRESP_FILE`

3. Perform MIDI-to-MEI reconciliation, yielding a MAPS file:

  `Rscript scripts/trompa-align.R $CORRESP_FILE $MAPS_FILE $MEI_URI` 

4. Convert the MAPS file to performance and timeline RDF

  `python scripts/convert_to_rdf.py -m $MAPS_FILE -c $SOLID_ROOT -u $MEI_URI -f tpl -s $STRUCTURE_URI -o $LD_OUT` 




# trompa-align

This repository contains a collection of scripts that are used to align MIDI piano performances with MEI score encodings, converting the alignment information to Linked Data for use with the [CLARA Companion for Long-term Analyses of Rehearsal Attempts](https://github.com/trompamusic/clara). 

The MEI score is synthesised to MIDI using [Verovio](https://verovio.org). The resulting MIDI file is then aligned with the performance MIDI using the [Symbolic Music Alignment Tool](https://midialignment.github.io/demo.html) by Nakamura et al. The MIDI-to-MIDI alignment is then reanchored within MEI using a [script](scripts/trompa-align.R) which attempts to reconcile timestamps and pitch heights determined in Verovio and Nakamura (corresp) output; this is not entirely trivial due to differences in precision and rounding between the two tools. 

The result of this reconciliation is stored in the MAPS output format, from where it can be converted to RDF for use in CLARA. 

Further documentation to come -- ***below notes are provisional and not necessarily suitable for public consumption!*** For futher information contact weigl at mdw.ac.at


****



Install:
* Rscript scripts/install-packages.R 
* pip install -r requirements.txt



To ingest a new piece:

0. Separate the master MidiOffsets-in-Mediafiles-named.tsv by work (only needs to be done once):
`Rscript scripts/split-performance-offsets-by-work.R MidiOffsets-in-Mediafiles-named.tsv offsets/`

1. Generate Nakamura corresp files for performances of the chosen piece. Throw them in a directory and run the Nakamura corresps -> MAPS object conversion (with Verovio-alignment)
  `Rscript scripts/trompa-align.R Op126Nr3-corresp/ Beethoven_Op126Nr3.mei`

2. Generate structural segmentation (currently by section) for your chosen MEI file: 
e.g.: 
  `python scripts/convert_to_rdf.py --meiFile Beethoven_Op126Nr3.mei --meiUri http://localhost:8080/Beethoven_Op126Nr3.mei --segmentlineOutput Op126Nr3 --segmentlineUri http://localhost:8080/structure/Op126Nr3 --format both`

Copy the resulting file(s) (here, `Op126Nr3.ttl` and `Op126Nr.json`) to the appropriate place (where they will be served by your webserver)
e.g.:
  `cp Op126Nr3.json ~/meld-repos/variations/structure`

3. Generate performance and timeline RDF for the corresponding piece:
e.g.:
`python scripts/convert_to_rdf.py -f both -P offsets/Op126Nr3.tsv -t http://localhost:8080/timeline -s http://localhost:8080/structure -r http://localhost:8080/videos/BeethovenWettbewerb -q http://localhost:8080/performance -w http://localhost:8080/score -u http://localhost:8080/Beethoven_Op126Nr3.mei` 

Copy the resulting files to the appropriate place
e.g.:
  `cp performance/*.json ~/meld-repos/variations/performance/`
  `cp timeline/*.json ~/meld-repos/variations/timeline/`


4. Create a performance container to point the MELD application to (see e.g. ~/meld-repos/variations/performance/Opus126Nr3.json)



#TODO Provide additional detail:
- Creating performance container (or automate!)
- Creating score RDF (or automate!)
- Adding to score selection dropdown 
