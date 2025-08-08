# trompa-align (clara)

This is the backend for the clara application: https://github.com/trompamusic/clara
It provides background processing tasks for clara. To do this, it has the ability to
authenticate and connect to a user's Solid pod, reading from and writing to this location.

This repository contains a collection of scripts that are used to align MIDI piano performances with MEI score encodings, converting the alignment information to Linked Data for use with the [CLARA Companion for Long-term Analyses of Rehearsal Attempts](https://github.com/trompamusic/clara).

The MEI score is synthesised to MIDI using [Verovio](https://verovio.org). The resulting MIDI file is then aligned with the performance MIDI using the [Symbolic Music Alignment Tool](https://midialignment.github.io/demo.html) by Nakamura et al. The MIDI-to-MIDI alignment is then reanchored within MEI using a [script](scripts/trompa-align.R) which attempts to reconcile timestamps and pitch heights determined in Verovio and Nakamura (corresp) output; this is not entirely trivial due to differences in precision and rounding between the two tools.

The result of this reconciliation is stored in the MAPS output format, from where it can be converted to RDF for use in CLARA.

Further documentation to come -- ***below notes are provisional and not necessarily suitable for public consumption!*** For futher information contact weigl at mdw.ac.at

## Setup
It's easier to run the app in Docker, as there is a component which requires R, and some 
other external software. Building this is taken care of automatically by the Dockerfile.

    docker compose build web

    docker compose up

## Configuration

If you are using docker, copy the `.env.example` file to `env.docker`. If running locally, copy to `.env`.
If you're running in docker, most of these options don't need to be changed.

In order to provide a seamless experience to users, we take advantage of Solid [Client ID Documents](https://solidproject.org/TR/oidc#clientids-document). This means that there must be a public URL pointing to
the client id document. This document is served at http://localhost:8000/clara.jsonld

Public SOLID servers must be able to load this document from the internet, so for local development you will 
need a tunnel service such as ngrok. The free version is sufficient, but requires separate configuration 
each time that you run it. Run:

    ngrok http 8000

And take note of the public domain name. It will be something like https://f9da16955d31.ngrok-free.app

> Danger: After doing this, trompa-align will be publicly available on the internet. The ngrok url _should_ be
> undiscoverable, but there is a small risk that someone may access it. Be careful!

Update `.env` to include

    CONFIG_BASE_URL=https://your-id.ngrok-free.app
    CLIENT_ID_DOCUMENT_URL=https://your-id.ngrok-free.app/clara.jsonld

TODO: Some Solid providers are not fully compliant with the Solid specification and do not support Client ID Documents. In this case, we should
  perform the "dynamic registration" step and create a new client for the backend, requesting user permission. While this isn't ideal, because 
  the user needs to authorize two separate applications, it should still work.


## Initial app setup

Create the database

    flask db create-database


## Testing scripts

We provide a CLI that allows you to perform all steps of the clara workflow.

In these commands, `USERS-PROFILE` is the URL to the web id of a user who has been 
authenticated by this app to act on the user's behalf

### general solid commands

Upload any file to a pod

    flask solid add-turtle USERS-PROFILE RESOURCE-ON-POD LOCAL-FILE

Run HTTP OPTIONS on a file

    flask solid options USERS-PROFILE RESOURCE-ON-POD

Delete a file

    flask solid delete USERS-PROFILE RESOURCE-ON-POD

Get the contents of a container. Specify to get the response in turtle or json-ld with `--ttl` or `--json`

    flask solid list-container USERS-PROFILE CONTAINER-ON-POD

Recursively list a user's entire pod

    flask solid list-pod USERS-PROFILE

Use HTTP PATCH to set `dcterms:title` on a resource

    flask solid patch-title USERS-PROFILE CONTAINER ITEM TITLE

Get a file as json-ld or turtle (use `--ttl` or `--json`)

    flask solid get-resource USERS-PROFILE RESOURCE

Get a file with no requested content-type

    flask solid get-file USERS-PROFILE RESOURCE


### clara steps

Create the base clara structure in a user's pod:

    flask solid create-clara USERS-PROFILE

Recursively delete the clara structure

    flask solid create-clara USERS-PROFILE

List all items in the clara container (specific version of `list-container`)

    flask solid list-clara USERS-PROFILE

Upload an MEI score to a pod. Use either --url to download a score from a url and upload it, or --file to upload a local file.
Specify --title to override a title, otherwise it is read from the MEI file

    flask solid upload-score USERS-PROFILE

Upload a performance of a score, either as a midi file or a webmidi file

    flask solid upload-midi USERS-PROFILE FILE
    flask solid upload-webmidi USERS-PROFILE FILE

Find the score container for a given score external URL

    flask solid get-score-for-url USERS-PROFILE FILE

Run the alignment process

    flask solid get-score-for-url USERS-PROFILE SCORE_URL MIDI_URL


## Development notes

Here are some notes about the implementation details about how we structure and store this data

File structure:

```
at.ac.mdw.trompa/
  scores/
     contains score documents
  mei/
     contains local copies of MEI files
  performances/
    scoreuuid1/
      performance1uuid
      performance2uuid
    scoreuuid2/
      performance1uuid
      performance2uuid
  audio/
     contains generated audio files
timelines/
     contains
  midi/
     contains midi (uploaded or generated from webmidi)
  webmidi/
     contains uploaded webmidi files
```


A "score" is a triple document containing:
 - Metadata about the score (title, location of original MEI file online, location of our copy)
 - Information about segments in the MEI file

A "performance" is a triple document containing:
 * mo:performance_of to their Scores
 * rdfs:label to their labels
 * mo:recorded_as to their Signals

Contexts for the below:
```
mo: <http://purl.org/ontology/mo/>
meld: <https://meld.linkedmusic.org/terms/>
skos: <http://www.w3.org/2004/02/skos/core#>
tl: <http://purl.org/NET/c4dm/timeline.owl#>
```

Scores are:
* mo:published_as to their MEI files,
* meld:segments to their segment lines
* dcterms:title the title of the composition

MEI copies are:
* skos:exactMatch to their MEI files (<- those triples live in the Score definition though)

Performances are:
* mo:performance_of to their Scores
* rdfs:label to their labels
* mo:recorded_as to their Signals


Signals are:
* mo:available_as to their MP3s
* mo:time to their Intervals

Intervals are:
* tl:onTimeLine to their Timelines

### file formats

**TTL or json-ld?**

Meld consumes JSON-LD. If the structure file is TTL and you request `Content-Type: application/ld+json` 
from a server, then the server will convert it on the fly, causing load on the server. We've had informal
"complaints" from some pod proviers that this was causing undue load. So, save this file as JSON-LD.
Most other files are TTL, just simply because it's "nicer to write", and the files are very small.

## Other notes

These notes are from an older version of this readme and have not been cleaned up

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
