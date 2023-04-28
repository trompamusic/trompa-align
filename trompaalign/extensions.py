from flask_cors import CORS
from flask_redis import FlaskRedis
from flask_sqlalchemy import SQLAlchemy
from trompasolid.backend import SolidBackend
from trompasolid.backend.db_backend import DBBackend
from trompasolid.backend.redis_backend import RedisBackend


class BackendExtension:
    backend: SolidBackend

    def __init__(self, app=None):
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        if app.config["BACKEND"] == "db":
            self.backend = DBBackend(db.session)
        elif app.config["BACKEND"] == "redis":
            self.backend = RedisBackend(redis_client)


db = SQLAlchemy()
redis_client = FlaskRedis()
backend = BackendExtension()
cors = CORS()