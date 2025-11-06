import io
import json
import logging
import os
import uuid
from urllib.error import HTTPError

import rdflib
from rdflib.namespace import RDF, SDO
from rdflib.term import Literal
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


def _parse_acl_link_from_headers(headers):
    """Return ACL URI from Link headers if present, else None."""
    links = headers.get("Link")
    logger.debug("Parsing Link header for ACL: %s", links)
    if not links:
        return None
    try:
        parsed_links = requests.utils.parse_header_links(links)
    except Exception:
        logger.debug("Failed to parse Link headers")
        return None
    for l in parsed_links:
        rel = l.get("rel")
        if rel == "acl":
            acl_url = l.get("url")
            logger.debug("Found ACL link: %s", acl_url)
            return acl_url
    return None


def discover_acl_uri(solid_client, provider, profile, resource_uri):
    """Discover the ACL resource URI for a given resource.

    Strategy:
    1) HEAD or OPTIONS the resource and parse Link: <...>; rel="acl"
    2) Fallback to appending ".acl" (works on many Solid servers for both resources and containers)
    """
    logger.debug("Discovering ACL URI for resource: %s", resource_uri)
    # Try HEAD first
    try:
        headers = solid_client.get_bearer_for_user(provider, profile, resource_uri, "HEAD")
        logger.debug("HEAD %s with headers: %s", resource_uri, headers)
        r = requests.head(resource_uri, headers=headers)
        # Some servers may not allow HEAD; ignore failures and try OPTIONS
        logger.debug("HEAD status: %s, headers: %s", r.status_code, r.headers)
        if r.ok:
            acl_from_head = _parse_acl_link_from_headers(r.headers)
            if acl_from_head:
                return acl_from_head
    except Exception:
        logger.debug("HEAD attempt failed for %s", resource_uri)
        pass

    # Try OPTIONS
    try:
        headers, _ = http_options(solid_client, provider, profile, resource_uri)
        logger.debug("OPTIONS headers: %s", headers)
        acl_from_options = _parse_acl_link_from_headers(headers)
        if acl_from_options:
            return acl_from_options
    except Exception:
        logger.debug("OPTIONS attempt failed for %s", resource_uri)
        pass

    # Fallback heuristic: append .acl
    if resource_uri.endswith("/"):
        acl_fallback = resource_uri + ".acl"
        logger.debug("ACL discovery fallback (container): %s", acl_fallback)
        return acl_fallback
    acl_fallback = resource_uri + ".acl"
    logger.debug("ACL discovery fallback (resource): %s", acl_fallback)
    return acl_fallback


def _head_for_etag(solid_client, provider, profile, uri):
    """Return (exists: bool, etag: Optional[str])."""
    try:
        headers = solid_client.get_bearer_for_user(provider, profile, uri, "HEAD")
        logger.debug("Probing ETag via HEAD %s with headers: %s", uri, headers)
        r = requests.head(uri, headers=headers)
        logger.debug("HEAD status: %s, headers: %s", r.status_code, r.headers)
        if r.status_code == 404:
            logger.debug("HEAD indicates ACL does not exist: %s", uri)
            return False, None
        if r.ok:
            etag = r.headers.get("ETag")
            logger.debug("HEAD found ETag: %s", etag)
            return True, etag
    except Exception:
        # As a fallback, try GET to infer existence and ETag
        try:
            headers = solid_client.get_bearer_for_user(provider, profile, uri, "GET")
            headers.update({"Accept": "text/turtle"})
            logger.debug("Probing ETag via GET %s with headers: %s", uri, headers)
            r = requests.get(uri, headers=headers)
            logger.debug("GET status: %s, headers: %s", r.status_code, r.headers)
            if r.status_code == 404:
                return False, None
            if r.ok:
                etag = r.headers.get("ETag")
                logger.debug("GET found ETag: %s", etag)
                return True, etag
        except Exception:
            pass
    return False, None


