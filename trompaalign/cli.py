import json
import os
from datetime import datetime, timezone
from urllib.parse import urlparse

import click
import requests
from rdflib.namespace import RDF
from trompaalign.extensions import db, backend
from flask import current_app
from flask.cli import AppGroup
from solidauth import client, httpclient
from solidauth.migrations import upgrade

from trompaalign.solid import (
    CLARA_CONTAINER_NAME,
    LDP,
    add_score_to_list,
    create_and_save_structure,
    create_clara_container,
    delete_duplicate_scores,
    delete_resource,
    find_score_for_external_uri,
    list_external_score_urls,
    get_contents_of_container,
    get_pod_listing,
    get_pod_listing_ttl,
    get_pod_response,
    get_storage_from_profile,
    get_title_from_mei,
    http_options,
    lookup_provider_from_profile,
    patch_container_item_title,
    parse_pod_graph,
    recursive_delete_from_pod,
    save_resource_from_pod,
    delete_acl_for_resource,
    set_resource_acl_private,
    set_resource_acl_public,
    update_score_list_bulk,
    upload_mei_to_pod,
    upload_midi_to_pod,
    upload_webmidi_to_pod,
)
from trompaalign import batch
from trompaalign.tasks import align_recording

cli = AppGroup("solid", help="Solid commands")
db_bp = AppGroup("db", help="Database commands")


@db_bp.command("create-database")
def cmd_create_database():
    """Create application and authentication database tables."""
    print("Creating database tables...")
    db.create_all()
    upgrade(db.engine)
    print("Done")


@db_bp.command("upgrade")
def cmd_upgrade_database():
    """Apply authentication database migrations."""
    upgrade(db.engine)
    click.echo("Database upgraded")


@cli.command("list-pod")
@click.argument("profile")
def cmd_list_containers_in_pod(profile):
    """List containers in a pod."""
    print(f"Looking up data for profile {profile}")
    cl = client.SolidClient(backend.backend, client_id_document_url=current_app.config["CLIENT_ID_DOCUMENT_URL"])
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
    graph = parse_pod_graph(listing, storage)
    for resource in graph.subjects(RDF.type, LDP.BasicContainer):
        print(" ", resource)


@cli.command("list-container")
@click.option("--json/--ttl", "use_json", default=True)
@click.argument("profile")
@click.argument("container")
def cmd_list_container(use_json, profile, container):
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

    cl = client.SolidClient(backend.backend, client_id_document_url=current_app.config["CLIENT_ID_DOCUMENT_URL"])
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
def cmd_check_pod_for_clara(profile):
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

    cl = client.SolidClient(backend.backend, client_id_document_url=current_app.config["CLIENT_ID_DOCUMENT_URL"])
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
def cmd_add_clara_to_pod(profile):
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

    cl = client.SolidClient(backend.backend, client_id_document_url=current_app.config["CLIENT_ID_DOCUMENT_URL"])
    create_clara_container(cl, provider, profile, storage)


@cli.command("get-resource")
@click.option("--json/--ttl", "use_json", default=True)
@click.argument("profile")
@click.argument("resource")
def cmd_get_resource(use_json, profile, resource):
    """Get a resource"""
    print(f"Looking up data for profile {profile}")
    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return

    cl = client.SolidClient(backend.backend, client_id_document_url=current_app.config["CLIENT_ID_DOCUMENT_URL"])
    accept = "application/ld+json" if use_json else "text/turtle"
    r = get_pod_response(cl, provider, profile, resource, accept=accept)
    if use_json:
        print(json.dumps(r.json(), indent=2))
    else:
        print(r.text)


@cli.command("patch-title")
@click.argument("profile")
@click.argument("container")
@click.argument("item")
@click.argument("title")
def cmd_patch_container_title(profile, container, item, title):
    print(f"Looking up data for profile {profile}")
    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return

    cl = client.SolidClient(backend.backend, client_id_document_url=current_app.config["CLIENT_ID_DOCUMENT_URL"])
    patch_container_item_title(cl, provider, profile, container, item, title)


@cli.command("get-score-for-url")
@click.argument("profile")
@click.argument("score_url")
def cmd_get_score_for_url(profile, score_url):
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

    cl = client.SolidClient(backend.backend, client_id_document_url=current_app.config["CLIENT_ID_DOCUMENT_URL"])
    score = find_score_for_external_uri(cl, provider, profile, storage, score_url)
    if score:
        print(f"External MEI URL is in this user's solid pod as {score}")


