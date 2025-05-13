import json
import unicodedata
import re
from collections import defaultdict
from pathlib import Path
from typing import List

import os


# Helper function to get absolute paths to files
def get_file_path(filename):
    """Get absolute path to a file, supporting both blueprint and main app contexts"""
    # First, try to find in the blueprint's directory
    blueprint_path = os.path.join(os.path.dirname(__file__), filename)
    if os.path.exists(blueprint_path):
        return blueprint_path
    
    # If not found, try the project root
    root_path = os.path.join(os.getcwd(), filename)
    return root_path

def load_options(filename="pizzavision/options.json") -> List[str]:
    """Return the list of entry labels, no matter which JSON version is saved."""
    path = get_file_path(filename)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    raw_options = data.get("options", [])

    # New structure → list of dicts
    if raw_options and isinstance(raw_options[0], dict):
        return [item["label"] for item in raw_options]

    # Old structure → list of strings
    return raw_options

def load_vote_options(filename="pizzavision/options.json"):
    path = get_file_path(filename)
    with open(path, 'r') as json_file:
        data = json.load(json_file)
    return data['votes']


def load_options(path: str | Path = "pizzavision/options.json") -> List[str]:
    """Return the list of entry labels, no matter which JSON version is saved."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    raw_options = data.get("options", [])

    # New structure → list of dicts
    if raw_options and isinstance(raw_options[0], dict):
        return [item["label"] for item in raw_options]

    # Old structure → list of strings
    return raw_options

def load_vote_options():
    with open('pizzavision/options.json', 'r') as json_file:
        data = json.load(json_file)
    return data['votes']

# All other helper functions
ESC_POINTS = [12, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]   # top‑11 gets points

def canonical(text: str) -> str:
    """Lowercase, strip accents, collapse spaces. Use for label matching."""
    # Unicode → decomposed form, drop combining marks
    no_accents = ''.join(
        ch for ch in unicodedata.normalize('NFD', text)
        if unicodedata.category(ch) != 'Mn'
    )
    return re.sub(r'\s+', ' ', no_accents).strip().lower()

def country_key(label: str) -> str:
    """Return 'iceland', 'france', etc. Works on full 'Country: Song' labels."""
    return canonical(label.split(':', 1)[0])

def uniq_sorted(names):
    """Deduplicate and sort user names, keeping original spelling of first hit."""
    seen = {}
    for name in names:
        key = canonical(name)
        if key not in seen:
            seen[key] = name.strip()
    return sorted(seen.values(), key=lambda n: canonical(n))

def find_all_tied_winners(scores, highest=True):
    if not scores:
        return []
    best = max(scores.values()) if highest else min(scores.values())
    if best == 0:
        return []          # nobody scored in this category
    return [u for u, s in scores.items() if s == best]

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
    all_candidates = set([cand for sublist in votes for cand in sublist])
    for candidate in all_candidates:
        if candidate not in candidate_points:
            candidate_points[candidate] = 0

    # Return a sorted list of tuples by points in descending order
    return sorted(candidate_points.items(), key=lambda item: item[1], reverse=True)

def calculate_awards(db, options_data):
    users_raw = db.all()
    songs_raw = options_data['options']

    # build a lookup that survives accented differences
    songs_by_canon = {canonical(s['label']): s for s in songs_raw}

    user_points = {}
    for user in users_raw:
        uname = user['user']
        ranked_labels = user['rank']

        # initialise counters
        up = {
            'genres': defaultdict(int),
            'leads': defaultdict(int),
            'languages': defaultdict(int),
            'former_soviet': 0,
            'big5': 0,
            'iceland': 0,
            'drinks': defaultdict(int)
        }

        # assign ESC points to the user's top entries
        for idx, lbl in enumerate(ranked_labels[:len(ESC_POINTS)]):
            pts = ESC_POINTS[idx]
            song = songs_by_canon.get(canonical(lbl))
            if not song:
                continue  # label typo that still slipped through
            up['genres'][song['genre']] += pts
            up['leads'][song['lead']] += pts
            up['languages'][song['language']] += pts
            if song['former_soviet']:
                up['former_soviet'] += pts
            if song['big5']:
                up['big5'] += pts
            if country_key(lbl) == 'iceland':
                up['iceland'] += pts
            up['drinks'][song['drink']] += pts

        user_points[uname] = up

    # -------------------------------------------------
    # award helpers
    # -------------------------------------------------
    awards = []
    users = list(user_points.keys())

    def calculate_insight(award_code, winner_names, scores):
        # Special handling for Twinzies award
        if award_code == "Twinzies":
            # Handle multiple tied pairs
            if len(winner_names) > 1:
                return f"These pairs tied with identical match scores of {scores[winner_names[0]]}."
            
            # Handle a single winning pair
            winner = winner_names[0]
            pair = winner.split(" & ")
            if len(pair) == 2:
                user1, user2 = pair
                # Find user data
                user1_data = next((u for u in users_raw if u['user'] == user1), None)
                user2_data = next((u for u in users_raw if u['user'] == user2), None)
                
                if not user1_data or not user2_data:
                    return f"{user1} and {user2} had remarkably similar voting patterns."
                    
                # Focus only on point-scoring entries (top 11)
                rank1 = user1_data['rank'][:len(ESC_POINTS)]
                rank2 = user2_data['rank'][:len(ESC_POINTS)]
                
                # Calculate perfect position matches (same song in same exact position)
                perfect_matches = sum(1 for i in range(min(len(rank1), len(rank2))) if rank1[i] == rank2[i])
                
                # Find songs they both gave points to
                common_songs = set(rank1) & set(rank2)
                
                # Calculate how many songs they gave the same number of points to
                same_points_count = 0
                for song in common_songs:
                    pos1 = rank1.index(song)
                    pos2 = rank2.index(song)
                    if pos1 == pos2:
                        same_points_count += 1
                        
                # Calculate average point difference for common songs
                common_point_diff = 0
                if common_songs:
                    for song in common_songs:
                        pos1 = rank1.index(song)
                        pos2 = rank2.index(song)
                        points1 = ESC_POINTS[pos1]
                        points2 = ESC_POINTS[pos2]
                        common_point_diff += abs(points1 - points2)
                    avg_point_diff = common_point_diff / len(common_songs)
                    
                    return f"{user1} and {user2} gave points to {len(common_songs)} of the same songs. They gave identical points to {same_points_count} songs, and their average point difference was only {avg_point_diff:.1f} points!"
                
                return f"{user1} and {user2} had {perfect_matches} identical rankings in their point-scoring entries."
            
            return f"This pair agreed on their point-scoring entries more than any other voters with a score of {scores[winner]}."
        # Handle multiple winners for ties
        if len(winner_names) > 1:
            # Create a combined insight for ties
            winners_str = ", ".join(winner_names[:-1]) + " and " + winner_names[-1]
            
            if award_code == "Pop Diva":
                pop_songs = [s['label'] for s in songs_raw if s['genre'] == "pop"]
                avg_scores = sum(scores[winner] for winner in winner_names) / len(winner_names)
                return f"{winners_str} tied with {avg_scores:.1f} points each for pop songs. They're our Eurovision pop committee!"
                
            elif award_code == "Rockstar":
                return f"{winners_str} tied with equal rock appreciation. Rock on!"
                
            elif award_code == "Folk Hero":
                avg_points = sum(scores[winner] for winner in winner_names) / len(winner_names)
                return f"{winners_str} each gave an average of {avg_points:.1f} points to folk songs - traditional tastes unite!"
                
            elif award_code == "Mr. Roboto":
                return f"{winners_str} shared a love for electronic beats with {scores[winner_names[0]]} points each."
                
            elif award_code == "Crooner":
                return f"{winners_str} all fell for the emotional ballads, with identical point totals."
                
            elif award_code == "Big 5":
                total_points = sum(ESC_POINTS[:11])
                avg_percent = (scores[winner_names[0]]/total_points*100)
                return f"{winners_str} each gave {avg_percent:.1f}% of their points to Big 5 countries."
                

            elif award_code == "Call me Dadoi":
                iceland_points = scores[winner_names[0]]  # All tied winners have the same score
                avg_iceland = sum(user_points[u]['iceland'] for u in users) / len(users)
                diff = iceland_points - avg_iceland
                return f"{winners_str} each gave {diff:.1f} more points than the group average to Iceland."
                
            elif award_code == "Red George":
                return f"{winners_str} all showed equal love for former Soviet entries, with {scores[winner_names[0]]} points each."
                
            elif award_code == "For the Girls":
                female_percent = (scores[winner_names[0]] / sum(ESC_POINTS[:11])) * 100
                return f"{winners_str} all gave {female_percent:.1f}% of their points to female-led performances."
                
            elif award_code == "Polyglot":
                return f"{winners_str} equally appreciated native language songs with {scores[winner_names[0]]} points each."
                
            elif award_code == "Tastemaker":
                return f"{winners_str} had equally popular taste among the group - they're all trendsetters!"
                
            elif award_code == "Contrarian":
                return f"{winners_str} were equally unique in their picks - our tied contrarians!"
                
            elif award_code == "Twinzies":
                # This one is naturally a pair already
                pair = winner_names[0].split(" & ")
                if len(pair) == 2:
                    return f"{pair[0]} and {pair[1]} had identical scores on {scores[winner_names[0]]} matching picks."
                return f"These pairs had identical match scores of {scores[winner_names[0]]}."
                
            elif award_code in ["A Bottle Of Red", "A Bottle Of White", "A Bottle Of Beer"]:
                drink_type = award_code.replace("A Bottle Of ", "").lower()
                return f"{winners_str} tied in their appreciation for songs that pair with {drink_type}, with {scores[winner_names[0]]} points each."
                
            return f"{winners_str} tied for this award with {scores[winner_names[0]]} points each."
        
        # Single winner case - use existing logic
        winner = winner_names[0]  # Use first winner for calculations
        winner_user_data = next((u for u in users_raw if u['user'] == winner), None)
        
        if not winner_user_data:
            return "No data available for insights."
            
        winner_ranks = winner_user_data['rank']
        
        # Get all user rankings
        all_user_ranks = {u['user']: u['rank'] for u in users_raw}
        
        # Helper to get all genre songs
        def get_genre_songs(genre):
            return [s['label'] for s in songs_raw if s['genre'] == genre]
            
        # Calculate insights based on award type
        if award_code == "Pop Diva":
            pop_songs = get_genre_songs("pop")
            pop_count = sum(1 for song in pop_songs if song in winner_ranks[:10])
            avg_pop_count = sum(sum(1 for song in pop_songs if song in u['rank'][:10]) for u in users_raw) / len(users_raw)
            return f"{winner} placed {pop_count} pop songs in their top 10, compared to the group average of {avg_pop_count:.1f}."
            
        elif award_code == "Rockstar":
            # Find their highest ranked rock song
            rock_songs = get_genre_songs("rock")
            winner_top_rock = next((song for song in winner_ranks if song in rock_songs), None)
            if winner_top_rock:
                winner_pos = winner_ranks.index(winner_top_rock)
                avg_pos = sum(u['rank'].index(winner_top_rock) if winner_top_rock in u['rank'] else len(u['rank']) for u in users_raw) / len(users_raw)
                return f"{winner} ranked '{winner_top_rock.split(':', 1)[1].strip()}' at position {winner_pos+1}, while the average was {avg_pos:.1f}."
            return f"{winner} has a special appreciation for rock music."
                
        elif award_code == "Folk Hero":
            folk_points = scores[winner]
            total_possible = sum(ESC_POINTS[:len(get_genre_songs("folk"))])
            return f"{winner} gave {round((folk_points/total_possible)*100) }% of their points to folk songs."
            
        elif award_code == "Mr. Roboto":
            electronic_songs = get_genre_songs("electronic")
            top_electronic = [s for s in winner_ranks[:5] if s in electronic_songs]
            return f"{winner} placed {len(top_electronic)} electronic songs in their top 5."
            
        elif award_code == "Crooner":
            ballad_songs = get_genre_songs("ballad")
            total_ballads = len(ballad_songs)
            winner_ballads = sum(1 for s in winner_ranks if s in ballad_songs)
            return f"{winner} gave points to {winner_ballads} ballads!"
            
        elif award_code == "Big 5":
            big5_points = scores[winner]
            total_points = sum(ESC_POINTS[:11])
            return f"{winner} gave {big5_points} points to Big 5 countries, which is {(big5_points/total_points*100):.1f}% of their available points."

        # For single winner case
        elif award_code == "Call me Dadoi":
            winner_iceland_points = scores[winner]
            avg_iceland = sum(user_points[u]['iceland'] for u in users) / len(users)
            diff = winner_iceland_points - avg_iceland
            return f"{winner} gave {diff:.1f} more than points the group average to Iceland."
            
        elif award_code == "Red George":
            soviet_songs = [s['label'] for s in songs_raw if s.get('former_soviet')]
            favorite = next((s for s in winner_ranks if s in soviet_songs), None)
            if favorite:
                return f"{winner}'s favorite former Soviet entry was '{favorite.split(':', 1)[1].strip()}'."
            return f"{winner} gave former Soviet countries {scores[winner]} points in total."
            
        elif award_code == "For the Girls":
            female_percent = (scores[winner] / sum(ESC_POINTS[:11])) * 100
            return f"{winner} gave {female_percent:.1f}% of their points to songs with female leads."
            
        elif award_code == "Polyglot":
            native_songs = [s['label'] for s in songs_raw if s.get('language') == 'native']
            native_in_top = sum(1 for s in winner_ranks[:7] if s in native_songs)
            return f"{winner} placed {native_in_top} native language songs in their top 7."
            
        elif award_code == "Tastemaker":
            # Find a song that appeared most commonly in other users' top ranks
            winner_top_song = winner_ranks[0]
            others_with_same = sum(1 for u in users_raw if u['user'] != winner and winner_top_song in u['rank'][:5])
            return f"{winner}'s #1 pick appeared in {others_with_same} other voters' top 5."
            
        elif award_code == "Contrarian":
            unique_picks = 0
            for song in winner_ranks[:10]:
                if not any(song in u['rank'][:10] for u in users_raw if u['user'] != winner):
                    unique_picks += 1
            return f"{winner} had {unique_picks} songs in their top 10 that didn't appear in anyone else's top 10."
            
        elif award_code == "Twinzies":
            # For pairs
            pair = winner_names[0].split(" & ")
            if len(pair) == 2:
                user1, user2 = pair
                rank1 = next((u['rank'] for u in users_raw if u['user'] == user1), [])
                rank2 = next((u['rank'] for u in users_raw if u['user'] == user2), [])
                identical_count = sum(1 for i in range(min(len(rank1), len(rank2))) if rank1[i] == rank2[i])
                return f"{user1} and {user2} had {identical_count} identical rankings in the same positions."
            return f"This pair agreed on their rankings more than any other voters."
            
        elif award_code == "A Bottle Of Red":
            red_wine_songs = [s['label'] for s in songs_raw if s.get('drink') == 'red wine']
            fav_red = next((s for s in winner_ranks if s in red_wine_songs), None)
            if fav_red:
                return f"{winner}'s favorite red wine song was '{fav_red.split(':', 1)[1].strip()}'."
            return f"{winner} gave the most points to songs that pair well with red wine."
            
        elif award_code == "A Bottle Of White":
            white_wine_songs = [s['label'] for s in songs_raw if s.get('drink') == 'white wine']
            white_count = len([s for s in winner_ranks[:10] if s in white_wine_songs])
            return f"{winner} had {white_count} white wine songs in their top 10."
            
        elif award_code == "A Bottle Of Beer":
            beer_pts = scores[winner]
            return f"{winner} gave {beer_pts} points to songs paired with beer, making them the ultimate Eurovision drinking buddy."
        
        elif award_code == "Twinzies":
            # Handle the pair that's already in "User1 & User2" format
            pair = winner.split(" & ")
            if len(pair) == 2:
                user1, user2 = pair
                rank1 = next((u['rank'] for u in users_raw if u['user'] == user1), [])
                rank2 = next((u['rank'] for u in users_raw if u['user'] == user2), [])
                
                # Calculate how many songs they both ranked
                common_songs = set(rank1) & set(rank2)
                
                # Calculate perfect position matches (same song in same position)
                perfect_matches = sum(1 for i in range(min(len(rank1), len(rank2))) 
                                    if i < len(rank1) and i < len(rank2) and rank1[i] == rank2[i])
                
                # Calculate close matches (ranked within 3 positions of each other)
                close_matches = 0
                for song in common_songs:
                    pos1 = rank1.index(song)
                    pos2 = rank2.index(song)
                    if abs(pos1 - pos2) <= 3:
                        close_matches += 1
                
                # Calculate average position difference for common songs
                if common_songs:
                    avg_diff = sum(abs(rank1.index(song) - rank2.index(song)) for song in common_songs) / len(common_songs)
                    return f"{user1} and {user2} had {perfect_matches} identical rankings and {close_matches} songs ranked within 3 positions of each other. Their average ranking difference was only {avg_diff:.1f} positions!"
                return f"{user1} and {user2} had {perfect_matches} identical rankings in the same positions."
            return f"This pair agreed on their rankings more than any other voters with a matching score of {scores[winner]}."
            
        return f"{winner} earned this award with {scores[winner]} points."

    def push_award(code_name, pretty, scores_dict):
        winners = find_all_tied_winners(scores_dict)
        if winners:
            insight = calculate_insight(code_name, winners, scores_dict)
            awards.append({
                "award": pretty,
                "winner": " & ".join(uniq_sorted(winners)),
                "insight": insight,  # Add the insight string
                **options_data.get('award_details', {}).get(code_name, {})
            })

    # genre awards
    genre_map = {
        "pop":  "🎤 Pop Diva 🎤",
        "rock": "🎸 Rockstar 🎸",
        "folk": "🪕 Folk Hero 🪕",
        "electronic": "🤖 Mr. Roboto 🤖",
        "ballad": "🎙️ Crooner 🎙️"
    }
    for g, pretty in genre_map.items():
        push_award(
            code_name={
                "pop": "Pop Diva", "rock": "Rockstar", "folk": "Folk Hero",
                "electronic": "Mr. Roboto", "ballad": "Crooner"
            }[g],
            pretty=pretty,
            scores_dict={u: pts['genres'][g] for u, pts in user_points.items()}
        )

    # similarity matrix for Tastemaker, Contrarian and Twinzies
    sim_total = defaultdict(int)
    pair_sim = {}
    for i, u1 in enumerate(users):
        r1 = users_raw[i]['rank']
        for j in range(i + 1, len(users)):
            u2 = users[j]
            r2 = users_raw[j]['rank']
            score = sum(
                max(10 - abs(r1.index(lbl) - r2.index(lbl)), 0)
                for lbl in set(r1) & set(r2)
            )
            key = f"{u1} & {u2}" if u1 < u2 else f"{u2} & {u1}"
            pair_sim[key] = score
            sim_total[u1] += score
            sim_total[u2] += score

    push_award("Tastemaker", "👑 Tastemaker 👑", sim_total)
    push_award("Contrarian", "🙃 Contrarian 🙃", sim_total if not sim_total else
               {u: -s for u, s in sim_total.items()})  # invert for lowest

    # Big 5
    push_award("Big 5", "5️⃣ Big 5 5️⃣", {u: p['big5'] for u, p in user_points.items()})

    # female leads
    push_award("For the Girls", "👩 For the Girls 👩",
               {u: p['leads']['F'] for u, p in user_points.items()})

    # polyglot
    push_award("Polyglot", "🌍 Polyglot 🌍",
               {u: p['languages']['native'] for u, p in user_points.items()})

    # Iceland
    push_award("Call me Dadoi", "🕺 Call me Dadoi 🕺",
               {u: p['iceland'] for u, p in user_points.items()})

    # former Soviet
    push_award("Red George", "🚩 Red George 🚩",
               {u: p['former_soviet'] for u, p in user_points.items()})

    # drinks
    for drink, pretty, code in [
        ("red wine",  "🍷 A Bottle Of Red 🍷",  "A Bottle Of Red"),
        ("white wine","🥂 A Bottle Of White 🥂","A Bottle Of White"),
        ("beer",      "🍺 A Bottle Of Beer 🍺","A Bottle Of Beer")
    ]:
        push_award(code, pretty,
                   {u: p['drinks'][drink] for u, p in user_points.items()})

    # twinzies (best pair)
    push_award("Twinzies", "👯 Twinzies 👯", pair_sim)

    return awards