def is_container_resource(solid_client, provider, profile, resource_uri: str) -> bool:
    """Detect if the resource is an LDP Container by fetching its types.

    We request JSON-LD and look for ldp:Container or ldp:BasicContainer types for the
    node whose @id equals the resource URI. Falls back to trailing-slash heuristic
    if the resource cannot be loaded as JSON-LD.
    """
    try:
        headers = solid_client.get_bearer_for_user(provider, profile, resource_uri, "GET")
        data, _ = get_uri_jsonld_or_none(resource_uri, headers)
        if data is None:
            logger.debug("is_container_resource: JSON-LD unavailable, fallback heuristic for %s", resource_uri)
            return resource_uri.endswith("/")
        compact = jsonld.compact(data, jsonld_context)
        logger.debug("is_container_resource compacted: %s", compact)
        candidates = []
        if isinstance(compact, dict):
            if "@graph" in compact and isinstance(compact["@graph"], list):
                candidates = compact["@graph"]
            else:
                candidates = [compact]
        for node in candidates:
            node_id = node.get("@id")
            if node_id != resource_uri:
                continue
            types = node.get("@type", [])
            if not isinstance(types, list):
                types = [types]
            # Accept both compacted and full IRI forms
            if any(
                t
                in (
                    "ldp:Container",
                    "ldp:BasicContainer",
                    "http://www.w3.org/ns/ldp#Container",
                    "http://www.w3.org/ns/ldp#BasicContainer",
                )
                for t in types
            ):
                logger.debug("Resource %s is an LDP Container (types=%s)", resource_uri, types)
                return True
        logger.debug("Resource %s is not detected as Container (types checked).", resource_uri)
        return False
    except Exception as e:
        logger.debug("is_container_resource failed for %s: %s", resource_uri, e)
        return resource_uri.endswith("/")


def _build_acl_graph_private(resource_uri: str, profile_uri: str, is_container: bool) -> rdflib.Graph:
    """Owner-only Control/Read/Write. For containers, also set acl:default."""
    ACL = rdflib.Namespace("http://www.w3.org/ns/auth/acl#")
    g = rdflib.Graph()
    auth = rdflib.BNode()
    g.add((auth, RDF.type, ACL.Authorization))
    g.add((auth, ACL.accessTo, URIRef(resource_uri)))
    if is_container:
        g.add((auth, ACL.default, URIRef(resource_uri)))
    g.add((auth, ACL.agent, URIRef(profile_uri)))
    g.add((auth, ACL.mode, ACL.Control))
    g.add((auth, ACL.mode, ACL.Read))
    g.add((auth, ACL.mode, ACL.Write))
    return g


def _build_acl_graph_public(resource_uri: str, profile_uri: str, is_container: bool) -> rdflib.Graph:
    """Owner Control/Read/Write + Public Read. For containers, also set acl:default for both rules."""
    ACL = rdflib.Namespace("http://www.w3.org/ns/auth/acl#")
    FOAF = rdflib.Namespace("http://xmlns.com/foaf/0.1/")
    g = _build_acl_graph_private(resource_uri, profile_uri, is_container)
    auth_public = rdflib.BNode()
    g.add((auth_public, RDF.type, ACL.Authorization))
    g.add((auth_public, ACL.accessTo, URIRef(resource_uri)))
    if is_container:
        g.add((auth_public, ACL.default, URIRef(resource_uri)))
    g.add((auth_public, ACL.agentClass, FOAF.Agent))
    g.add((auth_public, ACL.mode, ACL.Read))
    return g