@cli.command("recursive-delete")
@click.argument("profile")
@click.argument("container")
def cmd_recursive_delete(profile, container):
    """Delete CONTAINER and its contents recursively. CONTAINER is a full URL."""
    print(f"Looking up data for profile {profile}")
    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return
    cl = client.SolidClient(backend.backend, client_id_document_url=current_app.config["CLIENT_ID_DOCUMENT_URL"])
    recursive_delete_from_pod(cl, provider, profile, container)


@cli.command("delete")
@click.argument("profile")
@click.argument("resource")
def cmd_delete_resource(profile, resource):
    """Delete an item from a pod"""
    print(f"Looking up data for profile {profile}")
    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return

    cl = client.SolidClient(backend.backend, client_id_document_url=current_app.config["CLIENT_ID_DOCUMENT_URL"])
    delete_resource(cl, provider, profile, resource)


@cli.command("upload-score")
@click.argument("profile")
@click.option("--url", default=None)
@click.option("--file", default=None)
@click.option("--title", default=None)
def cmd_upload_score_to_pod(profile, url, file, title):
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
        r = httpclient.get(url)
        r.raise_for_status()
        payload = r.text

    cl = client.SolidClient(backend.backend, client_id_document_url=current_app.config["CLIENT_ID_DOCUMENT_URL"])
    title = get_title_from_mei(payload, filename)
    mei_copy_uri = upload_mei_to_pod(cl, provider, profile, storage, payload)

    create_and_save_structure(cl, provider, profile, storage, title, payload, url, mei_copy_uri)


@cli.command("upload-webmidi")
@click.argument("profile")
@click.argument("file", type=click.Path(exists=True))
def cmd_upload_webmidi_to_pod(profile, file):
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

    cl = client.SolidClient(backend.backend, client_id_document_url=current_app.config["CLIENT_ID_DOCUMENT_URL"])
    resource = upload_webmidi_to_pod(cl, provider, profile, storage, payload)
    print(f"Uploaded: {resource}")


@cli.command("upload-midi")
@click.argument("profile")
@click.argument("file", type=click.Path(exists=True))
def cmd_upload_midi_to_pod(profile, file):
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

    cl = client.SolidClient(backend.backend, client_id_document_url=current_app.config["CLIENT_ID_DOCUMENT_URL"])
    resource = upload_midi_to_pod(cl, provider, profile, storage, payload)
    print(f"Uploaded: {resource}")


@cli.command("add-turtle")
@click.argument("profile")
@click.argument("resource")
@click.argument("file", type=click.Path(exists=True))
def add_turtle(profile, resource, file):
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
    cl = client.SolidClient(backend.backend, client_id_document_url=current_app.config["CLIENT_ID_DOCUMENT_URL"])
    headers = cl.get_bearer_for_user(provider, profile, resource, "PUT")
    headers["content-type"] = "text/turtle"
    r = httpclient.put(resource, data=payload, headers=headers)
    print(r.text)


@cli.command("add-jsonld")
@click.argument("profile")
@click.argument("resource")
@click.argument("file", type=click.Path(exists=True))
def add_jsonld(profile, resource, file):
    """Upload any file to a pod with application/ld+json content type"""
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
    cl = client.SolidClient(backend.backend, client_id_document_url=current_app.config["CLIENT_ID_DOCUMENT_URL"])
    headers = cl.get_bearer_for_user(provider, profile, resource, "PUT")
    headers["content-type"] = "application/ld+json"
    r = httpclient.put(resource, data=payload, headers=headers)
    print(r.text)


@cli.command("get-file")
@click.argument("profile")
@click.argument("resource")
@click.option("--save", is_flag=True, help="Save to local file (basename of resource)")
def get_file(profile, resource, save):
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
    cl = client.SolidClient(backend.backend, client_id_document_url=current_app.config["CLIENT_ID_DOCUMENT_URL"])
    if save:
        parsed = urlparse(resource)
        filename = os.path.basename(parsed.path) or "index"
        save_resource_from_pod(cl, provider, profile, resource, filename, overwrite=True)
        print(f"Saved to {filename}")
    else:
        print(get_pod_response(cl, provider, profile, resource).text)


