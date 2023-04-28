import json
import os
import tempfile
import uuid

import rdflib
import requests
from celery import shared_task
from rdflib import URIRef

from scripts.midi_events_to_file import midi_json_to_midi
from scripts.performance_alignment_workflow import perform_workflow
from trompaalign.solid import lookup_provider_from_profile, get_storage_from_profile, get_clara_listing_for_pod, \
    create_clara_container, upload_mei_to_pod, \
    get_title_from_mei, create_and_save_structure, get_resource_from_pod, CLARA_CONTAINER_NAME, MO, RDF


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

    clara_container = get_clara_listing_for_pod(provider, profile, storage)
    if clara_container is None:
        create_clara_container(provider, profile, storage)

    r = requests.get(mei_external_uri)
    r.raise_for_status()
    payload = r.text

    title = get_title_from_mei(payload)
    mei_copy_uri = upload_mei_to_pod(provider, profile, storage, payload)

    create_and_save_structure(provider, profile, storage, title, payload, mei_external_uri, mei_copy_uri)



@shared_task()
def align_recording(profile, score_url, webmidi_url, performance_container):
    """

    :param profile:
    :param score_url: the URL of our "score" RDF document
    :param webmidi_url:
    :param performance_container:
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
        graph.parse(data=score, format='n3')
        """
        <uuid> a mo:Score ;
      mo:published_as <external URL> ;
      """
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
            print(f"Cannot find external location of MEI file given the score resource {score_url}")
            return
        webmidi = get_resource_from_pod(provider, profile, webmidi_url)
        mei_content = get_resource_from_pod(provider, profile, external_mei_url)

        mei_file = os.path.join(td, "score.mei")
        with open(mei_file, "wb") as fp:
            fp.write(mei_content)

        midi = midi_json_to_midi(json.loads(webmidi.decode("utf-8")))
        midi_file = os.path.join(td, "performance.mid")
        midi.save(midi_file)
        # upload midi

        # TODO: This is done by perform_workflow, I think
        # mp3_file = os.path.join(td, "performance.mp3")
        # midi_to_mp3(midi_file, mp3_file, td)
        # upload audio

        expansion = None
        audio_container = os.path.join(clara_container, "audio")
        perf_fname = str(uuid.uuid4())
        audio_fname = str(uuid.uuid4()) + '.mp3'
        perform_workflow(midi_file, mei_file, expansion, external_mei_url, score_url, performance_container,
                         audio_container, td, perf_fname, audio_fname)

        performance = json.load(open(os.path.join(td, perf_fname)))
        # print(performance)
        performance_resource = os.path.join(performance_container, perf_fname)
        print(f"Performance resource: {performance_resource}")

        files = os.listdir(td)
        print(f"Files in temp dir {td}")
        for f in files:
            print(f" - {f}")

        # save timeline
        # save performance manifest
        # save audio
        # save midi
