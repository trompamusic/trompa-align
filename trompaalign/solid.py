import io
import json
import logging
import os
import uuid
from urllib.error import HTTPError

import rdflib
import requests
import requests.utils
from pyld import jsonld
from rdflib import URIRef

from scripts.convert_to_rdf import generate_structural_segmentation, score_to_graph, segmentation_to_graph
from scripts.namespace import MO
from trompaalign.mei import get_metadata_for_mei

logger = logging.getLogger(__name__)


class SolidError(Exception):
    pass


jsonld_context = {
    "mo": "http://purl.org/ontology/mo/",
    "dcterms": "http://purl.org/dc/terms/",
    "ldp": "http://www.w3.org/ns/ldp#",
    "stat": "http://www.w3.org/ns/posix/stat#",
    "mime": "http://www.w3.org/ns/iana/media-types/",
    "schema": "https://schema.org/about/",
    "oa": "http://www.w3.org/ns/oa",
}


CLARA_CONTAINER_NAME = "at.ac.mdw.trompa/"


def http_options(solid_client, provider, profile, container):
    headers = solid_client.get_bearer_for_user(provider, profile, container, "OPTIONS")
    r = requests.options(container, headers=headers)
    r.raise_for_status()
    return r.headers, r.content


def get_pod_listing(solid_client, provider, profile, storage):
    headers = solid_client.get_bearer_for_user(provider, profile, storage, "GET")
    data, headers = get_uri_jsonld(storage, headers)
    if data is not None:
        compact = jsonld.compact(data, jsonld_context)
        return compact
    else:
        return None


def get_pod_listing_ttl(solid_client, provider, profile, storage):
    headers = solid_client.get_bearer_for_user(provider, profile, storage, "GET")
    return get_uri_ttl(storage, headers)


def patch_container_item_title(solid_client, provider, profile, container, item, title):
    """
    TODO: Trying to follow the sparkql-update syntax at https://www.w3.org/TR/2013/REC-sparql11-update-20130321/#insertData
     to add another triple to a container.
    however, when including the PREFIX syntax, node-solid-server fails with [including spelling error]
        Patch document syntax error: Line 1 of <https://alastair.trompa-solid.upf.edu/at.ac.mdw.trompa/scores/>: Bad syntax:
        Unknown syntax at start of statememt: 'PREFIX dcterms: <htt'
    The rdflib js parser doesn't support PREFIX: https://github.com/linkeddata/rdflib.js/blob/c5bcd95/src/patch-parser.js#L11

    When inlining the relation, it fails with
        Original file read error: Error: EISDIR: illegal operation on a directory, read

    This appears to be because nss stores containers as directories on disk, and it can't store any additional
    data related to the container other than the filesystem data (date created, etc)
    """

    headers = solid_client.get_bearer_for_user(provider, profile, container, "PATCH")
    type_headers = {"Accept": "text/turtle", "content-type": "application/sparql-update"}
    headers.update(type_headers)

    update_data = f"""INSERT DATA
{{
  <{item}> <http://purl.org/dc/terms/title> "{title}" .
}}"""

    r = requests.patch(container, data=update_data, headers=headers)
    r.raise_for_status()
    print(r.text)
    print(f"Status: {r.status_code}")


def get_contents_of_container(container, container_name):
    contents = []
    for item in container["@graph"]:
        # This returns 1 item for the actual url, which has ldp:contains: [list, of items]
        # but then also enumerates the list of items
        if item["@id"] == container_name:
            contains = item.get("ldp:contains")
            if not contains:
                return []
            if not isinstance(contains, list):
                contains = [contains]
            for cont in contains:
                contents.append(cont["@id"])
    return contents


def get_resource_from_pod(solid_client, provider, profile, uri, accept=None):
    headers = solid_client.get_bearer_for_user(provider, profile, uri, "GET")
    if accept:
        headers.update({"Accept": accept})
    r = requests.get(uri, headers=headers)
    r.raise_for_status()
    return r.content


def create_clara_container(solid_client, provider, profile, storage):
    clara_container = os.path.join(storage, CLARA_CONTAINER_NAME)
    headers = solid_client.get_bearer_for_user(provider, profile, clara_container, "PUT")
    container_payload = {
        "@type": [
            "http://www.w3.org/ns/ldp#BasicContainer",
            "http://www.w3.org/ns/ldp#Container",
            "http://www.w3.org/ns/ldp#Resource",
        ],
        "@id": clara_container,
    }
    type_headers = {"Accept": "application/ld+json", "content-type": "application/ld+json"}
    headers.update(type_headers)
    r = requests.put(clara_container, data=json.dumps(container_payload), headers=headers)
    if r.status_code == 201:
        print("Successfully created")
    else:
        print(f"Unexpected status code: {r.status_code}: {r.text}")


