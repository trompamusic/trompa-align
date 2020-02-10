# trompa-align

This repository contains a collection of scripts that are used to align MIDI piano performances with MEI score encodings, converting the alignment information to Linked Data for use with the [https://github.com/trompamusic/clara](CLARA Companion for Long-term Analyses of Rehearsal Attempts). 

The MEI score is synthesised to MIDI using [https://verovio.org](Verovio). The resulting MIDI file is then aligned with the performance MIDI using the [https://midialignment.github.io/demo.html](Symbolic Music Alignment Tool) by Nakamura et al. The MIDI-to-MIDI alignment is then reanchored within MEI using a [scripts/trompa-align.R](script) which attempts to reconcile timestamps and pitch heights determined in Verovio and Nakamura (corresp) output; this is not entirely trivial due to differences in precision and rounding between the two tools. 

The result of this reconciliation is stored in the MAPS output format, from where it can be converted to RDF for use in CLARA. 

Further documentation to come -- below notes are provisional and not necessarily suitable for public consumption! For futher information contact weigl at mdw.ac.at


####



Install:
* Rscript scripts/install-packages.R 
* Build verovio with python hooks
    - requires install of python-devel and swig, 
* pip install rdflib rdflib-jsonld



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
