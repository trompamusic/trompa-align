import io
import json
import logging
import mimetypes
import os
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

import rdflib
import rdflib.exceptions
import requests
import requests.utils
from pyld import jsonld
from rdflib import URIRef
from rdflib.namespace import RDF, SDO, SKOS
from rdflib.term import Literal
from solidauth import client, httpclient
from solidauth.solid import RdfFetchError, fetch_graph

from scripts.convert_to_rdf import generate_structural_segmentation, score_to_graph, segmentation_to_graph
from scripts.namespace import MELD, MO, TL
from trompaalign.mei import get_metadata_for_mei

logger = logging.getLogger(__name__)


class SolidError(Exception):
    pass


def require_value(graph: rdflib.Graph, uri: str, subject=None, predicate=None, object_=None) -> str:
    """Return the single term matching the given pattern, raising if it's missing or ambiguous."""
    try:
        value = graph.value(subject=subject, predicate=predicate, object=object_, any=False)
    except rdflib.exceptions.UniquenessError:
        raise ValueError(f"URI {uri} has more than one {predicate}") from None
    if value is None:
        raise ValueError(f"URI {uri} is missing {predicate}")
    return str(value)


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
LDP = rdflib.Namespace("http://www.w3.org/ns/ldp#")


def is_lock_expired_response(resp: requests.Response) -> bool:
    """Return True if the response body looks like a SolidCommunity lock timeout."""
    try:
        data = resp.json()
        if data.get("statusCode") == 500 and isinstance(data.get("message"), str):
            if "Lock expired" in data.get("message"):
                return True
    except Exception:
        pass
    try:
        return "Lock expired after" in (resp.text or "")
    except Exception:
        return False


def create_ldp_container(
    solid_client,
    provider,
    profile,
    container_uri: str,
    *,
    timeout: float | None = None,
):
    """Create an LDP BasicContainer using a Turtle payload."""
    if not container_uri.endswith("/"):
        container_uri = container_uri + "/"

    headers = solid_client.get_bearer_for_user(provider, profile, container_uri, "PUT")

    graph = rdflib.Graph()
    container_ref = rdflib.URIRef(container_uri)
    LDP = rdflib.Namespace("http://www.w3.org/ns/ldp#")
    graph.add((container_ref, RDF.type, LDP.BasicContainer))
    graph.add((container_ref, RDF.type, LDP.Container))
    graph.add((container_ref, RDF.type, LDP.Resource))

    turtle_data = graph.serialize(format="turtle")
    type_headers = {"Accept": "text/turtle", "content-type": "text/turtle"}
    headers.update(type_headers)

    request_kwargs = {}
    if timeout is not None:
        request_kwargs["timeout"] = timeout

    r = httpclient.put(container_uri, data=turtle_data.encode("utf-8"), headers=headers, **request_kwargs)
    if r.status_code == 201:
        return container_uri
    try:
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        if is_lock_expired_response(r):
            print(f"Warning: provider lock timeout, treating container create as success for {container_uri}")
        else:
            print(f"Unexpected status creating container {container_uri}: {e}")
            print(f"Response: {r.text}")
            raise
    return container_uri


def http_options(solid_client, provider, profile, container):
    headers = solid_client.get_bearer_for_user(provider, profile, container, "OPTIONS")
    r = httpclient.options(container, headers=headers)
    r.raise_for_status()
    return r.headers, r.content


def get_pod_listing(solid_client, provider, profile, storage):
    response = get_pod_response(solid_client, provider, profile, storage, accept="application/ld+json")
    data = response.json()
    return jsonld.compact(data, jsonld_context) if data is not None else None


def get_pod_listing_ttl(solid_client, provider, profile, storage):
    return get_pod_response(solid_client, provider, profile, storage, accept="text/turtle").text


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
        r = httpclient.head(resource_uri, headers=headers)
        # Some servers may not allow HEAD; ignore failures and try OPTIONS
        logger.debug("HEAD status: %s, headers: %s", r.status_code, r.headers)
        if r.ok:
            acl_from_head = _parse_acl_link_from_headers(r.headers)
            if acl_from_head:
                return acl_from_head
    except Exception:
        logger.debug("HEAD attempt failed for %s", resource_uri)

    # Try OPTIONS
    try:
        headers, _ = http_options(solid_client, provider, profile, resource_uri)
        logger.debug("OPTIONS headers: %s", headers)
        acl_from_options = _parse_acl_link_from_headers(headers)
        if acl_from_options:
            return acl_from_options
    except Exception:
        logger.debug("OPTIONS attempt failed for %s", resource_uri)

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
        r = httpclient.head(uri, headers=headers)
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
            r = httpclient.get(uri, headers=headers)
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
    r = httpclient.put(resource_uri, data=content_bytes, headers=headers)
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


