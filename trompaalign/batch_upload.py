import os
import mimetypes
from pathlib import Path
from typing import Optional

import rdflib
from rdflib.namespace import RDF
from rdflib import URIRef
import requests

from solidauth import client


def is_lock_expired_response(resp: requests.Response) -> bool:
    """Detect SolidCommunity lock timeout error responses.

    Looks for a JSON body like:
      {"statusCode":500, "message":"Lock expired after ..."}
    Falls back to substring search in text body.
    We've seen that solidcommunity.net returns a 500 error with a lock expired message if it takes more than 6 seconds
    to process the upload, however the file still appears to be uploaded and created successfully.
    """
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


def _with_trailing_slash(uri: str) -> str:
    return uri if uri.endswith("/") else uri + "/"


def container_exists(solid_client: client.SolidClient, provider: str, profile: str, container_uri: str) -> bool:
    """Return True if the LDP container exists, False if not.

    Tries HEAD first, then falls back to GET with Accept: text/turtle.
    """
    uri = _with_trailing_slash(container_uri)
    try:
        headers = solid_client.get_bearer_for_user(provider, profile, uri, "HEAD")
        r = requests.head(uri, headers=headers)
        if r.status_code == 404:
            return False
        if r.ok:
            return True
    except Exception:
        pass

    try:
        headers = solid_client.get_bearer_for_user(provider, profile, uri, "GET")
        headers.update({"Accept": "text/turtle"})
        r = requests.get(uri, headers=headers)
        if r.status_code == 404:
            return False
        if r.ok:
            return True
    except Exception:
        pass

    return False


def create_ldp_container(solid_client: client.SolidClient, provider: str, profile: str, container_uri: str):
    """
    Create an LDP container using rdflib instead of raw JSON.

    Args:
        solid_client: The Solid client instance
        provider: The provider URL
        profile: The profile URL
        container_uri: The URI where the container should be created
    """
    # Ensure container URIs always end with a trailing slash
    if not container_uri.endswith("/"):
        container_uri = container_uri + "/"

    headers = solid_client.get_bearer_for_user(provider, profile, container_uri, "PUT")

    # Create RDF graph for the container
    graph = rdflib.Graph()
    container_ref = URIRef(container_uri)

    # Add LDP container types
    ldp = rdflib.Namespace("http://www.w3.org/ns/ldp#")
    graph.add((container_ref, RDF.type, ldp.BasicContainer))
    graph.add((container_ref, RDF.type, ldp.Container))
    graph.add((container_ref, RDF.type, ldp.Resource))

    # Serialize as turtle
    turtle_data = graph.serialize(format="turtle")

    # Set headers for turtle content
    type_headers = {"Accept": "text/turtle", "content-type": "text/turtle"}
    headers.update(type_headers)

    r = requests.put(container_uri, data=turtle_data.encode("utf-8"), headers=headers)
    if r.status_code == 201:
        print(f"Successfully created container: {container_uri}")
    else:
        # Treat SolidCommunity lock timeout as success
        try:
            r.raise_for_status()
        except requests.exceptions.HTTPError as e:
            if is_lock_expired_response(r):
                print(f"Warning: provider lock timeout, treating container create as success for {container_uri}")
            else:
                print(f"Unexpected status creating container {container_uri}: {e}")
                print(f"Response: {r.text}")
                raise


def get_content_type(file_path: str) -> Optional[str]:
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

    r = requests.put(remote_uri, data=content, headers=headers)
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


def recursive_upload_directory(
    solid_client: client.SolidClient,
    provider: str,
    profile: str,
    local_directory: str,
    remote_base_uri: str,
    debug: bool = False,
):
    """
    Recursively upload a directory structure to a Solid pod.

    Args:
        solid_client: The Solid client instance
        provider: The provider URL
        profile: The profile URL
        local_directory: Path to the local directory to upload
        remote_base_uri: Base URI in the pod where files should be uploaded
        debug: If True, only print what would be uploaded without actually uploading
    """
    local_path = Path(local_directory)

    if not local_path.exists():
        raise FileNotFoundError(f"Directory {local_directory} does not exist")

    if not local_path.is_dir():
        raise ValueError(f"{local_directory} is not a directory")

    # First, collect all files and directories to upload
    files_to_upload = []
    dirs_to_create = set()

    for root, dirs, files in os.walk(local_path):
        root_path = Path(root)
        relative_path = root_path.relative_to(local_path)

        # Skip empty directories
        if not files and not dirs:
            continue

        # Add directory to create list if it has content
        if files or dirs:
            if relative_path == Path("."):
                # Root directory
                remote_dir_uri = remote_base_uri.rstrip("/") + "/"
            else:
                # Subdirectory
                remote_dir_uri = f"{remote_base_uri.rstrip('/')}/{relative_path.as_posix()}".rstrip("/") + "/"
            dirs_to_create.add(remote_dir_uri)

        # Add files to upload list
        for file in files:
            local_file_path = root_path / file
            cleaned_filename = clean_remote_filename(file)

            if relative_path == Path("."):
                # File in root directory
                remote_file_uri = f"{remote_base_uri.rstrip('/')}/{cleaned_filename}"
            else:
                # File in subdirectory
                remote_file_uri = f"{remote_base_uri.rstrip('/')}/{relative_path.as_posix()}/{cleaned_filename}"

            files_to_upload.append((str(local_file_path), remote_file_uri))

    if debug:
        print("DEBUG MODE - No actual uploads will be performed")
        print(f"Would create {len(dirs_to_create)} directories:")
        sorted_dirs = sorted(dirs_to_create)
        for dir_uri in sorted_dirs:
            print(f"  CREATE CONTAINER: {dir_uri}")

        print(f"Would upload {len(files_to_upload)} files:")
        for local_file_path, remote_file_uri in files_to_upload:
            content_type = get_content_type(local_file_path)
            content_type_str = f" (content-type: {content_type})" if content_type else " (no content-type)"
            print(f"  UPLOAD FILE: {local_file_path} -> {remote_file_uri}{content_type_str}")

        print(f"DEBUG SUMMARY: Would upload {len(files_to_upload)} files to {len(dirs_to_create)} directories")
    else:
        # Create directories first (in order)
        sorted_dirs = sorted(dirs_to_create)
        for dir_uri in sorted_dirs:
            if not container_exists(solid_client, provider, profile, dir_uri):
                create_ldp_container(solid_client, provider, profile, dir_uri)

        # Upload files
        for local_file_path, remote_file_uri in files_to_upload:
            upload_file_to_pod(solid_client, provider, profile, local_file_path, remote_file_uri)

        print(f"Successfully uploaded {len(files_to_upload)} files to {len(dirs_to_create)} directories")