def _put_document_with_preconditions(
    solid_client,
    provider,
    profile,
    resource_uri: str,
    content_bytes: bytes,
    content_type: str,
    existing: bool,
    etag: str | None,
    extra_headers: dict | None = None,
):
    """PUT a document with ETag-based preconditions.

    - If existing True and etag provided: send If-Match
    - If existing False: send If-None-Match: *
    - Sets Content-Type as provided; allows optional extra headers
    """
    headers = solid_client.get_bearer_for_user(provider, profile, resource_uri, "PUT")
    headers["content-type"] = content_type
    if extra_headers:
        headers.update(extra_headers)
    if existing and etag:
        headers["If-Match"] = etag
    if not existing:
        headers["If-None-Match"] = "*"
    r = requests.put(resource_uri, data=content_bytes, headers=headers)
    if r.status_code == 412:
        raise SolidError("Update failed due to precondition (ETag mismatch). Reload and retry.")
    r.raise_for_status()
    return r


def set_resource_acl_private(solid_client, provider, profile, resource_uri: str):
    """Set ACL to private (owner-only Control/Read/Write)."""
    acl_uri = discover_acl_uri(solid_client, provider, profile, resource_uri)
    exists, etag = _head_for_etag(solid_client, provider, profile, acl_uri)
    container = is_container_resource(solid_client, provider, profile, resource_uri)
    logger.debug("Building private ACL for %s (container=%s)", resource_uri, container)
    g = _build_acl_graph_private(resource_uri, profile, container)
    ttl = g.serialize(format="n3", encoding="utf-8")
    _put_document_with_preconditions(solid_client, provider, profile, acl_uri, ttl, "text/turtle", exists, etag)
    return acl_uri


def set_resource_acl_public(solid_client, provider, profile, resource_uri: str):
    """Set ACL to public-read + owner Control/Read/Write."""
    acl_uri = discover_acl_uri(solid_client, provider, profile, resource_uri)
    exists, etag = _head_for_etag(solid_client, provider, profile, acl_uri)
    container = is_container_resource(solid_client, provider, profile, resource_uri)
    logger.debug("Building public ACL for %s (container=%s)", resource_uri, container)
    g = _build_acl_graph_public(resource_uri, profile, container)
    ttl = g.serialize(format="n3", encoding="utf-8")
    _put_document_with_preconditions(solid_client, provider, profile, acl_uri, ttl, "text/turtle", exists, etag)
    return acl_uri


def delete_acl_for_resource(solid_client, provider, profile, resource_uri: str):
    """Delete the ACL resource for a given resource using ETag preconditions."""
    acl_uri = discover_acl_uri(solid_client, provider, profile, resource_uri)
    exists, etag = _head_for_etag(solid_client, provider, profile, acl_uri)
    if not exists:
        logger.debug("ACL does not exist for %s (uri=%s)", resource_uri, acl_uri)
        return acl_uri
    headers = solid_client.get_bearer_for_user(provider, profile, acl_uri, "DELETE")
    if etag:
        headers["If-Match"] = etag
    r = requests.delete(acl_uri, headers=headers)
    if r.status_code == 412:
        raise SolidError("ACL delete failed due to precondition (ETag mismatch). Reload and retry.")
    r.raise_for_status()
    return acl_uri


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
                continue
            if not isinstance(contains, list):
                contains = [contains]
            for cont in contains:
                contents.append(cont["@id"])
    return contents


def get_contents_of_container_rdf(container_jsonld, container_name: str) -> list[str]:
    """Extract contained resource URIs from a container JSON-LD using rdflib.

    - Validates that the subject is an LDP Container (Container or BasicContainer)
    - Returns a list of contained resource URIs via ldp:contains
    """
    LDP = rdflib.Namespace("http://www.w3.org/ns/ldp#")
    print(json.dumps(container_jsonld, indent=2))
    try:
        g = rdflib.Graph()
        g.parse(data=json.dumps(container_jsonld), format="json-ld")
        subject = rdflib.URIRef(container_name)

        # Validate container type
        is_container = (subject, RDF.type, LDP.Container) in g or (subject, RDF.type, LDP.BasicContainer) in g
        if not is_container:
            return []

        # Collect contained resources
        contents: list[str] = []
        for o in g.objects(subject, LDP.contains):
            if isinstance(o, rdflib.term.Node):
                contents.append(str(o))
        return contents
    except Exception as e:
        print("Exception", e)
        return []


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
    contents = get_contents_of_container_rdf(score_listing, resource)
    for item in contents:
        file = get_resource_from_pod(solid_client, provider, profile, item)
        graph = rdflib.Graph()
        graph.parse(file)
        matches = list(graph.triples((None, MO.published_as, URIRef(mei_external_uri))))
        if len(matches):
            return item