def delete_resource(solid_client, provider, profile, resource_uri: str):
    """Delete a resource from a Solid pod.

    Args:
        solid_client: The Solid client instance
        provider: The provider URL
        profile: The profile URL
        resource_uri: The URI of the resource to delete

    Raises:
        requests.HTTPError: If the deletion fails
    """
    headers = solid_client.get_bearer_for_user(provider, profile, resource_uri, "DELETE")
    r = httpclient.delete(resource_uri, headers=headers)
    r.raise_for_status()
    return r


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
    r = httpclient.delete(acl_uri, headers=headers)
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

    r = httpclient.patch(container, data=update_data, headers=headers)
    r.raise_for_status()
    print(r.text)
    print(f"Status: {r.status_code}")


def parse_pod_graph(data, base_uri):
    """Parse JSON-LD or Turtle, or reuse an existing RDF graph."""
    if isinstance(data, rdflib.Graph):
        return data
    is_json = isinstance(data, (dict, list))
    return rdflib.Graph().parse(
        data=json.dumps(data) if is_json else data,
        format="json-ld" if is_json else "turtle",
        publicID=base_uri,
    )


def get_contents_of_container(container, container_name):
    """Extract member URLs from JSON-LD, Turtle or an RDF graph; reject invalid members."""
    graph = parse_pod_graph(container, container_name)
    subject = URIRef(container_name)
    members = list(graph.objects(subject, LDP.contains))
    if any(not isinstance(member, URIRef) for member in members):
        raise ValueError(f"Container member is not a URL: {container_name}")
    return sorted(str(member) for member in members)


def list_container(solid_client, provider, profile, container):
    """Fetch and parse the direct members of a container."""
    listing = get_pod_listing_ttl(solid_client, provider, profile, container)
    return get_contents_of_container(listing, container)


def _local_name(encoded_name):
    name = unquote(encoded_name)
    if not name or name in (".", "..") or any(char in name for char in ("/", "\\", "\0")):
        raise ValueError(f"Unsafe local filename: {encoded_name}")
    return name


def container_basename(container):
    """Return the decoded container basename, using the hostname for a pod root."""
    url = urlsplit(container)
    basename = url.path.rstrip("/").rsplit("/", 1)[-1]
    return _local_name(basename or url.hostname or "")


def container_member_name(container, resource):
    """Validate a direct member URL and return its decoded filename."""
    parent, child = urlsplit(container), urlsplit(resource)
    if (
        (child.scheme, child.netloc) != (parent.scheme, parent.netloc)
        or child.query
        or child.fragment
        or not child.path.startswith(parent.path)
    ):
        raise ValueError(f"Resource is outside its container: {resource}")
    return _local_name(child.path[len(parent.path) :].removesuffix("/"))


def _with_trailing_slash(uri: str) -> str:
    return uri if uri.endswith("/") else uri + "/"


def container_exists(solid_client: client.SolidClient, provider: str, profile: str, container_uri: str) -> bool:
    """Return True if the LDP container exists, False if not.

    Tries HEAD first, then falls back to GET with Accept: text/turtle.
    """
    uri = _with_trailing_slash(container_uri)
    try:
        headers = solid_client.get_bearer_for_user(provider, profile, uri, "HEAD")
        r = httpclient.head(uri, headers=headers)
        if r.status_code == 404:
            return False
        if r.ok:
            return True
    except Exception:
        pass

    try:
        headers = solid_client.get_bearer_for_user(provider, profile, uri, "GET")
        headers.update({"Accept": "text/turtle"})
        r = httpclient.get(uri, headers=headers)
        if r.status_code == 404:
            return False
        if r.ok:
            return True
    except Exception:
        pass

    return False


