from flask import Flask, render_template, redirect
from flask_socketio import SocketIO

# Initialize Flask app
app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

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
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)