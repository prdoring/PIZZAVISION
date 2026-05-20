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

def load_lock_state():
    with open('pizzavision/options.json', 'r') as json_file:
        data = json.load(json_file)
    return data['locked']

# All other helper functions
ESC_POINTS = [12, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]   # top‑11 gets points

def fmt_gdp(amount):
    amount = abs(amount)
    if amount >= 1e12:
        return f"${amount/1e12:.2f}T"
    if amount >= 1e9:
        return f"${amount/1e9:.1f}B"
    if amount >= 1e6:
        return f"${amount/1e6:.1f}M"
    return f"${amount:,.0f}"

def fmt_pop(amount):
    amount = abs(amount)
    if amount >= 1e9:
        return f"{amount/1e9:.2f}B people"
    if amount >= 1e6:
        return f"{amount/1e6:.1f}M people"
    return f"{amount:,.0f} people"

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
    # Initialize dictionaries to hold total points and point distributions
    candidate_points = {}
    point_distributions = {}
    
    # Process each vote
    for vote in votes:
        for idx, candidate in enumerate(vote):
            if idx < len(vo):  
                points = vo[idx]
                
                # Update total points
                if candidate in candidate_points:
                    candidate_points[candidate] += points
                else:
                    candidate_points[candidate] = points
                
                # Track individual point values for the distribution
                if candidate not in point_distributions:
                    point_distributions[candidate] = []
                point_distributions[candidate].append(points)

    # Ensure all possible candidates are included even if they have 0 points
    all_candidates = set([cand for sublist in votes for cand in sublist])
    for candidate in all_candidates:
        if candidate not in candidate_points:
            candidate_points[candidate] = 0
        if candidate not in point_distributions:
            point_distributions[candidate] = [0]

    # Get the sorted results
    sorted_results = sorted(candidate_points.items(), key=lambda item: item[1], reverse=True)
    
    # Sort each candidate's point distribution from highest to lowest
    for candidate in point_distributions:
        point_distributions[candidate].sort(reverse=True)
    
    # Return a tuple: (sorted results, point distributions)
    return (sorted_results, point_distributions)