def get_content_type(file_path: str) -> str | None:
    """
    Determine the content type for a file based on its extension.

    Args:
        file_path: Path to the file

    Returns:
        Content type string or None if not specified
    """
    filename = os.path.basename(file_path)

    # Handle special case for files ending with $.ext
    if "$." in filename:
        # Extract extension after $
        parts = filename.split("$.")
        if len(parts) > 1:
            ext = parts[-1].lower()
            if ext == "xml":
                return "text/xml"
            elif ext == "ttl":
                return "text/turtle"
            # For other extensions, return None (omit content-type)
            return None
    if filename.endswith(".jsonld"):
        return "application/ld+json"

    # For regular files, use mimetypes
    content_type, _ = mimetypes.guess_type(file_path)
    return content_type


def clean_remote_filename(filename: str) -> str:
    """
    Clean the filename for remote storage by removing the $ extension pattern.

    Args:
        filename: Original filename

    Returns:
        Cleaned filename
    """
    if "$." in filename:
        # Remove everything from $. onwards
        return filename.split("$.")[0]
    return filename


def upload_file_to_pod(
    solid_client: client.SolidClient, provider: str, profile: str, local_file_path: str, remote_uri: str
):
    """
    Upload a single file to the pod.

    Args:
        solid_client: The Solid client instance
        provider: The provider URL
        profile: The profile URL
        local_file_path: Path to the local file
        remote_uri: URI where the file should be uploaded
    """
    print(f"Uploading file {local_file_path} to {remote_uri}")

    headers = solid_client.get_bearer_for_user(provider, profile, remote_uri, "PUT")

    # Read file content
    with open(local_file_path, "rb") as f:
        content = f.read()

    # Set content type
    content_type = get_content_type(local_file_path)
    if content_type:
        headers["content-type"] = content_type

    r = httpclient.put(remote_uri, data=content, headers=headers)
    try:
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        if is_lock_expired_response(r):
            print(f"Warning: provider lock timeout, treating as success for {remote_uri}")
        else:
            print(f"Error uploading {remote_uri}: {e}")
            print(f"Response: {r.text}")
            raise
    print(f"Uploaded: {remote_uri}")


def get_pod_response(solid_client, provider, profile, uri, accept=None):
    """Fetch an authenticated resource using the HTTP client's default redirect handling."""
    headers = solid_client.get_bearer_for_user(provider, profile, uri, "GET")
    if accept:
        headers["Accept"] = accept
    response = httpclient.get(uri, headers=headers)
    response.raise_for_status()
    return response


def get_resource_from_pod(solid_client, provider, profile, uri, accept=None):
    return get_pod_response(solid_client, provider, profile, uri, accept).content


def save_resource_from_pod(solid_client, provider, profile, uri, destination, *, overwrite=True):
    """Fetch bytes and save them, optionally requiring a new destination file."""
    destination = Path(destination)
    content = get_resource_from_pod(solid_client, provider, profile, uri)
    output = destination.open("wb" if overwrite else "xb")
    try:
        with output:
            output.write(content)
    except BaseException:
        if not overwrite:
            destination.unlink()
        raise


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
    r = httpclient.put(clara_container, data=json.dumps(container_payload), headers=headers)
    if r.status_code == 201:
        print("Successfully created")
    else:
        print(f"Unexpected status code: {r.status_code}: {r.text}")


def lookup_provider_from_profile(profile_url: str):
    """

    :param profile_url: The profile of the user, e.g.  https://alice.coolpod.example/profile/card#me
    :return:
    """

    r = httpclient.options(profile_url)
    r.raise_for_status()
    links = r.headers.get("Link")
    if links:
        parsed_links = requests.utils.parse_header_links(links)
        for l in parsed_links:
            if l.get("rel") == "http://openid.net/specs/connect/1.0/issuer":
                return l["url"]

    # If we get here, there was no rel in the options. Instead, try and get the card
    # and find its issuer
    try:
        graph = fetch_graph(profile_url)
    except RdfFetchError as e:
        print(f"Cannot fetch or parse a profile at this url: {e}")
        return None
    issuer = rdflib.URIRef("http://www.w3.org/ns/solid/terms#oidcIssuer")
    triples = list(graph.triples((None, issuer, None)))
    if triples:
        # first item in the response, 3rd item in the triple
        return triples[0][2].toPython()  # ty: ignore[unresolved-attribute]


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
    r = httpclient.put(resource, data=payload.encode("utf-8"), headers=headers)
    r.raise_for_status()
    print(r.text)
    return resource


