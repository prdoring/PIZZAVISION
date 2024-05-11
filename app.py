import json
from flask import Flask, render_template, request, redirect, url_for
from flask_socketio import SocketIO, emit
from tinydb import TinyDB, Query

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
socketio = SocketIO(app)

# Initialize the database
db = TinyDB('db.json')
User = Query()

def load_options():
    with open('options.json', 'r', encoding='utf-8' ) as json_file:
        data = json.load(json_file)
    return data['options']

def load_vote_options():
    with open('options.json', 'r') as json_file:
        data = json.load(json_file)
    return data['votes']

@app.route('/')
def index():
    options = load_options()
    vo = load_vote_options()
    return render_template('index.html', options=options, votes = vo)

@app.route('/results')
def results():
    # Retrieve all votes from the database
    votes = [vote['rank'] for vote in db.all()]
    vo = load_vote_options()
    ranked_results = calculate_ranked_choice(votes, vo)
    return render_template('results.html', ranked_results=ranked_results)


@socketio.on('rankchanged')
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

def calculate_ranked_choice(votes, vo):
    # Initialize an empty dictionary to hold points for each candidate.
    candidate_points = {}

    # Assuming each vote list contains candidate labels as strings and can vary in labels
    for vote in votes:
        for idx, candidate in enumerate(vote):
            if idx < len(vo):  
                points = vo[idx]  
                if candidate in candidate_points:
                    candidate_points[candidate] += points
                else:
                    candidate_points[candidate] = points

    # Ensure all possible candidates are included even if they have 0 points
    all_candidates = set([cand for sublist in votes for cand in sublist])  # Extract all unique candidates
    for candidate in all_candidates:
        if candidate not in candidate_points:
            candidate_points[candidate] = 0

    # Return a sorted list of tuples by points in descending order
    return sorted(candidate_points.items(), key=lambda item: item[1], reverse=True)

def get_color(points, max_points, min_points):
    if max_points == min_points:  # Avoid division by zero
        return '#4CAF50'  # Return green if all are equal
    ratio = (points - min_points) / (max_points - min_points)
    r = int((255 * (1 - ratio)))
    g = int((255 * ratio))
    b = 0
    return f'rgb({r},{g},{b})'


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)  # Accessible on your local network
