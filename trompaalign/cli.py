import json
import os
from urllib.parse import urlparse

import click
import requests
from trompaalign.extensions import db, backend
from flask.cli import AppGroup
from solidauth import client
from solidauth.db import Base

from trompaalign.solid import (
    CLARA_CONTAINER_NAME,
    add_score_to_list,
    create_and_save_structure,
    create_clara_container,
    find_score_for_external_uri,
    list_external_score_urls,
    get_contents_of_container,
    get_pod_listing,
    get_pod_listing_ttl,
    get_storage_from_profile,
    get_title_from_mei,
    http_options,
    lookup_provider_from_profile,
    patch_container_item_title,
    delete_acl_for_resource,
    set_resource_acl_private,
    set_resource_acl_public,
    update_score_list_bulk,
    upload_mei_to_pod,
    upload_midi_to_pod,
    upload_webmidi_to_pod,
)
from trompaalign import batch_upload
from trompaalign.tasks import align_recording

cli = AppGroup("solid", help="Solid commands")
db_bp = AppGroup("db", help="Database commands")


@db_bp.command("create-database")
def cmd_create_database():
    """Create a user in the database"""
    # This doesn't use the Flask-SQLAlchemy create_all method, as we have other
    # tables that aren't part of that extension's declarative base
    print("Creating database tables...")
    db.create_all()
    Base.metadata.create_all(db.engine)
    print("Done")


@cli.command("list-pod")
@click.argument("profile")
@click.option("--use-client-id-document", is_flag=True, help="Use client ID document instead of dynamic registration")
def cmd_list_containers_in_pod(profile, use_client_id_document):
    """List containers in a pod."""
    print(f"Looking up data for profile {profile}")
    cl = client.SolidClient(backend.backend, use_client_id_document)
    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return
    storage = get_storage_from_profile(profile)
    if not storage:
        print("Cannot find storage, quitting")
        return

    print(f"Storage: {storage}")
    print("Pod containers:")
    print(f"{provider=} {profile=}")
    listing = get_pod_listing(cl, provider, profile, storage)
    for item in listing["@graph"]:
        if "ldp:BasicContainer" in item.get("@type", []):
            print(" ", item.get("@id"))


@cli.command("list-container")
@click.option("--json/--ttl", "use_json", default=True)
@click.argument("profile")
@click.argument("container")
@click.option("--use-client-id-document", is_flag=True, help="Use client ID document instead of dynamic registration")
def cmd_list_container(use_json, profile, container, use_client_id_document):
    """Get the contents of a container"""
    print(f"Looking up data for profile {profile}")
    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return
    storage = get_storage_from_profile(profile)
    if not storage:
        print("Cannot find storage, quitting")
        return

    print(f"Storage: {storage}")

    cl = client.SolidClient(backend.backend, use_client_id_document)
    if use_json:
        response = get_pod_listing(cl, provider, profile, container)
        print(json.dumps(response, indent=2))
    else:
        response = get_pod_listing_ttl(cl, provider, profile, container)
        print(response)
    if response is not None:
        contents = get_contents_of_container(response, container)
        for item in contents:
            print("  -", item)


@cli.command("list-clara")
@click.argument("profile")
@click.option("--use-client-id-document", is_flag=True, help="Use client ID document instead of dynamic registration")
def cmd_check_pod_for_clara(profile, use_client_id_document):
    """List clara content in a pod.

    If a pod has a clara directory, list the items in it.
    If it doesn't, quit
    """
    print(f"Looking up data for profile {profile}")
    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return
    storage = get_storage_from_profile(profile)
    if not storage:
        print("Cannot find storage, quitting")
        return

    print(f"Storage: {storage}")

    cl = client.SolidClient(backend.backend, use_client_id_document)
    clara_container = os.path.join(storage, CLARA_CONTAINER_NAME)
    listing = get_pod_listing(cl, provider, profile, clara_container)
    print(json.dumps(listing, indent=2))
    if listing is None:
        print("User storage doesn't include clara container. Use `create-clara` command")
        return
    else:
        contents = get_contents_of_container(listing, clara_container)
        print(clara_container)
        for item in contents:
            print("  -", item)