def list_external_score_urls(solid_client, provider, profile, storage):
    """Return a set of external MEI URLs referenced by score objects in the user's scores/ container.

    Iterates over all resources in the scores container and extracts values of mo:published_as.
    """
    resource = os.path.join(storage, CLARA_CONTAINER_NAME, "scores/")
    score_listing = get_pod_listing(solid_client, provider, profile, resource)
    if score_listing is None:
        return set()
    contents = get_contents_of_container(score_listing, resource)
    external_urls = set()
    for item in contents:
        try:
            ttl_bytes = get_resource_from_pod(solid_client, provider, profile, item, accept="text/turtle")
            graph = rdflib.Graph()
            # Stored as text/turtle (n3)
            graph.parse(data=ttl_bytes.decode("utf-8"), format="n3")
            for _s, _p, o in graph.triples((None, MO.published_as, None)):
                if isinstance(o, rdflib.term.Node):
                    external_urls.add(str(o))
        except Exception:
            # Ignore resources that are not TTL score descriptions
            continue
    return external_urls


def update_score_list_bulk(solid_client, provider, profile, storage, external_urls: set[str]) -> tuple[int, int]:
    """Add multiple external URLs to the scores list in a single write.

    Returns (added_count, total_after).
    """
    graph, _etag_ignored, score_data_resource = _get_score_list(solid_client, provider, profile, storage)

    existing_urls = set(str(o) for _s, _p, o in graph.triples((None, SDO.itemListElement, None)))
    to_add = [u for u in sorted(external_urls) if u not in existing_urls]

    if not to_add:
        # Nothing to do; still ensure the file exists if it doesn't
        exists, etag = _head_for_etag(solid_client, provider, profile, score_data_resource)
        if not exists:
            ttl_bytes = graph.serialize(format="n3", encoding="utf-8")
            _put_document_with_preconditions(
                solid_client,
                provider,
                profile,
                score_data_resource,
                ttl_bytes,
                "text/turtle",
                exists,
                etag,
            )
        return 0, len(existing_urls)

    for url in to_add:
        _add_score_to_list(graph, score_data_resource, url)

    exists, etag = _head_for_etag(solid_client, provider, profile, score_data_resource)
    ttl_bytes = graph.serialize(format="n3", encoding="utf-8")
    _put_document_with_preconditions(
        solid_client,
        provider,
        profile,
        score_data_resource,
        ttl_bytes,
        "text/turtle",
        exists,
        etag,
    )
    return len(to_add), len(existing_urls) + len(to_add)


def _get_empty_score_list_graph(score_data_resource):
    graph = rdflib.Graph()
    graph.add((URIRef(score_data_resource), RDF.type, SDO.ItemList))
    graph.add((URIRef(score_data_resource), SDO.name, Literal("Scores in this user's CLARA instance")))
    return graph


def _get_score_list(solid_client, provider, profile, storage):
    """Get the score list from the top-level scores-list file.

    Returns a tuple (graph, etag, resource_uri).
    If the file doesn't exist, returns (empty_graph, None, resource_uri).
    """
    score_data_resource = os.path.join(storage, CLARA_CONTAINER_NAME, "scores-list")
    try:
        headers = solid_client.get_bearer_for_user(provider, profile, score_data_resource, "GET")
        headers["Accept"] = "text/turtle"
        r = requests.get(score_data_resource, headers=headers)
        r.raise_for_status()
        etag = r.headers.get("ETag")
        graph = rdflib.Graph()
        graph.parse(data=r.text, format="n3")
        return graph, etag, score_data_resource
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return _get_empty_score_list_graph(score_data_resource), None, score_data_resource
        else:
            raise e