def lookup_provider_from_profile(profile_url: str):
    """

    :param profile_url: The profile of the user, e.g.  https://alice.coolpod.example/profile/card#me
    :return:
    """

    r = requests.options(profile_url)
    r.raise_for_status()
    links = r.headers.get("Link")
    if links:
        parsed_links = requests.utils.parse_header_links(links)
        for l in parsed_links:
            if l.get("rel") == "http://openid.net/specs/connect/1.0/issuer":
                return l["url"]

    # If we get here, there was no rel in the options. Instead, try and get the card
    # and find its issuer
    graph = rdflib.Graph()
    try:
        graph.parse(profile_url)
        issuer = rdflib.URIRef("http://www.w3.org/ns/solid/terms#oidcIssuer")
        triples = list(graph.triples([None, issuer, None]))
        if triples:
            # first item in the response, 3rd item in the triple
            return triples[0][2].toPython()
    except HTTPError as e:
        if e.status == 404:
            print("Cannot find a profile at this url")
        else:
            raise e


def get_title_from_mei(payload, filename):
    metadata = get_metadata_for_mei(payload)
    if metadata:
        title = ""
        if metadata["title"]:
            title += metadata["title"]
        if metadata["composer"]:
            title += " - " + metadata["composer"]
        if title:
            return title
    else:
        return filename


def upload_mei_to_pod(solid_client, provider, profile, storage, payload):
    resource = os.path.join(storage, CLARA_CONTAINER_NAME, "mei", str(uuid.uuid4()) + ".mei")
    print(f"Uploading file {resource}")
    headers = solid_client.get_bearer_for_user(provider, profile, resource, "PUT")
    # TODO: Should this be an XML mimetype, or a specific MEI one?
    headers["content-type"] = "application/xml"
    r = requests.put(resource, data=payload.encode("utf-8"), headers=headers)
    r.raise_for_status()
    print(r.text)
    return resource


def upload_webmidi_to_pod(solid_client, provider, profile, storage, payload: bytes):
    # TODO: This duplicates many other methods, could be simplified
    resource = os.path.join(storage, CLARA_CONTAINER_NAME, "webmidi", str(uuid.uuid4()) + ".json")
    print(f"Uploading webmidi file to {resource}")
    headers = solid_client.get_bearer_for_user(provider, profile, resource, "PUT")
    headers["content-type"] = "application/json"
    r = requests.put(resource, data=payload, headers=headers)
    r.raise_for_status()
    print("status:", r.text)
    return resource


def upload_midi_to_pod(solid_client, provider, profile, storage, payload: bytes):
    resource = os.path.join(storage, CLARA_CONTAINER_NAME, "midi", str(uuid.uuid4()) + ".mid")
    print(f"Uploading midi file to {resource}")
    headers = solid_client.get_bearer_for_user(provider, profile, resource, "PUT")
    headers["content-type"] = "audio/midi"
    r = requests.put(resource, data=payload, headers=headers)
    r.raise_for_status()
    print("status:", r.text)
    return resource


def upload_mp3_to_pod(solid_client, provider, profile, resource, payload: bytes):
    print(f"Uploading mp3 file to {resource}")
    headers = solid_client.get_bearer_for_user(provider, profile, resource, "PUT")
    headers["content-type"] = "audio/mpeg"
    r = requests.put(resource, data=payload, headers=headers)
    r.raise_for_status()
    print("status:", r.text)
    return resource


def find_score_for_external_uri(solid_client, provider, profile, storage, mei_external_uri):
    resource = os.path.join(storage, CLARA_CONTAINER_NAME, "scores/")
    score_listing = get_pod_listing(solid_client, provider, profile, resource)
    contents = get_contents_of_container(score_listing, resource)
    for item in contents:
        file = get_resource_from_pod(solid_client, provider, profile, item)
        graph = rdflib.Graph()
        graph.parse(file)
        matches = list(graph.triples((None, MO.published_as, URIRef(mei_external_uri))))
        if len(matches):
            return item