@cli.command("create-clara")
@click.argument("profile")
@click.option("--use-client-id-document", is_flag=True, help="Use client ID document instead of dynamic registration")
def cmd_add_clara_to_pod(profile, use_client_id_document):
    """Create the base clara Container in a pod"""
    print(f"Looking up data for profile {profile}")
    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return
    storage = get_storage_from_profile(profile)
    if not storage:
        print("Cannot find storage, quitting")
        return

    cl = client.SolidClient(backend.backend, use_client_id_document)
    create_clara_container(cl, provider, profile, storage)


@cli.command("get-resource")
@click.option("--json/--ttl", "use_json", default=True)
@click.argument("profile")
@click.argument("resource")
@click.option("--use-client-id-document", is_flag=True, help="Use client ID document instead of dynamic registration")
def cmd_get_resource(use_json, profile, resource, use_client_id_document):
    """Get a resource"""
    print(f"Looking up data for profile {profile}")
    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return

    cl = client.SolidClient(backend.backend, use_client_id_document)
    headers = cl.get_bearer_for_user(provider, profile, resource, "GET")
    if use_json:
        type_headers = {"Accept": "application/ld+json"}
    else:
        type_headers = {"Accept": "text/turtle"}
    headers.update(type_headers)
    r = requests.get(resource, headers=headers)
    r.raise_for_status()
    if use_json:
        print(json.dumps(r.json(), indent=2))
    else:
        print(r.text)


@cli.command("patch-title")
@click.argument("profile")
@click.argument("container")
@click.argument("item")
@click.argument("title")
@click.option("--use-client-id-document", is_flag=True, help="Use client ID document instead of dynamic registration")
def cmd_patch_container_title(profile, container, item, title, use_client_id_document):
    print(f"Looking up data for profile {profile}")
    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return

    cl = client.SolidClient(backend.backend, use_client_id_document)
    patch_container_item_title(cl, provider, profile, container, item, title)


@cli.command("get-score-for-url")
@click.argument("profile")
@click.argument("score_url")
@click.option("--use-client-id-document", is_flag=True, help="Use client ID document instead of dynamic registration")
def cmd_get_score_for_url(profile, score_url, use_client_id_document):
    """Find the score container for a given score external URL"""
    print(f"Looking up data for profile {profile}")
    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return
    storage = get_storage_from_profile(profile)
    if not storage:
        print("Cannot find storage, quitting")
        return

    cl = client.SolidClient(backend.backend, use_client_id_document)
    score = find_score_for_external_uri(cl, provider, profile, storage, score_url)
    if score:
        print(f"External MEI URL is in this user's solid pod as {score}")


def recursive_delete_from_pod(solid_client, provider, profile, container):
    """
    A container listing has 2 types of data returned from a query:
     - the information about the container itself (has an ldp:contains section with
         all items in that container)
     - the information about each item in ldp:contains (including its @type)

    So, we loop through all items. If it's an ldp:Container (and not the main ID), recurse into it
    otherwise, just delete it.
    After recursing into it, delete the container itself, as it'll be empty.
    """
    listing = get_pod_listing(solid_client, provider, profile, container)
    for item in listing.get("@graph", []):
        item_id = item["@id"]
        # First item is ourselves, skip it
        if item_id == container:
            continue
        if "ldp:Container" in item["@type"]:
            # If the container has other containers, delete them
            recursive_delete_from_pod(solid_client, provider, profile, item["@id"])
        else:
            # Otherwise it's just a file, delete it.
            headers = solid_client.get_bearer_for_user(provider, profile, item_id, "DELETE")
            print(f"Delete file {item_id}")
            requests.delete(item_id, headers=headers)
    # Finally, delete the container itself
    headers = solid_client.get_bearer_for_user(provider, profile, container, "DELETE")
    requests.delete(container, headers=headers)