def upload_webmidi_to_pod(solid_client, provider, profile, storage, payload: bytes):
    # TODO: This duplicates many other methods, could be simplified
    resource = os.path.join(storage, CLARA_CONTAINER_NAME, "webmidi", str(uuid.uuid4()) + ".json")
    print(f"Uploading webmidi file to {resource}")
    headers = solid_client.get_bearer_for_user(provider, profile, resource, "PUT")
    headers["content-type"] = "application/json"
    r = httpclient.put(resource, data=payload, headers=headers)
    r.raise_for_status()
    print("status:", r.text)
    return resource


def upload_midi_to_pod(solid_client, provider, profile, storage, payload: bytes):
    resource = os.path.join(storage, CLARA_CONTAINER_NAME, "midi", str(uuid.uuid4()) + ".mid")
    print(f"Uploading midi file to {resource}")
    headers = solid_client.get_bearer_for_user(provider, profile, resource, "PUT")
    headers["content-type"] = "audio/midi"
    r = httpclient.put(resource, data=payload, headers=headers)
    r.raise_for_status()
    print("status:", r.text)
    return resource


def upload_mp3_to_pod(solid_client, provider, profile, resource, payload: bytes):
    print(f"Uploading mp3 file to {resource}")
    headers = solid_client.get_bearer_for_user(provider, profile, resource, "PUT")
    headers["content-type"] = "audio/mpeg"
    r = httpclient.put(resource, data=payload, headers=headers)
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


@dataclass
class Score:
    uri: str
    external_uri: str
    mei_uri: str
    performances_container: str
    segments_uri: str


def load_score_from_uri(solid_client, provider, profile, storage, uri: str) -> Score:
    ttl_bytes = get_resource_from_pod(solid_client, provider, profile, uri, accept="text/turtle")
    graph = rdflib.Graph()
    uri_ref = URIRef(uri)

    graph.parse(data=ttl_bytes.decode("utf-8"), format="n3")

    # check the uri's type (i.e. skip old scores.ttl file)
    triples = list(graph.triples((uri_ref, RDF.type, MO.Score)))
    if not triples:
        raise ValueError(f"URI {uri} is not a score")

    external_uri = require_value(graph, uri, subject=uri_ref, predicate=MO.published_as)
    mei_uri = require_value(graph, uri, predicate=SKOS.exactMatch, object_=URIRef(external_uri))
    performances_container = require_value(graph, uri, subject=uri_ref, predicate=SKOS.related)
    segments_uri = require_value(graph, uri, subject=uri_ref, predicate=MELD.segments)

    return Score(
        uri=uri,
        external_uri=external_uri,
        mei_uri=mei_uri,
        performances_container=performances_container,
        segments_uri=segments_uri,
    )


def list_score_urls(solid_client, provider, profile, storage):
    """Enumerate the files in the scores/ container.

    Returns a list of Score objects
    """
    resource = os.path.join(storage, CLARA_CONTAINER_NAME, "scores/")
    score_listing = get_pod_listing(solid_client, provider, profile, resource)
    if score_listing is None:
        return []
    contents = get_contents_of_container(score_listing, resource)
    print("contents", contents)
    return contents


def list_performance_urls(solid_client, provider, profile, storage, performances_container: str) -> list[str]:
    """Get all of the performances for a specific performance container

    Arguments:
        performances_container: the URI of the performances container (from Score.performances_container)
    """

    return list_container(solid_client, provider, profile, performances_container)


@dataclass
class Performance:
    uri: str
    performance_of: str
    signal_uri: str
    available_as: str
    derived_from: str
    timeline: str
    offset: str | None = None


