"""Traversal and batch transfers for local directories and Solid pods."""

import os
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from solidauth import client

from trompaalign import solid


def walk_pod(solid_client, provider, profile, remote_uri):
    """Yield (URL, relative path, is_container), including the root and empty containers.

    Fetch only container listings. Navigation performs no local filesystem operations.
    """
    root = urlsplit(remote_uri)
    if root.scheme not in ("http", "https") or not root.netloc or root.query or root.fragment or root.username:
        raise ValueError("The remote container must be an HTTP(S) URL without credentials, query, or fragment")
    pending = [(remote_uri.rstrip("/") + "/", PurePosixPath())]
    while pending:
        container, relative = pending.pop()
        yield container, relative, True
        members = [
            (resource, relative / solid.container_member_name(container, resource))
            for resource in solid.list_container(solid_client, provider, profile, container)
        ]
        for resource, path in members:
            if resource.endswith("/"):
                pending.append((resource, path))
            else:
                yield resource, path, False


def recursive_get(solid_client, provider, profile, remote_uri, local_directory):
    """Download a container under its basename in local_directory, without overwriting files."""
    local_root = Path(local_directory) / solid.container_basename(remote_uri)
    count = 0
    for resource, relative, is_container in walk_pod(solid_client, provider, profile, remote_uri):
        destination = local_root / relative
        if destination.is_symlink():
            raise ValueError(f"Refusing to follow local symlink: {destination}")
        if is_container:
            destination.mkdir(parents=True, exist_ok=True)
        else:
            if destination.exists():
                raise FileExistsError(f"Refusing to overwrite existing file: {destination}")
            solid.save_resource_from_pod(solid_client, provider, profile, resource, destination, overwrite=False)
            count += 1
            print(f"Saved {resource} -> {destination}")
    return count


def recursive_upload_directory(
    solid_client: client.SolidClient | None,
    provider: str,
    profile: str,
    local_directory: str,
    remote_base_uri: str,
    debug: bool = False,
):
    """
    Recursively upload a directory structure to a Solid pod.

    Args:
        solid_client: The Solid client instance, or None in debug mode
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
            cleaned_filename = solid.clean_remote_filename(file)

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
            content_type = solid.get_content_type(local_file_path)
            content_type_str = f" (content-type: {content_type})" if content_type else " (no content-type)"
            print(f"  UPLOAD FILE: {local_file_path} -> {remote_file_uri}{content_type_str}")

        print(f"DEBUG SUMMARY: Would upload {len(files_to_upload)} files to {len(dirs_to_create)} directories")
    else:
        assert solid_client is not None, "A SolidClient is required unless debug=True"
        # Create directories first (in order)
        sorted_dirs = sorted(dirs_to_create)
        for dir_uri in sorted_dirs:
            if not solid.container_exists(solid_client, provider, profile, dir_uri):
                solid.create_ldp_container(solid_client, provider, profile, dir_uri)

        # Upload files
        for local_file_path, remote_file_uri in files_to_upload:
            solid.upload_file_to_pod(solid_client, provider, profile, local_file_path, remote_file_uri)

        print(f"Successfully uploaded {len(files_to_upload)} files to {len(dirs_to_create)} directories")