@cli.command("delete-clara")
@click.argument("profile")
@click.option("-c", "--container")
@click.option("--use-client-id-document", is_flag=True, help="Use client ID document instead of dynamic registration")
def cmd_delete_clara_container_from_pod(profile, container, use_client_id_document):
    """Delete the base clara Container in a pod"""
    print(f"Looking up data for profile {profile}")
    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return
    storage = get_storage_from_profile(profile)
    if not storage:
        print("Cannot find storage, quitting")
        return

    cl = client.SolidClient(backend.backend, use_client_id_document)
    if container is None:
        clara_container = os.path.join(storage, CLARA_CONTAINER_NAME)
    else:
        clara_container = os.path.join(storage, container)
    listing = get_pod_listing(cl, provider, profile, clara_container)
    if listing is None:
        print("Pod has no clara storage, quitting")
        return

    # To delete, we need to recursively delete everything one by one
    recursive_delete_from_pod(cl, provider, profile, clara_container)


@cli.command("delete")
@click.argument("profile")
@click.argument("resource")
@click.option("--use-client-id-document", is_flag=True, help="Use client ID document instead of dynamic registration")
def cmd_delete_resource(profile, resource, use_client_id_document):
    """Delete an item from a pod"""
    print(f"Looking up data for profile {profile}")
    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return

    cl = client.SolidClient(backend.backend, use_client_id_document)
    headers = cl.get_bearer_for_user(provider, profile, resource, "DELETE")
    requests.delete(resource, headers=headers)


@cli.command("upload-score")
@click.argument("profile")
@click.option("--url", default=None)
@click.option("--file", default=None)
@click.option("--title", default=None)
@click.option("--use-client-id-document", is_flag=True, help="Use client ID document instead of dynamic registration")
def cmd_upload_score_to_pod(profile, url, file, title, use_client_id_document):
    """Upload an MEI score to a pod"""
    print(f"Looking up data for profile {profile}")

    if not url and not file:
        print("Error: require one of url or file")
        return

    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return
    storage = get_storage_from_profile(profile)
    if not storage:
        print("Cannot find storage, quitting")
        return

    if file and not url:
        print("If you use --file you must set --url to a dummy value")
        return
    elif url and file:
        print("URL and File set, loading file from disk and using url as source")
        payload = open(file).read()
        filename = os.path.basename(file)
    else:
        print(f"Downloading file from {url}")
        filename = os.path.basename(url)
        r = requests.get(url)
        r.raise_for_status()
        payload = r.text

    cl = client.SolidClient(backend.backend, use_client_id_document)
    title = get_title_from_mei(payload, filename)
    mei_copy_uri = upload_mei_to_pod(cl, provider, profile, storage, payload)

    create_and_save_structure(cl, provider, profile, storage, title, payload, url, mei_copy_uri)


@cli.command("upload-webmidi")
@click.argument("profile")
@click.argument("file", type=click.Path(exists=True))
@click.option("--use-client-id-document", is_flag=True, help="Use client ID document instead of dynamic registration")
def cmd_upload_webmidi_to_pod(profile, file, use_client_id_document):
    """Upload a webmidi performance to a pod, convert to midi, and upload the midi"""
    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return
    storage = get_storage_from_profile(profile)
    if not storage:
        print("Cannot find storage, quitting")
        return

    payload = open(file, "rb").read()

    cl = client.SolidClient(backend.backend, use_client_id_document)
    resource = upload_webmidi_to_pod(cl, provider, profile, storage, payload)
    print(f"Uploaded: {resource}")


@cli.command("upload-midi")
@click.argument("profile")
@click.argument("file", type=click.Path(exists=True))
@click.option("--use-client-id-document", is_flag=True, help="Use client ID document instead of dynamic registration")
def cmd_upload_midi_to_pod(profile, file, use_client_id_document):
    """Upload a midi performance to a pod"""
    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return
    storage = get_storage_from_profile(profile)
    if not storage:
        print("Cannot find storage, quitting")
        return

    payload = open(file, "rb").read()

    cl = client.SolidClient(backend.backend, use_client_id_document)
    resource = upload_midi_to_pod(cl, provider, profile, storage, payload)
    print(f"Uploaded: {resource}")