def load_performance_from_uri(solid_client, provider, profile, uri: str) -> Performance:
    ttl_bytes = get_resource_from_pod(solid_client, provider, profile, uri, accept="text/turtle")
    graph = rdflib.Graph()
    uri_ref = URIRef(uri)
    graph.parse(data=ttl_bytes.decode("utf-8"), format="n3")
    triples = list(graph.triples((uri_ref, RDF.type, MO.Performance)))
    if not triples:
        raise ValueError(f"URI {uri} is not a performance")

    performance_of = require_value(graph, uri, subject=uri_ref, predicate=MO.performance_of)
    signal_uri = require_value(graph, uri, subject=uri_ref, predicate=MO.recorded_as)
    offset = graph.value(subject=uri_ref, predicate=MELD.offset)
    offset = None if offset is None else str(offset)

    signal_ref = URIRef(signal_uri)
    available_as = require_value(graph, uri, subject=signal_ref, predicate=MO.available_as)
    derived_from = require_value(graph, uri, subject=signal_ref, predicate=MO.derived_from)
    try:
        interval = graph.value(subject=signal_ref, predicate=MO.time, any=False)
    except rdflib.exceptions.UniquenessError:
        raise ValueError(f"URI {uri} has more than one {MO.time}") from None
    if interval is None:
        raise ValueError(f"URI {uri} is missing {MO.time}")
    timeline = require_value(graph, uri, subject=interval, predicate=TL.onTimeLine)

    return Performance(
        uri=uri,
        performance_of=performance_of,
        signal_uri=signal_uri,
        available_as=available_as,
        derived_from=derived_from,
        timeline=timeline,
        offset=offset,
    )


def update_score_list_bulk(solid_client, provider, profile, storage, external_urls: set[str]) -> tuple[int, int]:
    """Add multiple external URLs to the scores list in a single write.

    Returns (added_count, total_after).
    """
    graph, _etag_ignored, score_data_resource = _get_score_list(solid_client, provider, profile, storage)

    existing_urls = {str(o) for _s, _p, o in graph.triples((None, SDO.itemListElement, None))}
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
        r = get_pod_response(solid_client, provider, profile, score_data_resource, accept="text/turtle")
        etag = r.headers.get("ETag")
        graph = rdflib.Graph()
        graph.parse(data=r.text, format="n3")
        return graph, etag, score_data_resource
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            return _get_empty_score_list_graph(score_data_resource), None, score_data_resource
        else:
            raise


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
    create_ldp_container(solid_client, provider, profile, performance_resource, timeout=10)

    print("Making timeline container:", timeline_resource)
    create_ldp_container(solid_client, provider, profile, timeline_resource, timeout=10)

    print("Making score:", score_resource)
    headers = solid_client.get_bearer_for_user(provider, profile, score_resource, "PUT")
    headers["content-type"] = "text/turtle"
    r = httpclient.put(score_resource, data=score_data, headers=headers, timeout=10)
    try:
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print(f"Error making score: {e}")
        raise
    finally:
        print(r.text)
    print(r.text)

    print("Making segment:", segment_resource)
    headers = solid_client.get_bearer_for_user(provider, profile, segment_resource, "PUT")
    headers["content-type"] = "text/turtle"
    r = httpclient.put(segment_resource, data=segmentation_data, headers=headers, timeout=10)
    try:
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print(f"Error making segment: {e}")
        raise
    finally:
        print(r.text)
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
        if e.response is not None:
            print(" message:", e.response.text)
        return None, None


def get_uri_jsonld(uri, headers=None):
    if not headers:
        headers = {}
    headers.update({"Accept": "application/ld+json"})
    r = httpclient.get(uri, headers=headers)
    r.raise_for_status()
    logger.debug("Get json-ld from %s", uri)
    logger.debug("json-ld headers: %s", r.headers)
    logger.debug("json-ld content: %s", json.dumps(r.json(), indent=2))
    return r.json(), r.headers


def get_uri_ttl(uri, headers=None):
    if not headers:
        headers = {}
    headers.update({"Accept": "text/turtle"})
    r = httpclient.get(uri, headers=headers)
    r.raise_for_status()
    return r.text


def get_storage_from_profile(profile_uri):
    graph = fetch_graph(profile_uri)
    storage = graph.value(
        subject=rdflib.URIRef(profile_uri), predicate=rdflib.URIRef("http://www.w3.org/ns/pim/space#storage")
    )
    if storage is None:
        print("No storage found")
        return None
    return storage.toPython()  # ty: ignore[unresolved-attribute]


def save_performance_manifest(solid_client, provider, profile, performance_uri, manifest):
    print(f"Uploading manifest to {performance_uri}")
    headers = solid_client.get_bearer_for_user(provider, profile, performance_uri, "PUT")
    headers["content-type"] = "text/turtle"
    r = httpclient.put(performance_uri, data=manifest, headers=headers)
    r.raise_for_status()
    print("save_performance_manifest status:", r.text)


