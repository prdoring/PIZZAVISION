import hashlib
import os

from dotenv import load_dotenv
load_dotenv()

from flask import Flask, render_template, redirect
from flask_socketio import SocketIO

# Initialize Flask app
app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

# Signing key for the admin session cookie (see routes.admin_panel).
#
# Derived from ADMIN_PASSWORD rather than being its own managed secret: it
# gives a key that stays stable across Cloud Run cold starts (so the host
# isn't logged out every time the instance scales from zero) without adding
# another env var to keep in sync. Rotating the admin password invalidates
# existing admin sessions, which is the behaviour we want anyway.
# SECRET_KEY overrides it if you'd rather manage the two independently.
app.secret_key = os.environ.get('SECRET_KEY') or hashlib.sha256(
    f"pv-admin-session:{os.environ.get('ADMIN_PASSWORD', 'changeme')}".encode()
).hexdigest()
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# Cloud Run terminates TLS upstream and always serves us over HTTPS; locally
# we're on plain http, so only set the Secure flag when deployed.
app.config['SESSION_COOKIE_SECURE'] = bool(os.environ.get('GOOGLE_CLOUD_PROJECT'))

# Initialize SocketIO
socketio = SocketIO(app)

# Import and register the voting blueprint
from pizzavision import voting_bp, register_socketio_handlers
import pizzavision

# Pass the socketio instance to the blueprint
pizzavision.socketio = socketio

# Register the blueprint
app.register_blueprint(voting_bp, url_prefix='/pizzavision')

# Register the blueprint's socketio handlers
register_socketio_handlers(socketio)

# Main app routes
@app.route('/')
def index():
    """Main app homepage"""
    return redirect("/pizzavision")

# If you want a simple string response instead of a template:
# def index():
#     return "Welcome to the main app! The voting app is available at <a href='/voting'>Voting App</a>"

# Additional main app routes can be added here
@app.route('/about')
def about():
    return "About the main application"

# You can add more routes specific to your main app here

if __name__ == '__main__':
    # Use socketio.run instead of app.run for proper WebSocket support
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    socketio.run(app, host='0.0.0.0', port=port, debug=debug)