@cli.command("add-turtle")
@click.argument("profile")
@click.argument("resource")
@click.argument("file", type=click.Path(exists=True))
@click.option("--use-client-id-document", is_flag=True, help="Use client ID document instead of dynamic registration")
def add_turtle(profile, resource, file, use_client_id_document):
    """Upload any file to a pod with text/turtle content type"""
    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return
    storage = get_storage_from_profile(profile)
    if not storage:
        print("Cannot find storage, quitting")
        return

    payload = open(file, "rb").read()
    print(f"Uploading file {resource}")
    cl = client.SolidClient(backend.backend, use_client_id_document)
    headers = cl.get_bearer_for_user(provider, profile, resource, "PUT")
    headers["content-type"] = "text/turtle"
    r = requests.put(resource, data=payload, headers=headers)
    print(r.text)


@cli.command("get-file")
@click.argument("profile")
@click.argument("resource")
@click.option("--save", is_flag=True, help="Save to local file (basename of resource)")
@click.option("--use-client-id-document", is_flag=True, help="Use client ID document instead of dynamic registration")
def get_file(profile, resource, save, use_client_id_document):
    """Get any file from a pod"""
    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return
    storage = get_storage_from_profile(profile)
    if not storage:
        print("Cannot find storage, quitting")
        return

    print(f"Getting file {resource}")
    cl = client.SolidClient(backend.backend, use_client_id_document)
    headers = cl.get_bearer_for_user(provider, profile, resource, "GET")
    r = requests.get(resource, headers=headers)
    r.raise_for_status()
    if save:
        parsed = urlparse(resource)
        filename = os.path.basename(parsed.path) or "index"
        with open(filename, "wb") as f:
            f.write(r.content)
        print(f"Saved to {filename}")
    else:
        print(r.text)


@cli.command("options")
@click.argument("profile")
@click.argument("resource")
@click.option("--use-client-id-document", is_flag=True, help="Use client ID document instead of dynamic registration")
def cmd_options(profile, resource, use_client_id_document):
    """run HTTP OPTIONS on a resource"""
    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return

    print(f"Running OPTIONS on {resource}")
    cl = client.SolidClient(backend.backend, use_client_id_document)
    headers, content = http_options(cl, provider, profile, resource)
    for h, v in headers.items():
        print(f"{h}: {v}")
    print(content)


@cli.command("align-recording")
@click.option("--midi/--webmidi", "is_midi")
@click.argument("profile")
@click.argument("score_url")
@click.argument("midi_url")
def cmd_align_recording(is_midi, profile, score_url, midi_url):
    """Run the alignment process"""
    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return

    if is_midi:
        midi_url = midi_url
        webmidi_url = None
    else:
        midi_url = None
        webmidi_url = midi_url
    align_recording(profile, score_url, webmidi_url, midi_url)


@cli.command("add-score-to-list")
@click.argument("profile")
@click.argument("score_url")
@click.option("--use-client-id-document", is_flag=True, help="Use client ID document instead of dynamic registration")
def cmd_add_score_to_list(profile, score_url, use_client_id_document):
    """Add a score URL to the score list"""
    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return
    storage = get_storage_from_profile(profile)
    if not storage:
        print("Cannot find storage, quitting")
        return

    cl = client.SolidClient(backend.backend, use_client_id_document)
    try:
        added = add_score_to_list(cl, provider, profile, storage, score_url)
        if added:
            print(f"Added {score_url} to scores list")
        else:
            print(f"Score {score_url} already exists in list")
    except requests.HTTPError as e:
        print(f"Failed to update score list: {e}")
        if e.response is not None:
            print(e.response.text)