def save_performance_timeline(solid_client, provider, profile, timeline_uri, timeline):
    print(f"Uploading timeline to {timeline_uri}")
    headers = solid_client.get_bearer_for_user(provider, profile, timeline_uri, "PUT")
    headers["content-type"] = "application/ld+json"
    r = httpclient.put(timeline_uri, data=json.dumps(timeline).encode("utf-8"), headers=headers)
    r.raise_for_status()
    print("save_performance_timeline status:", r.text)


def recursive_delete_from_pod(solid_client, provider, profile, container):
    """Delete resources described by the listing, recursing into RDF-typed containers."""
    listing = get_pod_listing(solid_client, provider, profile, container)
    if listing is None:
        delete_resource(solid_client, provider, profile, container)
        return
    graph = parse_pod_graph(listing, container)
    for resource in graph.subjects(unique=True):
        if resource == URIRef(container):
            continue
        types = set(graph.objects(resource, RDF.type))
        if not types:
            raise ValueError(f"Missing RDF type for resource: {resource}")
        if LDP.Container in types:
            recursive_delete_from_pod(solid_client, provider, profile, str(resource))
        else:
            print(f"Delete file {resource}")
            delete_resource(solid_client, provider, profile, str(resource))
    delete_resource(solid_client, provider, profile, container)


