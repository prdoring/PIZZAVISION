from flask import Blueprint

# Create the blueprint
voting_bp = Blueprint('voting', __name__,
                      url_prefix='/voting',
                      template_folder='templates',
                      static_folder='static',
                      static_url_path='/voting/static')

# Reference to the main app's SocketIO instance (set during registration in pizzavision.py)
socketio = None

# Import routes after creating blueprint to avoid circular imports.
# routes.py also defines register_socketio_handlers, which is what pizzavision.py calls.
from . import routes
from .routes import register_socketio_handlers  # re-export

__all__ = ['voting_bp', 'register_socketio_handlers']
