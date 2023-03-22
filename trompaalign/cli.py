import json
import os
import uuid

import click
from flask.cli import AppGroup
import rdflib
import requests
import requests.utils
from trompasolid.client import get_bearer_for_user

from trompaalign.mei import get_metadata_for_mei
from trompaalign.solid import get_storage_from_profile, lookup_provider_from_profile, get_pod_listing, \
    CLARA_CONTAINER_NAME, create_clara_container, get_clara_listing_for_pod, upload_mei_to_pod

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


    headers = get_bearer_for_user(provider, profile, os.path.join(storage, CLARA_CONTAINER_NAME), 'DELETE')
    r = requests.delete(
        os.path.join(storage, CLARA_CONTAINER_NAME),
        headers=headers
    )


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

    upload_mei_to_pod(provider, profile, storage, url, payload, title=title)


@cli.command("upload-performance")
@click.argument("profile")
@click.argument("container")
@click.argument("file", type=click.Path(exists=True))
def cmd_upload_performance_to_pod(profile, container, file):
    """Upload a performance to a pod"""
    provider = lookup_provider_from_profile(profile)
    if not provider:
        print("Cannot find provider, quitting")
        return
    storage = get_storage_from_profile(profile)
    if not storage:
        print("Cannot find storage, quitting")
        return

    payload = open(file, "rb").read()
    filename = os.path.basename(file)
    print(file)

    resource = os.path.join(container, filename)
    print(f"Uploading file {resource}")
    headers = get_bearer_for_user(provider, profile, resource, 'PUT')
    headers["content-type"] = "application/json"
    # TODO: Encoding headers?
    r = requests.put(resource, data=payload, headers=headers)
    print(r.text)