def delete_duplicate_scores(solid_client, provider, profile, storage, delete_empty_scores=False, dry_run=False):
    """Delete duplicate scores that have no performances.

    For scores with the same external_uri, if a score has no performances
    and there are multiple scores with that external_uri, delete the score
    and its associated resources (segments, mei, timeline container,
    performance container, and score URI).

    Args:
        solid_client: The Solid client instance
        provider: The provider URL
        profile: The profile URL
        storage: The storage URL
        delete_empty_scores: If True, also delete scores with no performances
            even if they are unique (count == 1). Default False.
        dry_run: If True, show what would be deleted without actually deleting.
            Default False.

    Returns:
        int: Number of scores deleted (or would be deleted in dry_run mode)
    """
    logger.info("Starting delete_duplicate_scores (delete_empty_scores=%s, dry_run=%s)", delete_empty_scores, dry_run)
    if dry_run:
        print("DRY RUN MODE: No files will be deleted")

    # Get score list
    score_uris = list_score_urls(solid_client, provider, profile, storage)
    if not score_uris:
        logger.info("No scores found")
        print("No scores found")
        return 0

    logger.info("Found %d score URI(s)", len(score_uris))
    print(f"Found {len(score_uris)} score URI(s)")

    # Load each score and build a list of scores
    scores = []
    for score_uri in score_uris:
        try:
            logger.debug("Loading score from URI: %s", score_uri)
            score = load_score_from_uri(solid_client, provider, profile, storage, score_uri)
            scores.append(score)
        except Exception as e:
            logger.warning("Error loading score %s: %s", score_uri, e)
            print(f"Error loading score {score_uri}: {e}")
            continue

    logger.info("Successfully loaded %d score(s)", len(scores))
    print(f"Successfully loaded {len(scores)} score(s)")

    # Make a Counter of external_uri to counts
    external_uri_counts = Counter(score.external_uri for score in scores)
    logger.info("External URI counts: %s", dict(external_uri_counts))

    # For each score, get a list of performances
    # If there are no performances and the count is > 1, delete the score
    deleted_count = 0
    for score in scores:
        external_uri = score.external_uri
        count = external_uri_counts[external_uri]

        logger.info("Processing score URI: %s", score.uri)
        logger.info("  External URI: %s", external_uri)
        logger.info("  Count for this external_uri: %d", count)
        print(f"Processing score: {score.uri}")
        print(f"  External URI: {external_uri}")
        print(f"  Count: {count}")

        # Check if we should process this score
        if count > 1:
            logger.info("  Score is a duplicate (count > 1), will check for performances")
        elif delete_empty_scores and count == 1:
            logger.info("  Score is unique but delete_empty_scores=True, will check for performances")
        else:
            logger.info("  Skipping: score is unique (count=1) and delete_empty_scores=False")
            print("  Skipping: score is unique (count=1) and delete_empty_scores=False")
            continue

        # Get performances for this score
        try:
            logger.debug("Getting performances for container: %s", score.performances_container)
            # Get the listing for the performances container
            listing = get_pod_listing(solid_client, provider, profile, score.performances_container)
            if listing is None:
                performance_urls = []
            else:
                performance_urls = get_contents_of_container(listing, score.performances_container)
        except Exception as e:
            logger.warning("Error getting performances for score %s: %s", score.uri, e)
            print(f"Error getting performances for score {score.uri}: {e}")
            performance_urls = []

        num_performances = len(performance_urls)
        logger.info("  Number of performances: %d", num_performances)
        print(f"  Performances: {num_performances}")

        # Never delete a score if it has at least one performance
        if num_performances > 0:
            logger.info("  Skipping: score has %d performance(s), will not delete", num_performances)
            print(f"  Skipping: score has {num_performances} performance(s), will not delete")
            continue

        # If there are no performances, delete the score
        action_prefix = "Would delete" if dry_run else "Deleting"
        logger.info("  %s score: no performances and meets deletion criteria", action_prefix.lower())
        print(f"  {action_prefix} duplicate score {score.uri} (external_uri: {external_uri}, no performances)")

        # Extract score_id from score URI (basename)
        score_id = os.path.basename(score.uri)

        # Construct timeline container URI
        timeline_container = os.path.join(storage, CLARA_CONTAINER_NAME, "timelines", score_id, "")

        # Delete resources in order:
        # 1. Segments file
        try:
            if dry_run:
                logger.debug("Would delete segments: %s", score.segments_uri)
                print(f"  Would delete segments: {score.segments_uri}")
            else:
                logger.debug("Deleting segments: %s", score.segments_uri)
                delete_resource(solid_client, provider, profile, score.segments_uri)
                print(f"  Deleted segments: {score.segments_uri}")
        except Exception as e:
            logger.error("Error deleting segments %s: %s", score.segments_uri, e)
            print(f"  Error deleting segments {score.segments_uri}: {e}")

        # 2. MEI file
        try:
            if dry_run:
                logger.debug("Would delete MEI: %s", score.mei_uri)
                print(f"  Would delete MEI: {score.mei_uri}")
            else:
                logger.debug("Deleting MEI: %s", score.mei_uri)
                delete_resource(solid_client, provider, profile, score.mei_uri)
                print(f"  Deleted MEI: {score.mei_uri}")
        except Exception as e:
            logger.error("Error deleting MEI %s: %s", score.mei_uri, e)
            print(f"  Error deleting MEI {score.mei_uri}: {e}")

        # 3. Timeline container (recursive delete)
        try:
            if dry_run:
                logger.debug("Would delete timeline container: %s", timeline_container)
                print(f"  Would delete timeline container: {timeline_container}")
            else:
                logger.debug("Deleting timeline container: %s", timeline_container)
                recursive_delete_from_pod(solid_client, provider, profile, timeline_container)
                print(f"  Deleted timeline container: {timeline_container}")
        except Exception as e:
            logger.error("Error deleting timeline container %s: %s", timeline_container, e)
            print(f"  Error deleting timeline container {timeline_container}: {e}")

        # 4. Performance container (recursive delete)
        try:
            if dry_run:
                logger.debug("Would delete performance container: %s", score.performances_container)
                print(f"  Would delete performance container: {score.performances_container}")
            else:
                logger.debug("Deleting performance container: %s", score.performances_container)
                recursive_delete_from_pod(solid_client, provider, profile, score.performances_container)
                print(f"  Deleted performance container: {score.performances_container}")
        except Exception as e:
            logger.error("Error deleting performance container %s: %s", score.performances_container, e)
            print(f"  Error deleting performance container {score.performances_container}: {e}")

        # 5. Score URI
        try:
            if dry_run:
                logger.debug("Would delete score URI: %s", score.uri)
                print(f"  Would delete score: {score.uri}")
            else:
                logger.debug("Deleting score URI: %s", score.uri)
                delete_resource(solid_client, provider, profile, score.uri)
                print(f"  Deleted score: {score.uri}")
        except Exception as e:
            logger.error("Error deleting score %s: %s", score.uri, e)
            print(f"  Error deleting score {score.uri}: {e}")

        deleted_count += 1

    if dry_run:
        logger.info("Would delete %d duplicate score(s) with no performances", deleted_count)
        print(f"Would delete {deleted_count} duplicate score(s) with no performances")
    else:
        logger.info("Deleted %d duplicate score(s) with no performances", deleted_count)
        print(f"Deleted {deleted_count} duplicate score(s) with no performances")
    return deleted_count
