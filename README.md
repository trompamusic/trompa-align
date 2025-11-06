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
  scores-list
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

scores-list is a schema:ItemList which contains a list of IRIs (URLs).
Use the original URL location where the MEI was loaded from.
You SHOULD NOT create a new score document if its original location is already in this document.
You MUST add a new URL to this list if you add a new score.




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

### Permissions

PUT https://clara.solidcommunity.net/at.ac.mdw.trompa/scores/2abc60da-fe7d-4353-9a9a-63cac4a543e4.acl

FOr public readable
@prefix : <#>.
@prefix acl: <http://www.w3.org/ns/auth/acl#>.
@prefix foaf: <http://xmlns.com/foaf/0.1/>.
@prefix sco: <./>.
@prefix c: </profile/card#>.

:ControlReadWrite
    a acl:Authorization;
    acl:accessTo sco:2abc60da-fe7d-4353-9a9a-63cac4a543e4;
    acl:agent c:me;
    acl:mode acl:Control, acl:Read, acl:Write.
:Read
    a acl:Authorization;
    acl:accessTo sco:2abc60da-fe7d-4353-9a9a-63cac4a543e4;
    acl:agentClass foaf:Agent;
    acl:mode acl:Read.

For private only
@prefix : <#>.
@prefix acl: <http://www.w3.org/ns/auth/acl#>.
@prefix sco: <./>.
@prefix c: </profile/card#>.

:ControlReadWrite
    a acl:Authorization;
    acl:accessTo sco:2abc60da-fe7d-4353-9a9a-63cac4a543e4;
    acl:agent c:me;
    acl:mode acl:Control, acl:Read, acl:Write.



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



Regarding MIDIs / WebMIDIs, we probably should link them from the performance's signal.  Let's use mo:derived_from, which is defined as "a related signal from which the described signal is derived", which is (kind of) applicable.
I would suggest something like this, with all triples inside the performance's ttl file:
<UUID1> a mo:Performance ;
                 mo:recorded_as <UUID1#Signal> .

<UUID1#Signal> a mo:Signal ;
                 mo:available_as <pod-url/path/to/audio/UUID1.mp3> ;
                 mo:derived_from <pod-url/path/to/MIDI/UUID1.mid> .

<pod-url/path/to/MIDI/UUID1.mid> a mo:Signal ;
                mo:derived_from <pod-url/path/to/WebMIDI/UUID1.json> .
---

TODO: What is the difference between POST and PUT for a container>

You can't set additional attributes on a container when you create it, but you can
PATCH it afterwards to add new attributes (according to David)


When selecting a score URL, look at all of the existing scores in the user's pod
and see if one of them is the URL. If so, reuse that score id
 -> This requires enumerating all score objects every single time we add a new URL
    but is an acceptable tradeoff


---
Files to delete - seem to be duplicated
trompa-align-local.R: version of trompa-align.R which outputs results to stdout instead of file
local_alignment_to_maps.py: duplicate code, uses above R file
   -> both should be able to be replaced by better versions of the original code

generate_structure_rdf.py: ??

---

frontend:
When browsing the user's pod for existing item to perform,
Parse dcterms:title for a work title, if it doesn't exist then show serverdomain:filename.mei

Identify all expansions and then when a user is performing something, have a chooser for them to select
 which one they are performing
 -> send the expansion number to server to compute it

Expansions: Beethoven ob35 has A and B part with 15 variations
-> can we compute which appears to be the most correct expansion?

web interface, perform something:
 - list of things in your clara container
 - trompa-music-encodings list
 - input a url

When you select to perform something:
send /add to add an mei file
 - downloads file
 - gets title
 - computes sha256
 - Creates new Container
 - result of task -> returns url to the container

If existing score
 - get Container/performances
 - show list of performances

frontend: Loop, waiting for status
 - Get the structure (used to show where to perform)

frontend: new performance
 - After midi played, create a new webmidi file in the Container for the score
 - Trigger align

/align
 - takes profile, location of container, location of performance, performance id
 - Perform alignment
 - save midi, mp3, alignment, maps file, metadata triples
 - metadata triples are in a separate container - so that we know that everything in here is metadata (makes reading faster)


frontend: list of performances




python scripts/tpl_entrypoint_split_1.py --mei examples/example.mei --performance examples/example-clara-performance-midi.json --audio output.audio --maps output.maps

python scripts/preprocess_mei.py --meiFile examples/example.mei --meiUri http://example.com/example.mei --structureUri http://example.com/example.jsonld --structureOutput example-output.jsonld --midiOutput example-output.mid

python scripts/tpl_entrypoint_split_2.py --maps example-output.maps --performanceUri http://example.com/example.performance --meiUri http://example.com/example.mei --structureUri http://example.com/example.jsonld --audioUri http://example.com/example.audio --outputFilename example-output-align.json



python scripts/solid.py upload-performance https://alastair.trompa-solid.upf.edu/profile/card#me https://alastair.trompa-solid.upf.edu/at.ac.mdw.trompa/99666e85-b53b-4c2d-8523-afdfefadc6ff/ examples/example-clara-performance-midi.json

No title set, trying to get one from the MEI
Creating https://alastair.trompa-solid.upf.edu/at.ac.mdw.trompa/99666e85-b53b-4c2d-8523-afdfefadc6ff/
Created
Uploading file https://alastair.trompa-solid.upf.edu/at.ac.mdw.trompa/99666e85-b53b-4c2d-8523-afdfefadc6ff/Beethoven_WoO70-Breitkopf.mei