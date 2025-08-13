import click
import flask
from flask.cli import AppGroup
from solidauth import client
from solidauth.solid import lookup_provider_from_profile

from trompaalign import extensions, tasks
from trompaalign.solid import get_storage_from_profile, upload_midi_to_pod

cli_api = AppGroup("api", help="Simulate the API")


@cli_api.command("add-score")
@click.argument("profile")
@click.argument("score_url")
@click.option("--celery", is_flag=True, help="Run the task in celery")
def cmd_add_score(profile, score_url, celery):
    """Add a score to a user's storage"""
    print(f"Adding score {score_url} to profile {profile} ({celery=})")

    if celery:
        task = tasks.add_score.delay(profile, score_url)
        print(f"Task created: {task.task_id}")
    else:
        tasks.add_score(profile, score_url)


@cli_api.command("align")
@click.argument("profile")
@click.argument("score_url")
@click.argument("midi_file", type=click.File("rb"))
@click.option("--celery", is_flag=True, help="Run the task in celery")
def cmd_align(profile, score_url, midi_file, celery):
    """Align a score to a recording"""

    provider = lookup_provider_from_profile(profile)
    storage = get_storage_from_profile(profile)

    use_client_id_document = flask.current_app.config["ALWAYS_USE_CLIENT_URL"]
    cl = client.SolidClient(extensions.backend.backend, use_client_id_document=use_client_id_document)
    midi_payload = midi_file.read()
    midi_url = upload_midi_to_pod(cl, provider, profile, storage, midi_payload)
    webmidi_url = None

    print(f"Aligning score {score_url} to recording {midi_url} and {midi_url} for profile {profile}")
    if celery:
        task = tasks.align_recording.delay(profile, score_url, webmidi_url, midi_url)
        print(f"Task created: {task.task_id}")
    else:
        tasks.align_recording(profile, score_url, webmidi_url, midi_url)