def calculate_awards(vote_store, options_data):
    users_raw = vote_store.all()
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
            'drinks': defaultdict(int),
            'act_type': defaultdict(int),
            'selection': defaultdict(int),
            'returning': 0,
            'regions': defaultdict(int),
            'gdp_weighted': 0.0,
            'population_weighted': 0.0,
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
            up['act_type'][song.get('act_type', 'solo')] += pts
            up['selection'][song.get('selection_type', 'internal')] += pts
            if song.get('returning_artist'):
                up['returning'] += pts
            region = song.get('region')
            if region:
                up['regions'][region] += pts
            up['gdp_weighted'] += song.get('gdp', 0) * (pts / 12)
            up['population_weighted'] += song.get('population', 0) * (pts / 12)

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
                    return f"These two bands had remarkably similar voting patterns."
                    
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
                    
                    return f"These two bands gave points to {len(common_songs)} of the same songs. They gave identical points to {same_points_count} songs, and their average point difference was only {avg_point_diff:.1f} points!"
                
                return f"These two bands had {perfect_matches} identical rankings in their point-scoring entries."
            
            return f"This pair agreed on their point-scoring entries more than any other voters with a score of {scores[winner]}."
        # Handle multiple winners for ties
        if len(winner_names) > 1:
            # Create a combined insight for ties
            winners_str = "Multiple people"
            
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
                return f"{winners_str} fell for the emotional ballads, with identical point totals."
                
            elif award_code == "Big 5":
                total_points = sum(ESC_POINTS[:11])
                avg_percent = (scores[winner_names[0]]/total_points*100)
                return f"{winners_str} each gave {avg_percent:.1f}% of their points to the Big 4 (Spain sat 2026 out)."
                

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
                    return f"These two had identical scores on {scores[winner_names[0]]} matching picks."
                return f"These pairs had identical match scores of {scores[winner_names[0]]}."
                
            elif award_code in ["A Bottle Of Red", "A Bottle Of White", "A Bottle Of Beer"]:
                drink_type = award_code.replace("A Bottle Of ", "").lower()
                return f"{winners_str} tied in their appreciation for songs that pair with {drink_type}, with {scores[winner_names[0]]} points each."

            elif award_code == "Moneybags":
                return f"{winners_str} tied at {fmt_gdp(scores[winner_names[0]])} of GDP behind their picks."

            elif award_code == "Slummin' It":
                return f"{winners_str} tied for the most underdog-friendly picks, with only {fmt_gdp(scores[winner_names[0]])} of GDP behind them."

            elif award_code == "Extrovert":
                return f"{winners_str} tied at {fmt_pop(scores[winner_names[0]])} backing their picks."

            elif award_code == "Introvert":
                return f"{winners_str} tied for tiniest constituency — only {fmt_pop(scores[winner_names[0]])} behind their picks."

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
            return f"The winner of this award placed {pop_count} pop songs in their top 10, compared to the group average of {avg_pop_count:.1f}."
            
        elif award_code == "Rockstar":
            # Find their highest ranked rock song
            rock_songs = get_genre_songs("rock")
            winner_top_rock = next((song for song in winner_ranks if song in rock_songs), None)
            if winner_top_rock:
                winner_pos = winner_ranks.index(winner_top_rock)
                avg_pos = sum(u['rank'].index(winner_top_rock) if winner_top_rock in u['rank'] else len(u['rank']) for u in users_raw) / len(users_raw)
                return f"The winner of this award ranked '{winner_top_rock.split(':', 1)[1].strip()}' at position {winner_pos+1}, while the average was {avg_pos:.1f}."
            return f""
                
        elif award_code == "Folk Hero":
            folk_points = scores[winner]
            total_possible = sum(ESC_POINTS[:len(get_genre_songs("folk"))])
            return f"The winner of this award gave {round((folk_points/total_possible)*100) }% of their points to folk songs."
            
        elif award_code == "Mr. Roboto":
            electronic_songs = get_genre_songs("electronic")
            top_electronic = [s for s in winner_ranks[:5] if s in electronic_songs]
            return f"The winner of this award placed {len(top_electronic)} electronic songs in their top 5."
            
        elif award_code == "Crooner":
            ballad_songs = get_genre_songs("ballad")
            total_ballads = len(ballad_songs)
            winner_ballads = sum(1 for s in winner_ranks if s in ballad_songs)
            return f"The winner of this award gave points to {winner_ballads} ballads!"
            
        elif award_code == "Big 5":
            big5_points = scores[winner]
            total_points = sum(ESC_POINTS[:11])
            return f"The winner of this award gave {big5_points} points to the Big 4 — {(big5_points/total_points*100):.1f}% of their available points (Spain sat 2026 out, so the club's down a member)."

        # For single winner case
        elif award_code == "Call me Dadoi":
            winner_iceland_points = scores[winner]
            avg_iceland = sum(user_points[u]['iceland'] for u in users) / len(users)
            diff = winner_iceland_points - avg_iceland
            return f"The winner of this award gave {diff:.1f} more than points the group average to Iceland."
            
        elif award_code == "Red George":
            soviet_songs = [s['label'] for s in songs_raw if s.get('former_soviet')]
            favorite = next((s for s in winner_ranks if s in soviet_songs), None)
            if favorite:
                return f"The winner of this award's favorite former Soviet entry was '{favorite.split(':', 1)[1].strip()}'."
            return f""
            
        elif award_code == "For the Girls":
            female_percent = (scores[winner] / sum(ESC_POINTS[:11])) * 100
            return f"The winner of this award gave {female_percent:.1f}% of their points to songs with female leads."
            
        elif award_code == "Polyglot":
            native_songs = [s['label'] for s in songs_raw if s.get('language') == 'native']
            native_in_top = sum(1 for s in winner_ranks[:7] if s in native_songs)
            return f"The winner of this award placed {native_in_top} native language songs in their top 7."
            
        elif award_code == "Tastemaker":
            # Find a song that appeared most commonly in other users' top ranks
            winner_top_song = winner_ranks[0]
            others_with_same = sum(1 for u in users_raw if u['user'] != winner and winner_top_song in u['rank'][:5])
            return f"The winner of this award's #1 pick appeared in {others_with_same} other voters' top 5."
            
        elif award_code == "Contrarian":
            unique_picks = 0
            for song in winner_ranks[:10]:
                if not any(song in u['rank'][:10] for u in users_raw if u['user'] != winner):
                    unique_picks += 1
            return f"The winner of this award had {unique_picks} songs in their top 10 that didn't appear in anyone else's top 10."
            
        elif award_code == "Twinzies":
            # For pairs
            pair = winner_names[0].split(" & ")
            if len(pair) == 2:
                user1, user2 = pair
                rank1 = next((u['rank'] for u in users_raw if u['user'] == user1), [])
                rank2 = next((u['rank'] for u in users_raw if u['user'] == user2), [])
                identical_count = sum(1 for i in range(min(len(rank1), len(rank2))) if rank1[i] == rank2[i])
                return f"These two had {identical_count} identical rankings in the same positions."
            
        elif award_code == "A Bottle Of Red":
            red_wine_songs = [s['label'] for s in songs_raw if s.get('drink') == 'red wine']
            fav_red = next((s for s in winner_ranks if s in red_wine_songs), None)
            if fav_red:
                return f"The winner of this award's favorite red wine song was '{fav_red.split(':', 1)[1].strip()}'."
            
        elif award_code == "A Bottle Of White":
            white_wine_songs = [s['label'] for s in songs_raw if s.get('drink') == 'white wine']
            white_count = len([s for s in winner_ranks[:10] if s in white_wine_songs])
            return f"The winner of this award had {white_count} white wine songs in their top 10."
            
        elif award_code == "A Bottle Of Beer":
            beer_pts = scores[winner]
            return f"The winner of this award gave {beer_pts} points to songs paired with beer, making them the ultimate Eurovision drinking buddy."
        
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
                    return f"These two bands had {perfect_matches} identical rankings and {close_matches} songs ranked within 3 positions of each other. Their average ranking difference was only {avg_diff:.1f} positions!"
                return f"These tow bands had {perfect_matches} identical rankings in the same positions."
            return f"This pair agreed on their rankings more than any other voters with a matching score of {scores[winner]}."

        elif award_code == "Lone Wolf":
            return f"The winner of this award gave {scores[winner]} points to solo acts."

        elif award_code == "Squad Goals":
            return f"The winner of this award gave {scores[winner]} points to duos and full bands."

        elif award_code == "Voice of the People":
            return f"The winner of this award gave {scores[winner]} points to entries chosen by national-final televote."

        elif award_code == "Welcome Back":
            return f"The winner of this award gave {scores[winner]} points to Eurovision returnees."

        elif award_code == "Nordic Friend Zone":
            return f"The winner of this award gave {scores[winner]} points to Nordic entries."

        elif award_code == "Balkan Brotherhood":
            return f"The winner of this award gave {scores[winner]} points to Balkan entries."

        elif award_code == "Baltic Squad":
            return f"The winner of this award gave {scores[winner]} points to Baltic entries."

        elif award_code == "Mediterranean Mood":
            return f"The winner of this award gave {scores[winner]} points to Mediterranean entries."

        elif award_code == "Moneybags":
            return f"The winner of this award funneled {fmt_gdp(scores[winner])} of national GDP behind their top 11 picks."

        elif award_code == "Slummin' It":
            return f"The winner of this award rooted for the underdogs — only {fmt_gdp(scores[winner])} of GDP backed their picks."

        elif award_code == "Extrovert":
            return f"The winner of this award gave their points to {fmt_pop(scores[winner])}."

        elif award_code == "Introvert":
            return f"The winner of this award championed the small nations — only {fmt_pop(scores[winner])} stood behind their picks."

        return f"The winner of this award earned this award with {scores[winner]} points."

    def category_filter(award_code):
        """Return a (song, label) -> bool filter for category-based awards,
        or None for awards that aren't a simple per-song category match."""
        if award_code in {"Pop Diva", "Rockstar", "Folk Hero", "Mr. Roboto", "Crooner"}:
            g = {"Pop Diva": "pop", "Rockstar": "rock", "Folk Hero": "folk",
                 "Mr. Roboto": "electronic", "Crooner": "ballad"}[award_code]
            return lambda s, l: s.get('genre') == g
        if award_code == "Big 5":
            return lambda s, l: s.get('big5')
        if award_code == "For the Girls":
            return lambda s, l: s.get('lead') == 'F'
        if award_code == "Polyglot":
            return lambda s, l: s.get('language') == 'native'
        if award_code == "Call me Dadoi":
            return lambda s, l: country_key(l) == 'iceland'
        if award_code == "Red George":
            return lambda s, l: s.get('former_soviet')
        if award_code in {"A Bottle Of Red", "A Bottle Of White", "A Bottle Of Beer"}:
            d = {"A Bottle Of Red": "red wine", "A Bottle Of White": "white wine",
                 "A Bottle Of Beer": "beer"}[award_code]
            return lambda s, l: s.get('drink') == d
        if award_code == "Lone Wolf":
            return lambda s, l: s.get('act_type') == 'solo'
        if award_code == "Squad Goals":
            return lambda s, l: s.get('act_type') in ('duo', 'group')
        if award_code == "Voice of the People":
            return lambda s, l: s.get('selection_type') == 'national_final'
        if award_code == "Welcome Back":
            return lambda s, l: s.get('returning_artist')
        if award_code == "Nordic Friend Zone":
            return lambda s, l: s.get('region') == 'Nordic'
        return None

    def category_short_name(award_code):
        return {
            "Pop Diva": "pop", "Rockstar": "rock", "Folk Hero": "folk",
            "Mr. Roboto": "electronic", "Crooner": "ballad",
            "Big 5": "Big 4", "For the Girls": "female-led",
            "Polyglot": "non-English", "Call me Dadoi": "Iceland",
            "Red George": "former-Soviet",
            "A Bottle Of Red": "red-wine", "A Bottle Of White": "white-wine",
            "A Bottle Of Beer": "beer",
            "Lone Wolf": "solo-act", "Squad Goals": "group/duo",
            "Voice of the People": "national-final", "Welcome Back": "returnee",
            "Nordic Friend Zone": "Nordic",
        }.get(award_code, award_code)

    def calculate_stats(award_code, winner_names, scores_dict):
        """Return ordered stat lines for the winner slide:
          1. Summary (% captured + field size) for category awards
          2. Top supporting picks (existing per-award logic)
          3. Snub line for small-field category awards
          4. Runner-up + margin (numeric awards)"""
        if not winner_names:
            return []

        # Twinzies: winner is "User1 & User2". Special structure throughout.
        if award_code == "Twinzies":
            pair = winner_names[0].split(" & ")
            if len(pair) != 2:
                return []
            r1 = next((u['rank'] for u in users_raw if u['user'] == pair[0]), [])
            r2 = next((u['rank'] for u in users_raw if u['user'] == pair[1]), [])
            window = 12
            same = []
            for i in range(min(len(r1), len(r2), window)):
                if r1[i] == r2[i]:
                    same.append((i + 1, r1[i]))
            out = [f"{len(same)} of {window} picks identical in top {window}"]
            out.extend(f"Both ranked #{pos}: {lbl}" for pos, lbl in same[:3])
            # Runner-up pair from pair_sim
            winner_key = winner_names[0]
            others = [(k, s) for k, s in pair_sim.items()
                      if k != winner_key and s > 0]
            if others:
                others.sort(key=lambda x: x[1], reverse=True)
                ru_key, _ = others[0]
                ru_pair = ru_key.split(" & ")
                ru_same = 0
                if len(ru_pair) == 2:
                    ru_r1 = next((u['rank'] for u in users_raw if u['user'] == ru_pair[0]), [])
                    ru_r2 = next((u['rank'] for u in users_raw if u['user'] == ru_pair[1]), [])
                    ru_same = sum(1 for i in range(min(len(ru_r1), len(ru_r2), window))
                                  if ru_r1[i] == ru_r2[i])
                out.append(f"Runner-up pair: {ru_key} ({ru_same}/{window} identical)")
            return out

        winner = winner_names[0]
        winner_data = next((u for u in users_raw if u['user'] == winner), None)
        if not winner_data:
            return []
        winner_ranks = winner_data['rank']

        def top_picks(filter_fn, limit=3):
            picks = []
            for idx, lbl in enumerate(winner_ranks[:len(ESC_POINTS)]):
                song = songs_by_canon.get(canonical(lbl))
                if song and filter_fn(song, lbl):
                    picks.append((ESC_POINTS[idx], lbl))
                    if len(picks) >= limit:
                        break
            return picks

        out = []
        filt = category_filter(award_code)
        cat_size = sum(1 for s in songs_raw if filt(s, s['label'])) if filt else 0

        # 1. Summary — % captured + field size, for category awards
        if filt and cat_size:
            max_pts = sum(ESC_POINTS[:min(cat_size, len(ESC_POINTS))])
            winner_pts = scores_dict.get(winner, 0)
            if award_code in ("Slummin' It", "Introvert"):
                winner_pts = abs(winner_pts)
            if max_pts > 0:
                pct = round(winner_pts / max_pts * 100)
                label = category_short_name(award_code)
                out.append(f"Captured {pct}% of available {label} points ({cat_size} eligible)")

        # 2. Top supporting picks
        if filt:
            out.extend(f"{pts}pts → {lbl}" for pts, lbl in top_picks(filt))
        elif award_code in ("Moneybags", "Extrovert", "Slummin' It", "Introvert"):
            key = 'gdp' if award_code in ("Moneybags", "Slummin' It") else 'population'
            fmt_val = fmt_gdp if award_code in ("Moneybags", "Slummin' It") else fmt_pop
            contribs = []
            for idx, lbl in enumerate(winner_ranks[:len(ESC_POINTS)]):
                song = songs_by_canon.get(canonical(lbl))
                if song and song.get(key):
                    contribs.append((song[key] * (ESC_POINTS[idx] / 12), ESC_POINTS[idx], lbl))
            reverse = award_code in ("Moneybags", "Extrovert")
            contribs.sort(reverse=reverse)
            out.extend(f"{pts}pts → {lbl} ({fmt_val(c)})" for c, pts, lbl in contribs[:3])
        elif award_code == "Tastemaker":
            other_ranks = [u['rank'] for u in users_raw if u['user'] != winner]
            for idx, lbl in enumerate(winner_ranks[:3]):
                also = sum(1 for r in other_ranks if lbl in r[:5])
                out.append(f"{ESC_POINTS[idx]}pts → {lbl} (also top-5 for {also}/{len(other_ranks)} others)")
        elif award_code == "Contrarian":
            others_top10 = set()
            for u in users_raw:
                if u['user'] != winner:
                    others_top10.update(u['rank'][:10])
            unique = [(ESC_POINTS[idx], lbl) for idx, lbl in enumerate(winner_ranks[:len(ESC_POINTS)])
                      if lbl not in others_top10]
            out.extend(f"{pts}pts → {lbl} (in no one else's top 10)" for pts, lbl in unique[:3])

        # 3. Snub for small-field category awards (2-6 eligible entries)
        if filt and 2 <= cat_size <= 6:
            eligible = [s['label'] for s in songs_raw if filt(s, s['label'])]
            top11 = set(winner_ranks[:len(ESC_POINTS)])
            snubbed = [lbl for lbl in eligible if lbl not in top11]
            if snubbed:
                out.append(f"Snubbed: {snubbed[0]} (0pts)")

        # 4. Runner-up + margin
        if scores_dict and len(scores_dict) > 1:
            winner_score = scores_dict.get(winner, 0)
            others = [(u, s) for u, s in scores_dict.items()
                      if u not in winner_names and s != 0]
            if others:
                others.sort(key=lambda x: x[1], reverse=True)
                ru_name, ru_score = others[0]
                margin = winner_score - ru_score
                if margin > 0:
                    if award_code in ("Moneybags", "Slummin' It"):
                        out.append(f"Runner-up: {ru_name} (by {fmt_gdp(margin)})")
                    elif award_code in ("Extrovert", "Introvert"):
                        out.append(f"Runner-up: {ru_name} (by {fmt_pop(margin)})")
                    else:
                        out.append(f"Runner-up: {ru_name} (by {int(margin)}pts)")

        return out

    def push_award(code_name, pretty, scores_dict):
        winners = find_all_tied_winners(scores_dict)
        if winners:
            insight = calculate_insight(code_name, winners, scores_dict)
            stats = calculate_stats(code_name, winners, scores_dict)
            entry = {
                "code": code_name,
                "award": pretty,
                "winner": " & ".join(uniq_sorted(winners)),
                "insight": insight,
                "stats": stats,
                **options_data.get('award_details', {}).get(code_name, {})
            }
            # Big-display total for the economic awards (pulled from real
            # un-negated user_points, since scores_dict for Slummin'/Introvert
            # is sign-flipped to find the lowest).
            if code_name in ("Moneybags", "Slummin' It"):
                v = user_points[winners[0]]['gdp_weighted']
                entry["winner_total"] = fmt_gdp(v)
                entry["winner_total_value"] = v
                entry["winner_total_kind"] = "gdp"
            elif code_name in ("Extrovert", "Introvert"):
                v = user_points[winners[0]]['population_weighted']
                entry["winner_total"] = fmt_pop(v)
                entry["winner_total_value"] = v
                entry["winner_total_kind"] = "pop"
            awards.append(entry)

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

    # similarity matrix
    # Tastemaker / Contrarian use full ranking. Twinzies only compares the
    # top picks each voter actually invested effort in — junk at the tail
    # of a 25-song ballot shouldn't be the thing crowning the closest pair.
    TWINZIES_WINDOW = 12
    sim_total = defaultdict(int)
    pair_sim = {}
    for i, u1 in enumerate(users):
        r1_full = users_raw[i]['rank']
        r1_top = r1_full[:TWINZIES_WINDOW]
        for j in range(i + 1, len(users)):
            u2 = users[j]
            r2_full = users_raw[j]['rank']
            r2_top = r2_full[:TWINZIES_WINDOW]
            full_score = sum(
                max(10 - abs(r1_full.index(lbl) - r2_full.index(lbl)), 0)
                for lbl in set(r1_full) & set(r2_full)
            )
            sim_total[u1] += full_score
            sim_total[u2] += full_score
            top_score = sum(
                max(10 - abs(r1_top.index(lbl) - r2_top.index(lbl)), 0)
                for lbl in set(r1_top) & set(r2_top)
            )
            key = f"{u1} & {u2}" if u1 < u2 else f"{u2} & {u1}"
            pair_sim[key] = top_score

    push_award("Tastemaker", "👑 Tastemaker 👑", sim_total)
    push_award("Contrarian", "🙃 Contrarian 🙃", sim_total if not sim_total else
               {u: -s for u, s in sim_total.items()})  # invert for lowest

    # Big 5
    push_award("Big 5", "4️⃣ Big <s>5</s> 4 4️⃣", {u: p['big5'] for u, p in user_points.items()})

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

    # --- 2026 additions ---

    # solo vs group
    push_award("Lone Wolf", "🐺 Lone Wolf 🐺",
               {u: p['act_type']['solo'] for u, p in user_points.items()})
    push_award("Squad Goals", "👯‍♂️ Squad Goals 👯‍♂️",
               {u: p['act_type']['duo'] + p['act_type']['group']
                for u, p in user_points.items()})

    # selection method
    push_award("Voice of the People", "🗳️ Voice of the People 🗳️",
               {u: p['selection']['national_final'] for u, p in user_points.items()})

    # returning artist
    push_award("Welcome Back", "👋 Welcome Back 👋",
               {u: p['returning'] for u, p in user_points.items()})

    # bloc award (just Nordic — Balkan/Baltic/Med dropped as less fun)
    push_award("Nordic Friend Zone", "❄️ Nordic Friend Zone ❄️",
               {u: p['regions']['Nordic'] for u, p in user_points.items()})

    # GDP-weighted
    gdp_scores = {u: p['gdp_weighted'] for u, p in user_points.items()}
    push_award("Moneybags", "💰 Moneybags 💰", gdp_scores)
    push_award("Slummin' It", "🪙 Slummin' It 🪙",
               gdp_scores if not gdp_scores else
               {u: -s for u, s in gdp_scores.items()})

    # population-weighted
    pop_scores = {u: p['population_weighted'] for u, p in user_points.items()}
    push_award("Extrovert", "🗣️ Extrovert 🗣️", pop_scores)
    push_award("Introvert", "🤫 Introvert 🤫",
               pop_scores if not pop_scores else
               {u: -s for u, s in pop_scores.items()})

    # Cross-reveal contrast for symmetric economic award pairs.
    # Only attach to the SECOND award of each pair — the first hasn't been
    # revealed yet when the first one displays, so the reverse direction
    # would spoil the upcoming reveal.
    by_code = {a.get('code'): a for a in awards}
    for code_a, code_b in [("Moneybags", "Slummin' It"),
                           ("Extrovert", "Introvert")]:
        a, b = by_code.get(code_a), by_code.get(code_b)
        if a and b:
            b['stats'].append(f"Counterpoint — {code_a}: {a['winner']} ({a['winner_total']})")

    return awards