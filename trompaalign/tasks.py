import json
import os
import tempfile
import urllib.error
import uuid

import rdflib
import requests
from celery import shared_task
from rdflib import URIRef, RDF, SKOS

from scripts.convert_to_rdf import graph_to_turtle, graph_to_jsonld
from scripts.midi_events_to_file import midi_json_to_midi
from scripts.namespace import MO
from scripts.performance_alignment_workflow import perform_workflow
from trompaalign.mei import get_metadata_for_mei, mei_is_valid
from trompaalign.solid import (
    lookup_provider_from_profile,
    get_storage_from_profile,
    create_clara_container,
    upload_mei_to_pod,
    get_title_from_mei,
    create_and_save_structure,
    get_resource_from_pod,
    CLARA_CONTAINER_NAME,
    get_pod_listing,
    upload_midi_to_pod,
    upload_mp3_to_pod,
    save_performance_manifest,
    save_performance_timeline,
    SolidError,
)


class NoSuchScoreException(Exception):
    pass


class NoSuchPerformanceException(Exception):
    pass


@shared_task(ignore_result=False)
def add_score(profile, mei_external_uri):
    """
    To add a score, we have the following possible methods:
      1. download the MEI from the browser, then create the Container in the browser, compute structure in the browser,
         upload MEI + Structure
      2. download MEI in the browser, create the container + upload the MEI and then trigger a backend python task
         which downloads the MEI, computes the structure, and uploads it
      3. trigger a backend command from the browser, which creates the container, downloads the MEI, computes the
         structure, uploads them both, and returns the URI of the new Container to the browser

    The structure is necessary before the first rehearsal. It's a summary of some of the data in the MEI file, in
    json-ld format.
    As we have existing code in python to compute structure and make containers/upload files, 3 is easiest,
    but if for example the specified MEI doesn't have a title, we can't prompt the user to enter something.
    Eventually we might want to move to 1. to have a more flexible process

    :param profile:
    :param mei_external_uri:
    :return:
    """
    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return
    storage = get_storage_from_profile(profile)
    if not storage:
        print("Cannot find storage, quitting")
        return

    try:
        clara_container = get_pod_listing(provider, profile, storage)
    except urllib.error.HTTPError as e:
        if e.status == 404:
            create_clara_container(provider, profile, storage)

    r = requests.get(mei_external_uri)
    r.raise_for_status()
    payload = r.text

    is_valid = mei_is_valid(payload)
    if not is_valid:
        raise SolidError("MEI file is not valid")

    filename = os.path.basename(mei_external_uri)
    title = get_title_from_mei(payload, filename)
    mei_copy_uri = upload_mei_to_pod(provider, profile, storage, payload)

    return create_and_save_structure(provider, profile, storage, title, payload, mei_external_uri, mei_copy_uri)


@shared_task(ignore_result=False)
def align_recording(profile, score_url, webmidi_url, midi_url):
    """

    :param profile:
    :param score_url: the URL of our "score" RDF document
    :param webmidi_url: The URL of the uploaded webmidi file, or None if there is only a midi file
    :param midi_url: should be set only if webmidi is None
    :return:
    """

    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return
    storage = get_storage_from_profile(profile)
    if not storage:
        print("Cannot find storage, quitting")
        return

    clara_container = os.path.join(storage, CLARA_CONTAINER_NAME)

    with tempfile.TemporaryDirectory() as td:
        score = get_resource_from_pod(provider, profile, score_url)
        graph = rdflib.Graph()
        graph.parse(data=score, format="n3")
        # e.g., find all triples where `<someuri> a mo:score`
        # triples = list(graph.triples((None, RDF.type, MO.Score)))
        # However, we know what the someuri is, it's score_url
        # TODO: Does this correctly resolve relative/absolute?
        uri_ref = URIRef(score_url)
        triples = list(graph.triples((uri_ref, MO.published_as, None)))
        if triples:
            external_mei_url = triples[0][2]
            print(f"External MEI file is {external_mei_url}")
        else:
            raise NoSuchScoreException(
                f"Cannot find external location of MEI file given the score resource {score_url}"
            )

        triples = list(graph.triples((uri_ref, SKOS.related, None)))
        if triples:
            performance_container = triples[0][2]
            # TODO: Should the timeline container be related to the score too?
            performance_uuid = str(performance_container).split("/")[-2]
            timeline_container = os.path.join(clara_container, "timelines", performance_uuid)
            print(f"Performance container is {performance_container}")
            print(f"Timeline container is {timeline_container}")
        else:
            raise NoSuchPerformanceException(
                f"Cannot find location of performance container given the score resource {score_url}"
            )

        mei_content = get_resource_from_pod(provider, profile, external_mei_url)

        mei_file = os.path.join(td, "score.mei")
        with open(mei_file, "wb") as fp:
            fp.write(mei_content)

        if webmidi_url is not None:
            print("Converting webmidi to midi and uploading")
            webmidi = get_resource_from_pod(provider, profile, webmidi_url)
            midi = midi_json_to_midi(json.loads(webmidi.decode("utf-8")))
            midi_file = os.path.join(td, "performance.mid")
            midi.save(midi_file)
            midi_url = upload_midi_to_pod(provider, profile, storage, open(midi_file, "rb").read())
        else:
            print("only got a midi URL, using it directly")
            midi_contents = get_resource_from_pod(provider, profile, midi_url)
            midi_file = os.path.join(td, "performance.mid")
            with open(midi_file, "wb") as fp:
                fp.write(midi_contents)

        expansion = None
        audio_container = os.path.join(clara_container, "audio")
        perf_fname = str(uuid.uuid4())
        audio_fname = str(uuid.uuid4()) + ".mp3"
        performance_graph, timeline_graph = perform_workflow(
            midi_file,
            mei_file,
            expansion,
            external_mei_url,
            score_url,
            performance_container,
            timeline_container,
            audio_container,
            td,
            perf_fname,
            audio_fname,
        )

        performance_resource = os.path.join(performance_container, perf_fname)
        print(f"Performance resource: {performance_resource}")
        timeline_resource = os.path.join(timeline_container, perf_fname)
        print(f"Timeline resource: {timeline_resource}")

        audio_resource = os.path.join(audio_container, audio_fname)
        mp3_uri = upload_mp3_to_pod(provider, profile, audio_resource, open(os.path.join(td, audio_fname), "rb").read())

        # Add triples for Signal->Midi and Midi->webmidi
        performance_graph.add((URIRef(midi_url), RDF.type, MO.Signal))
        performance_signal_ref = URIRef(f"{performance_resource}#Signal")
        performance_graph.add((performance_signal_ref, RDF.type, MO.Signal))
        performance_graph.add((performance_signal_ref, MO.available_as, URIRef(mp3_uri)))
        performance_graph.add((performance_signal_ref, MO.derived_from, URIRef(midi_url)))
        if webmidi_url:
            performance_graph.add((URIRef(midi_url), MO.derived_from, URIRef(webmidi_url)))

        performance_document = graph_to_turtle(performance_graph)
        timeline_document = graph_to_jsonld(timeline_graph, mei_uri=external_mei_url, tl_uri=timeline_resource)

        save_performance_manifest(provider, profile, performance_resource, performance_document)
        save_performance_timeline(provider, profile, timeline_resource, timeline_document)

    return True
