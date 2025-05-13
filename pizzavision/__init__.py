from flask import Blueprint
from flask_socketio import SocketIO

# Create the blueprint
voting_bp = Blueprint('voting', __name__, 
                      url_prefix='/voting',
                      template_folder='templates',
                      static_folder='static',
                      static_url_path='/voting/static')

# Reference to the main app's SocketIO instance (will be set during registration)
socketio = None

# Import routes after creating blueprint to avoid circular imports
from . import routes


# Define SocketIO event handlers
def register_socketio_handlers(socket_io):
    """Register SocketIO event handlers"""
    from tinydb import TinyDB, Query
    from .utils import get_file_path
    
    # Initialize the database
    db_path = get_file_path('db.json')
    db = TinyDB(db_path)
    User = Query()
    
    @socket_io.on('nameChanged')
    def on_namechange(data):
        old_name = data['old_name']
        new_name = data['new_name']
        
        # Update the user's name in the database
        search_result = db.search(User.user == old_name)
        if search_result:
            # If the user already has entries, update their name
            db.update({'user': new_name}, User.user == old_name)
            print(f"Username changed from '{old_name}' to '{new_name}'")
        else:
            # If this is a new user (no previous rankings), just log it
            print(f"New user registered: '{new_name}'")
        
        # Emit an event to all clients to notify of the name change
        socket_io.emit('userRenamed', {'old_name': old_name, 'new_name': new_name}, broadcast=True)

    @socket_io.on('rankchanged')
    def on_rankchange(data):
        user = data['user']
        rank = data['rank']
        # Check if user already has an entry, update if they do, add if they don't
        search_result = db.search(User.user == user)
        if search_result:
            db.update({'rank': rank}, User.user == user)
        else:
            db.insert({'user': user, 'rank': rank})
        print(f"{user}'s new ranking: {rank}")