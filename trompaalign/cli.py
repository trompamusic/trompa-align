import json
import os

import click
from flask.cli import AppGroup
import requests
import requests.utils
from trompasolid.client import get_bearer_for_user

from trompaalign.solid import get_storage_from_profile, lookup_provider_from_profile, get_pod_listing, \
    CLARA_CONTAINER_NAME, create_clara_container, upload_mei_to_pod, \
    create_and_save_structure, get_title_from_mei, upload_webmidi_to_pod, \
    get_contents_of_container, find_score_for_external_uri, upload_midi_to_pod, get_pod_listing_ttl, \
    patch_container_item_title, http_options
from trompaalign.tasks import align_recording

cli = AppGroup("solid", help="Solid commands")


@cli.command("list-pod")
@click.argument("profile")
def cmd_list_containers_in_pod(profile):
    """List containers in a pod.
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
    print("Pod containers:")
    print(f"{provider=} {profile=}")
    listing = get_pod_listing(provider, profile, storage)
    for item in listing['@graph']:
        if 'ldp:BasicContainer' in item.get('@type', []):
            print(" ", item.get('@id'))


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

    if use_json:
        response = get_pod_listing(provider, profile, container)
        print(json.dumps(response, indent=2))
    else:
        response = get_pod_listing_ttl(provider, profile, container)
        print(response)
    return
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

    clara_container = os.path.join(storage, CLARA_CONTAINER_NAME)
    listing = get_pod_listing(provider, profile, clara_container)
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

    create_clara_container(provider, profile, storage)



@cli.command("get-resource")
@click.option("--json/--ttl", "use_json", default=True)
@click.argument("profile")
@click.argument("resource")
def cmd_get_resource(use_json, profile, resource):
    """Get a resource, authenticating as a specific user"""
    print(f"Looking up data for profile {profile}")
    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return

    headers = get_bearer_for_user(provider, profile, resource, 'GET')
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
def cmd_patch_container_title(profile, container, item, title):
    print(f"Looking up data for profile {profile}")
    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return

    patch_container_item_title(provider, profile, container, item, title)


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

    score = find_score_for_external_uri(provider, profile, storage, score_url)
    if score:
        print(f"External MEI URL is in this user's solid pod as {score}")


def recursive_delete_from_pod(provider, profile, container):
    """
    A container listing has 2 types of data returned from a query:
     - the information about the container itself (has an ldp:contains section with
         all items in that container)
     - the information about each item in ldp:contains (including its @type)

    So, we loop through all items. If it's an ldp:Container (and not the main ID), recurse into it
    otherwise, just delete it.
    After recursing into it, delete the container itself, as it'll be empty.
    """
    listing = get_pod_listing(provider, profile, container)
    for item in listing.get('@graph', []):
        item_id = item['@id']
        # First item is ourselves, skip it
        if item_id == container:
            continue
        if "ldp:Container" in item['@type']:
            # If the container has other containers, delete them
            recursive_delete_from_pod(provider, profile, item['@id'])
        else:
            # Otherwise it's just a file, delete it.
            headers = get_bearer_for_user(provider, profile, item_id, 'DELETE')
            r = requests.delete(item_id, headers=headers)
    # Finally, delete the container itself
    headers = get_bearer_for_user(provider, profile, container, 'DELETE')
    r = requests.delete(container, headers=headers)


@cli.command("delete-clara")
@click.argument("profile")
def cmd_delete_clara_container_from_pod(profile):
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

    clara_container = os.path.join(storage, CLARA_CONTAINER_NAME)
    listing = get_pod_listing(provider, profile, clara_container)
    if listing is None:
        print("Pod has no clara storage, quitting")
        return

    # To delete, we need to recursively delete everything one by one
    clara_container = os.path.join(storage, CLARA_CONTAINER_NAME)
    recursive_delete_from_pod(provider, profile, clara_container)


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
    else:
        print(f"Downloading file from {url}")
        r = requests.get(url)
        r.raise_for_status()
        payload = r.text

    title = get_title_from_mei(payload)
    mei_copy_uri = upload_mei_to_pod(provider, profile, storage, payload)

    create_and_save_structure(provider, profile, storage, title, payload, url, mei_copy_uri)


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

    resource = upload_webmidi_to_pod(provider, profile, storage, payload)
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

    resource = upload_midi_to_pod(provider, profile, storage, payload)
    print(f"Uploaded: {resource}")


@cli.command("add-turtle")
@click.argument("profile")
@click.argument("resource")
@click.argument("file", type=click.Path(exists=True))
def add_turtle(profile, resource, file):
    """Upload any file to a pod"""
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
    headers = get_bearer_for_user(provider, profile, resource, 'PUT')
    headers["content-type"] = "text/turtle"
    r = requests.put(resource, data=payload, headers=headers)
    print(r.text)


@cli.command("get-turtle")
@click.argument("profile")
@click.argument("resource")
def get_turtle(profile, resource):
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
    headers = get_bearer_for_user(provider, profile, resource, 'GET')
    r = requests.get(resource, headers=headers)
    print(r.text)

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
    headers, content = http_options(provider, profile, resource)
    for h, v in headers.items():
        print(f"{h}: {v}")
    print(content)


@cli.command("align-recording")
@click.option("--midi/--webmidi", 'is_midi')
@click.argument("profile")
@click.argument("score_url")
@click.argument("midi_url")
@click.argument("performance_container")
def cmd_align_recording(is_midi, profile, score_url, midi_url, performance_container):
    """Run the alignment process """
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
    align_recording(profile, score_url, webmidi_url, midi_url, performance_container)
