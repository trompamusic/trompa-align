import click
from flask.cli import AppGroup

from trompaalign import tasks

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
