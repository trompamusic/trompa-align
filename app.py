from trompaalign.webserver import webserver_bp, create_app

app = create_app()

app.register_blueprint(webserver_bp)
