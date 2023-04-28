import io
import json
import os
import uuid
from urllib.error import HTTPError

import rdflib
from rdflib.namespace import RDF, RDFS, SKOS, DCTERMS, SDO
from rdflib import Graph, URIRef, Literal, Namespace
import requests
import requests.utils
from pyld import jsonld
from trompasolid.client import get_bearer_for_user

from scripts.convert_to_rdf import generate_structural_segmentation, segmentation_to_graph
from trompaalign.mei import get_metadata_for_mei


class SolidError(Exception):
    pass

MO = Namespace("http://purl.org/ontology/mo/")
MELD = Namespace("https://meld.linkedmusic.org/terms/")
TL = Namespace("http://purl.org/NET/c4dm/timeline.owl#")
LDP = Namespace("http://www.w3.org/ns/ldp#")

jsonld_context = {
    'mo': 'http://purl.org/ontology/mo/',
    'dcterms': 'http://purl.org/dc/terms/',
    'ldp': 'http://www.w3.org/ns/ldp#',
    'stat': 'http://www.w3.org/ns/posix/stat#',
    'mime': 'http://www.w3.org/ns/iana/media-types/',
    'schema': 'https://schema.org/about/'
}


# TODO: is a / necessary at the end of a name?
#  yes - according to LDP best practises
CLARA_CONTAINER_NAME = "at.ac.mdw.trompa/"


def get_pod_listing(provider, profile, storage):
    headers = get_bearer_for_user(provider, profile, storage, 'GET')
    resp = get_uri_jsonld(storage, headers)
    compact = jsonld.compact(resp, jsonld_context)
    return compact


def get_clara_listing_for_pod(provider, profile, storage):
    clara_container = os.path.join(storage, CLARA_CONTAINER_NAME)
    headers = get_bearer_for_user(provider, profile, clara_container, 'GET')
    try:
        return get_uri_jsonld(clara_container, headers)
    except requests.exceptions.HTTPError as e:
        # Special case - container doesn't exist, therefore it's missing
        if e.response.status_code == 404:
            return None
        else:
            raise


def get_resource_from_pod(provider, profile, uri):
    headers = get_bearer_for_user(provider, profile, uri, 'GET')
    # headers.update({"Accept": "application/ld+json"})
    r = requests.get(uri, headers=headers)
    r.raise_for_status()
    return r.content


