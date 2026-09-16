from trompaalign import cli, cli_api
from trompaalign.webserver import create_app, webserver_bp

app = create_app()

app.register_blueprint(webserver_bp)

app.cli.add_command(cli.cli)
app.cli.add_command(cli.db_bp)
app.cli.add_command(cli_api.cli_api)