def _add_score_to_list(score_list_graph: rdflib.Graph, item_list_subject_uri: str, mei_external_uri: str):
    """Add the external URL to the ItemList as a schema:itemListElement IRI."""
    score_list_graph.add((URIRef(item_list_subject_uri), SDO.itemListElement, URIRef(mei_external_uri)))
    return score_list_graph


def score_exists_in_list(solid_client, provider, profile, storage, mei_external_uri: str) -> bool:
    """Return True if the given external URL is present in the scores list, else False.

    Read-only; performs no writes.
    """
    graph, _etag, _resource = _get_score_list(solid_client, provider, profile, storage)
    for _s, _p, o in graph.triples((None, SDO.itemListElement, URIRef(mei_external_uri))):
        # First match is sufficient
        return True
    return False


def add_score_to_list(solid_client, provider, profile, storage, mei_external_uri) -> bool:
    """Public helper to add a score URL to the score list iff missing.

    Uses the bulk update path even for a single URL to ensure a single read/write.
    Returns True if added; False if it already existed.
    """
    added, _total = update_score_list_bulk(solid_client, provider, profile, storage, {mei_external_uri})
    return added > 0


def create_and_save_structure(
    solid_client, provider, profile, storage, title, mei_payload: str, mei_external_uri, mei_copy_uri
):
    """A 'score' is an RDF document that describes an MEI file and the segments that we generate

    <uuid> a mo:Score ;
      mo:published_as <external URL> ;
      meld:segments <pod-url/path/to/segments/file.ttl> .

    <pod-url/path/to/MEI/copy.mei> a mo:PublishedScore ;
      skos:exactMatch <external URL>.

    TODO: We don't need to create a new structure if we already have one for this mei_external_uri.
      Currently we have a check for this in the frontend, so we shouldn't call the API if this is the case
      However if another endpoint calls the API directly, it may cause duplicates.
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
    r = requests.put(performance_resource, headers=headers, timeout=10)
    r.raise_for_status()
    print(r.text)

    print("Making timeline container:", timeline_resource)
    headers = solid_client.get_bearer_for_user(provider, profile, timeline_resource, "PUT")
    r = requests.put(timeline_resource, headers=headers, timeout=10)
    r.raise_for_status()
    print(r.text)

    print("Making score:", score_resource)
    headers = solid_client.get_bearer_for_user(provider, profile, score_resource, "PUT")
    headers["content-type"] = "text/turtle"
    r = requests.put(score_resource, data=score_data, headers=headers, timeout=10)
    r.raise_for_status()
    print(r.text)

    print("Making segment:", segment_resource)
    headers = solid_client.get_bearer_for_user(provider, profile, segment_resource, "PUT")
    headers["content-type"] = "text/turtle"
    r = requests.put(segment_resource, data=segmentation_data, headers=headers, timeout=10)
    r.raise_for_status()
    print(r.text)

    # Add the external MEI URL to the scores list
    try:
        added, _total = update_score_list_bulk(solid_client, provider, profile, storage, {mei_external_uri})
        if added == 0:
            print("Score already present in scores list; continuing")
    except SolidError as e:
        # List update conflict; surface but do not fail the creation process
        print(f"Warning: could not update scores list: {e}")

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
    print("save_performance_manifest status:", r.text)


def save_performance_timeline(solid_client, provider, profile, timeline_uri, timeline):
    print(f"Uploading timeline to {timeline_uri}")
    headers = solid_client.get_bearer_for_user(provider, profile, timeline_uri, "PUT")
    headers["content-type"] = "application/ld+json"
    r = requests.put(timeline_uri, data=json.dumps(timeline).encode("utf-8"), headers=headers)
    r.raise_for_status()
    print("save_performance_timeline status:", r.text)