def create_clara_container(provider, profile, storage):
    clara_container = os.path.join(storage, CLARA_CONTAINER_NAME)
    headers = get_bearer_for_user(provider, profile, clara_container, 'PUT')
    container_payload = {
        "@type": ["http://www.w3.org/ns/ldp#BasicContainer", "http://www.w3.org/ns/ldp#Container", "http://www.w3.org/ns/ldp#Resource"],
        "@id": clara_container
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
    links = r.headers.get('Link')
    if links:
        parsed_links = requests.utils.parse_header_links(links)
        for l in parsed_links:
            if l.get('rel') == 'http://openid.net/specs/connect/1.0/issuer':
                return l['url']

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


def get_title_from_mei(payload):
    metadata = get_metadata_for_mei(payload)
    title = ""
    if metadata["title"]:
        title += metadata["title"]
    if metadata["composer"]:
        title += " - " + metadata["composer"]
    if title:
        return title
    else:
        print("Error: Cannot find title in the MEI")
        return


def upload_mei_to_pod(provider, profile, storage, payload):
    resource = os.path.join(storage, CLARA_CONTAINER_NAME, "mei", str(uuid.uuid4()) + ".mei")
    print(f"Uploading file {resource}")
    headers = get_bearer_for_user(provider, profile, resource, 'PUT')
    # TODO: Should this be an XML mimetype, or a specific MEI one?
    headers["content-type"] = "application/xml"
    r = requests.put(resource, data=payload.encode("utf-8"), headers=headers)
    print(r.text)
    return resource


def upload_webmidi_to_pod(provider, profile, storage, payload: bytes):
    # TODO: This duplicates many other methods, could be simplified
    resource = os.path.join(storage, CLARA_CONTAINER_NAME, "webmidi", str(uuid.uuid4()) + ".json")
    print(f"Uploading file {resource}")
    headers = get_bearer_for_user(provider, profile, resource, 'PUT')
    headers["content-type"] = "application/json"
    r = requests.put(resource, data=payload, headers=headers)
    print("status:", r.text)
    return resource


def create_performance_container(provider, profile, storage, mei_external_uri):

    container_uuid = str(uuid.uuid4())
    # End with a /
    resource = os.path.join(storage, CLARA_CONTAINER_NAME, "performances", container_uuid, "")
    print(f"Creating {resource}")

    g = rdflib.Graph()
    g.bind("ldp", LDP)
    g.bind("schema", SDO)

    container_ref = URIRef('')
    g.add((container_ref, RDF.type, LDP.BasicContainer))
    g.add((container_ref, RDF.type, LDP.Container))
    g.add((container_ref, RDF.type, LDP.Resource))
    g.add((container_ref, SDO.about, URIRef(mei_external_uri)))
    print(g.serialize(format="n3"))

    # TODO: Identify differences between PUT and POST for creating containers
    #  https://www.w3.org/TR/ldp-primer/#creating-containers-and-structural-hierarchy
    #  seems to imply that you can POST to a parent container to make a new child one. Do they all need
    #  to exist up the tree? In any case, this PUT seems to work fine
    # Spec says:
    # Clients can create LDPRs via POST (section 5.2.3 HTTP POST) to a LDPC,
    # via PUT (section 4.2.4 HTTP PUT), or any other methods allowed for HTTP resources
    headers = get_bearer_for_user(provider, profile, resource, 'PUT')
    headers["content-type"] = "text/turtle"
    headers["slug"] = container_uuid
    headers["link"] = '<http://www.w3.org/ns/ldp/BasicContainer>; rel="type"'

    r = requests.put(resource, data=g.serialize(format='n3'), headers=headers)
    print(r.text)

    # TODO: HTTP PATCH to add
    # "http://schema.org/about": {'@id': url},



def save_segments_file(provider, profile, storage, segments_contents):
    resource = os.path.join(storage, CLARA_CONTAINER_NAME, "segments", str(uuid.uuid4()))

    headers = get_bearer_for_user(provider, profile, resource, 'PUT')

    r = requests.put(resource, data=segments_contents, headers=headers)
    print(r.text)
    return resource

"""
    g = Graph()
    g.bind("mo", MO)
    g.bind("meld", MELD)
    g.bind("skos", SKOS)
    g.bind("rdfs", RDFS)
    g.bind("tl", TL)

    score = URIRef()
    mei_uri = URIRef(mei_external_uri)
    mei_copy_uri = URIRef(mei_copy_uri)

    g.add((score, RDF.type, MO.Score))
    g.add((score, MO.published_as, mei_uri))
    g.add((score, MELD.segments, URIRef(segments_uri)))
    g.add((score, DCTERMS.title, title))
    g.add((mei_copy_uri, RDF.type, MO.PublishedScore))
    g.add((mei_copy_uri, SKOS.exactMatch, mei_uri))
"""

def create_and_save_structure(provider, profile, storage, title, mei_payload: str, mei_external_uri, mei_copy_uri):
    """A 'score' is an RDF document that describes an MEI file and the segments that we generate

    <uuid> a mo:Score ;
      mo:published_as <external URL> ;
      meld:segments <pod-url/path/to/segments/file.ttl> .

    <pod-url/path/to/MEI/copy.mei> a mo:PublishedScore ;
      skos:exactMatch <external URL>.

    TODO: We don't need to create a new structure if we already have one for this mei_external_uri
    """

    score_id = str(uuid.uuid4())
    resource = os.path.join(storage, CLARA_CONTAINER_NAME, "scores", score_id)

    mei_io = io.BytesIO(mei_payload.encode("utf-8"))
    mei_io.seek(0)

    segmentation = generate_structural_segmentation(mei_io)
    graph = segmentation_to_graph(segmentation, resource, mei_external_uri, title)

    # TODO: This wasn't in the original convert_to_rdf, but we decided to add it. ideally this should
    #   be part of that function, and that function should use rdflib, not manually construct the ttl
    mei_copy_uri_ref = URIRef(mei_copy_uri)
    graph.add((mei_copy_uri_ref, RDF.type, MO.PublishedScore))
    graph.add((mei_copy_uri_ref, SKOS.exactMatch, URIRef(mei_external_uri)))

    n3String = graph.serialize(format='n3')

    headers = get_bearer_for_user(provider, profile, resource, 'PUT')
    headers["content-type"] = "text/turtle"

    r = requests.put(resource, data=n3String, headers=headers)
    print("Making structure:", resource)
    print(r.text)


def get_uri_jsonld(uri, headers=None):
    if not headers:
        headers = {}
    headers.update({"Accept": "application/ld+json"})
    r = requests.get(uri, headers=headers)
    r.raise_for_status()
    return r.json()


def get_storage_from_profile(profile_uri):
    profile = get_uri_jsonld(profile_uri)
    expanded = jsonld.expand(profile, jsonld_context)
    id_card = [l for l in expanded if l.get('@id') == profile_uri]
    if id_card:
        id_card = id_card[0]
        storage = id_card.get('http://www.w3.org/ns/pim/space#storage', [])
        if isinstance(storage, list) and storage:
            return storage[0].get('@id')
        elif storage:
            return storage.get('@id')
    return None