@cli.command("update-score-list")
@click.argument("profile")
@click.option("--use-client-id-document", is_flag=True, help="Use client ID document instead of dynamic registration")
def cmd_update_score_list(profile, use_client_id_document):
    """Scan the user's scores/ container and update the score list with public URLs.

    Reads all score description resources in the Clara scores container, extracts mo:published_as URLs,
    deduplicates them, and writes them into the top-level scores-list in a single update.
    """
    print(f"Looking up data for profile {profile}")
    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return
    storage = get_storage_from_profile(profile)
    if not storage:
        print("Cannot find storage, quitting")
        return

    cl = client.SolidClient(backend.backend, use_client_id_document)
    urls = list_external_score_urls(cl, provider, profile, storage)
    if not urls:
        print("No external score URLs found in scores/ container")
        return
    added, total = update_score_list_bulk(cl, provider, profile, storage, urls)
    print(f"Found {len(urls)} external URLs; added {added}; total in score list now {total}")


@cli.command("recursive-upload-directory")
@click.argument("profile")
@click.argument("local_directory", type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.argument("remote_uri")
@click.option("--use-client-id-document", is_flag=True, help="Use client ID document instead of dynamic registration")
@click.option("--debug", is_flag=True, help="Debug mode: show what would be uploaded without actually uploading")
def cmd_recursive_upload_directory(profile, local_directory, remote_uri, use_client_id_document, debug):
    """Recursively upload a local directory to a Solid pod.

    This command will:
    - Create LDP containers for directories (only if they contain files)
    - Upload all files with appropriate content-types
    - Handle special filename patterns (files ending with $.ext)
    - Set content-type to text/xml for .xml files and text/turtle for .ttl files

    Use --debug to see what would be uploaded without actually performing the upload.
    """
    if debug:
        print(f"DEBUG: Analyzing directory {local_directory} for upload to {remote_uri}")
        print("DEBUG: Skipping profile validation in debug mode")
        # In debug mode, we don't need to validate the profile or create a client
        # We'll create a mock client just to pass to the function
        cl = None
        provider = "debug-provider"
        profile = profile
    else:
        print(f"Looking up data for profile {profile}")
        provider = lookup_provider_from_profile(profile)
        if not provider:
            print("Cannot find provider, quitting")
            return
        print(f"Uploading directory {local_directory} to {remote_uri}")
        cl = client.SolidClient(backend.backend, use_client_id_document)

    try:
        batch_upload.recursive_upload_directory(cl, provider, profile, local_directory, remote_uri, debug=debug)
        if not debug:
            print("Upload completed successfully")
    except Exception as e:
        print(f"Upload failed: {e}")
        raise


@cli.command("set-permissions")
@click.argument("profile")
@click.argument("resource")
@click.option("--public/--private", "is_public", default=None, help="Set resource ACL to public-read or private")
@click.option("--remove", is_flag=True, help="Delete the ACL resource for the target")
@click.option("--use-client-id-document", is_flag=True, help="Use client ID document instead of dynamic registration")
def cmd_set_permissions(profile, resource, is_public, remove, use_client_id_document):
    """Set ACL permissions of a resource to public-read or private.

    Public: owner Control/Read/Write, public Read
    Private: owner Control/Read/Write
    """
    print(f"Looking up data for profile {profile}")
    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return

    cl = client.SolidClient(backend.backend, use_client_id_document)

    # Validate option combinations
    if remove and is_public is not None:
        print("Error: --remove is mutually exclusive with --public/--private")
        return
    if not remove and is_public is None:
        print("Error: specify one of --public/--private or --remove")
        return

    try:
        if remove:
            acl_uri = delete_acl_for_resource(cl, provider, profile, resource)
            print(f"Deleted ACL: {acl_uri}")
        elif is_public:
            acl_uri = set_resource_acl_public(cl, provider, profile, resource)
            print(f"Set resource public-read. ACL: {acl_uri}")
        else:
            acl_uri = set_resource_acl_private(cl, provider, profile, resource)
            print(f"Set resource private. ACL: {acl_uri}")
    except requests.HTTPError as e:
        print(f"ACL update failed: {e}")
        if e.response is not None:
            print(e.response.text)
    except Exception as e:
        print(f"ACL update failed: {e}")
