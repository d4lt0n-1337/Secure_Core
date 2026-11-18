import os
import sys
import pytest


# Allow importing `app` package when running from repo root
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
SERVER_DIR = os.path.join(ROOT, 'server')
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)


@pytest.fixture(scope='session')
def flask_app():
    from app import create_app
    from app.extensions import db

    app = create_app('testing')
    app.config.update(
        TESTING=True,
    )

    # For the in-memory sqlite test DB, create the schema once for the session.
    with app.app_context():
        db.create_all()

    return app


@pytest.fixture()
def app_context(flask_app):
    with flask_app.app_context():
        yield


@pytest.fixture(autouse=True)
def _db_rollback_between_tests(app_context, flask_app):
    """Keep tests isolated.

    The app uses an in-memory sqlite DB in testing; this rolls back any open
    transaction state between tests.
    """
    from app.extensions import db

    yield
    db.session.rollback()