def create_and_save_structure(
    solid_client, provider, profile, storage, title, mei_payload: str, mei_external_uri, mei_copy_uri
):
    """A 'score' is an RDF document that describes an MEI file and the segments that we generate

    <uuid> a mo:Score ;
      mo:published_as <external URL> ;
      meld:segments <pod-url/path/to/segments/file.ttl> .

    <pod-url/path/to/MEI/copy.mei> a mo:PublishedScore ;
      skos:exactMatch <external URL>.

    TODO: We don't need to create a new structure if we already have one for this mei_external_uri
    """

    score_id = str(uuid.uuid4())
    score_resource = os.path.join(storage, CLARA_CONTAINER_NAME, "scores", score_id)
    segment_resource = os.path.join(storage, CLARA_CONTAINER_NAME, "segments", score_id)
    # Multiple performances for a score, so it ends in a / to make it a container
    performance_resource = os.path.join(storage, CLARA_CONTAINER_NAME, "performances", score_id, "")
    timeline_resource = os.path.join(storage, CLARA_CONTAINER_NAME, "timelines", score_id, "")

    mei_io = io.BytesIO(mei_payload.encode("utf-8"))
    mei_io.seek(0)

    segmentation = generate_structural_segmentation(mei_io)
    segmentation_graph = segmentation_to_graph(segmentation, segment_resource)
    score_graph = score_to_graph(
        score_resource, segment_resource, performance_resource, mei_external_uri, mei_copy_uri, title
    )

    segmentation_data = segmentation_graph.serialize(format="n3", encoding="utf-8")
    score_data = score_graph.serialize(format="n3", encoding="utf-8")

    print("Making performance container:", performance_resource)
    headers = solid_client.get_bearer_for_user(provider, profile, performance_resource, "PUT")
    r = requests.put(performance_resource, headers=headers)
    r.raise_for_status()
    print(r.text)

    print("Making timeline container:", timeline_resource)
    headers = solid_client.get_bearer_for_user(provider, profile, timeline_resource, "PUT")
    r = requests.put(timeline_resource, headers=headers)
    r.raise_for_status()
    print(r.text)

    print("Making score:", score_resource)
    headers = solid_client.get_bearer_for_user(provider, profile, score_resource, "PUT")
    headers["content-type"] = "text/turtle"
    r = requests.put(score_resource, data=score_data, headers=headers)
    r.raise_for_status()
    print(r.text)

    print("Making segment:", segment_resource)
    headers = solid_client.get_bearer_for_user(provider, profile, segment_resource, "PUT")
    headers["content-type"] = "text/turtle"
    r = requests.put(segment_resource, data=segmentation_data, headers=headers)
    r.raise_for_status()
    print(r.text)

    return score_resource


def get_uri_jsonld_or_none(uri, headers=None):
    try:
        return get_uri_jsonld(uri, headers)
    except requests.exceptions.HTTPError as e:
        print("Error", e)
        print(" message:", e.response.text)
        return None, None


def get_uri_jsonld(uri, headers=None):
    if not headers:
        headers = {}
    headers.update({"Accept": "application/ld+json"})
    r = requests.get(uri, headers=headers)
    r.raise_for_status()
    logger.debug("Get json-ld from %s", uri)
    logger.debug("json-ld headers: %s", r.headers)
    logger.debug("json-ld content: %s", json.dumps(r.json(), indent=2))
    return r.json(), r.headers


def get_uri_ttl(uri, headers=None):
    if not headers:
        headers = {}
    headers.update({"Accept": "text/turtle"})
    r = requests.get(uri, headers=headers)
    r.raise_for_status()
    return r.text


def get_storage_from_profile(profile_uri):
    graph = rdflib.Graph()
    graph.parse(profile_uri)
    storage = graph.value(
        subject=rdflib.URIRef(profile_uri), predicate=rdflib.URIRef("http://www.w3.org/ns/pim/space#storage")
    )
    if storage is None:
        print("No storage found")
        return None
    return storage.toPython()


def save_performance_manifest(solid_client, provider, profile, performance_uri, manifest):
    print(f"Uploading manifest to {performance_uri}")
    headers = solid_client.get_bearer_for_user(provider, profile, performance_uri, "PUT")
    headers["content-type"] = "text/turtle"
    r = requests.put(performance_uri, data=manifest, headers=headers)
    r.raise_for_status()
    print("status:", r.text)


def save_performance_timeline(solid_client, provider, profile, timeline_uri, timeline):
    print(f"Uploading timeline to {timeline_uri}")
    headers = solid_client.get_bearer_for_user(provider, profile, timeline_uri, "PUT")
    headers["content-type"] = "application/ld+json"
    r = requests.put(timeline_uri, data=json.dumps(timeline).encode("utf-8"), headers=headers)
    r.raise_for_status()
    print("status:", r.text)