@cli.command("recursive-get")
@click.argument("profile")
@click.argument("remote_uri")
@click.argument("local_directory", type=click.Path(file_okay=False))
def cmd_recursive_get(profile, remote_uri, local_directory):
    """Download REMOTE_URI recursively to LOCAL_DIRECTORY."""
    try:
        provider = lookup_provider_from_profile(profile)
        if not provider:
            raise click.ClickException("Cannot find provider for profile")
        cl = client.SolidClient(backend.backend, client_id_document_url=current_app.config["CLIENT_ID_DOCUMENT_URL"])
        count = batch.recursive_get(cl, provider, profile, remote_uri, local_directory)
    except click.ClickException:
        raise
    except Exception as exc:
        raise click.ClickException(f"Download failed: {exc}") from exc
    click.echo(f"Downloaded {count} file(s) to {local_directory}")


@cli.command("options")
@click.argument("profile")
@click.argument("resource")
def cmd_options(profile, resource):
    """run HTTP OPTIONS on a resource"""
    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return

    print(f"Running OPTIONS on {resource}")
    cl = client.SolidClient(backend.backend, client_id_document_url=current_app.config["CLIENT_ID_DOCUMENT_URL"])
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
    label = datetime.now(timezone.utc).isoformat(timespec="seconds")
    align_recording(profile, score_url, webmidi_url, midi_url, label)


@cli.command("add-score-to-list")
@click.argument("profile")
@click.argument("score_url")
def cmd_add_score_to_list(profile, score_url):
    """Add a score URL to the score list"""
    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return
    storage = get_storage_from_profile(profile)
    if not storage:
        print("Cannot find storage, quitting")
        return

    cl = client.SolidClient(backend.backend, client_id_document_url=current_app.config["CLIENT_ID_DOCUMENT_URL"])
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
def cmd_update_score_list(profile):
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

    cl = client.SolidClient(backend.backend, client_id_document_url=current_app.config["CLIENT_ID_DOCUMENT_URL"])
    urls = list_external_score_urls(cl, provider, profile, storage)
    if not urls:
        print("No external score URLs found in scores/ container")
        return
    added, total = update_score_list_bulk(cl, provider, profile, storage, urls)
    print(f"Found {len(urls)} external URLs; added {added}; total in score list now {total}")


@cli.command("delete-duplicate-scores")
@click.argument("profile")
@click.option(
    "--delete-empty-scores",
    is_flag=True,
    help="Also delete scores with no performances even if they are unique (count == 1)",
)
@click.option("--dry-run", is_flag=True, help="Show what would be deleted without actually deleting anything")
def cmd_delete_duplicate_scores(profile, delete_empty_scores, dry_run):
    """Delete duplicate scores from the scores/ container.

    Deletes scores that have no performances. By default, only deletes duplicates
    (scores with the same external_uri where count > 1). With --delete-empty-scores,
    also deletes unique scores (count == 1) if they have no performances.
    """
    if dry_run:
        print("DRY RUN MODE: No files will be deleted")
    print(f"Looking up data for profile {profile}")
    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return

    storage = get_storage_from_profile(profile)
    if not storage:
        print("Cannot find storage, quitting")
        return

    cl = client.SolidClient(backend.backend, client_id_document_url=current_app.config["CLIENT_ID_DOCUMENT_URL"])
    deleted_count = delete_duplicate_scores(
        cl, provider, profile, storage, delete_empty_scores=delete_empty_scores, dry_run=dry_run
    )
    if dry_run:
        print(f"Total would be deleted: {deleted_count} score(s)")
    else:
        print(f"Total deleted: {deleted_count} score(s)")


@cli.command("recursive-upload-directory")
@click.argument("profile")
@click.argument("local_directory", type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.argument("remote_uri")
@click.option("--debug", is_flag=True, help="Debug mode: show what would be uploaded without actually uploading")
def cmd_recursive_upload_directory(profile, local_directory, remote_uri, debug):
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
        cl = None
        provider = "debug-provider"
    else:
        print(f"Looking up data for profile {profile}")
        provider = lookup_provider_from_profile(profile)
        if not provider:
            print("Cannot find provider, quitting")
            return
        print(f"Uploading directory {local_directory} to {remote_uri}")
        cl = client.SolidClient(backend.backend, client_id_document_url=current_app.config["CLIENT_ID_DOCUMENT_URL"])

    try:
        batch.recursive_upload_directory(cl, provider, profile, local_directory, remote_uri, debug=debug)
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
def cmd_set_permissions(profile, resource, is_public, remove):
    """Set ACL permissions of a resource to public-read or private.

    Public: owner Control/Read/Write, public Read
    Private: owner Control/Read/Write
    """
    print(f"Looking up data for profile {profile}")
    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return

    cl = client.SolidClient(backend.backend, client_id_document_url=current_app.config["CLIENT_ID_DOCUMENT_URL"])

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
