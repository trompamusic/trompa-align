import json
import os

import click
from flask.cli import AppGroup
import requests
import requests.utils
from trompasolid.client import get_bearer_for_user

from trompaalign.solid import get_storage_from_profile, lookup_provider_from_profile, get_pod_listing, \
    CLARA_CONTAINER_NAME, create_clara_container, get_clara_listing_for_pod, upload_mei_to_pod, \
    create_and_save_structure, get_title_from_mei, upload_webmidi_to_pod, create_performance_container
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
@click.argument("profile")
@click.argument("container")
def cmd_list_container(profile, container):
    """Get the contents of a ontainer"""
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

    response = get_pod_listing(provider, profile, container)
    print(json.dumps(response, indent=2))


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

    listing = get_clara_listing_for_pod(provider, profile, storage)
    print(json.dumps(listing, indent=2))
    if listing is None:
        print("User storage doesn't include clara container. Use `create-clara` command")
        return
    else:
        for item in listing:
            # This returns 1 item for the actual url, which has ldp:contains: [list, of items]
            # but then also enumerates the list of items
            if item['@id'] == os.path.join(storage, CLARA_CONTAINER_NAME):
                print(item['@id'])
                print("  contains:")
                for cont in item.get('http://www.w3.org/ns/ldp#contains', []):
                    print("  -", cont['@id'])


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
@click.argument("profile")
@click.argument("resource")
def cmd_get_resource(profile, resource):
    """Get a resource, authenticating as a specific user"""
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

    headers = get_bearer_for_user(provider, profile, resource, 'GET')
    type_headers = {"Accept": "application/ld+json"}
    headers.update(type_headers)
    r = requests.get(resource, headers=headers)
    r.raise_for_status()
    print(json.dumps(r.json(), indent=2))


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
    for item in listing['@graph']:
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

    listing = get_clara_listing_for_pod(provider, profile, storage)
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


@cli.command("upload-performance")
@click.argument("profile")
@click.argument("file", type=click.Path(exists=True))
def cmd_upload_performance_to_pod(profile, file):
    """Upload a webmidi performance to a pod"""
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


@cli.command("create-performance-container")
@click.argument("profile")
@click.argument("mei_external_uri")
def cmd_create_performance_container(profile, mei_external_uri):
    """Create a container for a specific uri"""
    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return
    storage = get_storage_from_profile(profile)
    if not storage:
        print("Cannot find storage, quitting")
        return

    container = create_performance_container(provider, profile, storage, mei_external_uri)
    print(f"Created: {container}")


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
    headers = get_bearer_for_user(provider, profile, resource, 'OPTIONS')
    r = requests.options(resource, headers=headers)
    for h, v in r.headers.items():
        print(f"{h}: {v}")
    print(r.text)

@cli.command("align-recording")
@click.argument("profile")
@click.argument("score_url")
@click.argument("webmidi_url")
@click.argument("performance_container")
def cmd_align_recording(profile, score_url, webmidi_url, performance_container):
    """Run the alignment process """
    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return

    align_recording(profile, score_url, webmidi_url, performance_container)
