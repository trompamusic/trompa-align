from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from solidauth.backend import SolidBackend
from solidauth.backend.db_backend import DBBackend


class BackendExtension:
    backend: SolidBackend

    def __init__(self, app=None):
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        self.backend = DBBackend(db.session)


db = SQLAlchemy()
backend = BackendExtension()
cors = CORS()
