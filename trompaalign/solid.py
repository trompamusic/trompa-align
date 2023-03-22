import json
import os
import uuid
from urllib.error import HTTPError

import rdflib
import requests
import requests.utils
from pyld import jsonld
from trompasolid.client import get_bearer_for_user

from trompaalign.mei import get_metadata_for_mei


class SolidError(Exception):
    pass


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


def upload_mei_to_pod(provider, profile, storage, url, payload, title=None):
    if not payload:
        r = requests.get(url)
        r.raise_for_status()
        payload = r.text

    if not title:
        print("No title set, trying to get one from the MEI")
        metadata = get_metadata_for_mei(payload)
        title = ""
        if metadata["title"]:
            title += metadata["title"]
        if metadata["composer"]:
            title += " - " + metadata["composer"]
        if not title:
            print("Error: Cannot find title in the MEI, and it's not set with --title")
            return

    container_name = str(uuid.uuid4()) + "/"
    resource = os.path.join(storage, CLARA_CONTAINER_NAME, container_name)
    container_payload = {
        "@type": ["http://www.w3.org/ns/ldp#BasicContainer", "http://www.w3.org/ns/ldp#Container", "http://www.w3.org/ns/ldp#Resource"],
        "@id": resource,
        "http://schema.org/about": {'@id': url},
        "http://purl.org/dc/terms/title": title
    }
    print(f"Creating {resource}")

    g = rdflib.Graph()
    g.parse(data=json.dumps(container_payload), format="json-ld")

    headers = get_bearer_for_user(provider, profile, resource, 'PUT')
    headers["content-type"] = "text/turtle"

    r = requests.put(resource, data=g.serialize(format='nt'), headers=headers)
    print(r.text)

    filename = os.path.basename(url)
    resource = os.path.join(storage, CLARA_CONTAINER_NAME, container_name, filename)
    print(f"Uploading file {resource}")
    headers = get_bearer_for_user(provider, profile, resource, 'PUT')
    headers["content-type"] = "application/xml"
    r = requests.put(resource, data=payload.encode("utf-8"), headers=headers)
    print(r.text)
    return os.path.join(storage, CLARA_CONTAINER_NAME, container_name)


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