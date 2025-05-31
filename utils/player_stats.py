"""
This module provides functions to fetch and parse player statistics
and leaderboards from rank.tornadosw.eu for a CS 1.6 server.
"""
import urllib

import requests
from bs4 import BeautifulSoup
import pandas as pd

def search_player(player_search_query):
    """
    Searches for players on rank.tornadosw.eu based on a query.

    Args:
        player_search_query (str): The name or part of the name of the player to search for.

    Returns:
        dict: A dictionary mapping player IDs (str) to player names (str)
              found matching the search query. Returns an empty dictionary if no
              players are found or if an error occurs.
    """
    initial_url = "http://rank.tornadosw.eu/top15.php?"
    params = {
        "lang": "en",
        "player": "",
        "me": "",
        "top": "15",
        "style": "1",
        "order": "13",
        "default_order": "13",
        "weapon": "0",
        "show": "0",
        "default_weapon": "0",
        "page": "1",
        "ip_port": "151.80.47.182:27015",
        "type": "0",
        "search": player_search_query,
        "zp": "0",
        "skills": "L=60.00|L%20=75.00|M-=85.00|M=100.00|M%20=115.00|H-=130.00|H=140.00|H%20=150.00|P-=165.00|P=180.00|P%20=195.00|G=210.00"
    }
    response = requests.get(initial_url, params=params)
    steam_player_dict = {}

    if response.status_code == 200:
        soup = BeautifulSoup(response.text, 'html.parser')
        a_tags = soup.find_all('a', href=True)
        for tag in a_tags:
            href = tag['href']
            parsed_url = urllib.parse.urlparse(href)
            query_params = urllib.parse.parse_qs(parsed_url.query)
            player_id = query_params.get('player', [None])[0]
            player_name = tag.get_text(strip=True)

            if player_id:
                steam_player_dict[player_id] = player_name
    return steam_player_dict

def find_player_info(player_id):
    """
    Fetches detailed statistics for a specific player ID from rank.tornadosw.eu.

    Args:
        player_id (str): The unique ID of the player.

    Returns:
        dict: A dictionary containing various player statistics.
              Keys include 'Name', 'Rank', 'K/D Ratio', 'Headshots', 'Played Time',
              'Top Weapons', etc. Returns an empty dictionary if the player is not
              found or if an error occurs.
    """
    initial_url = "http://rank.tornadosw.eu/user.php"
    params = {
        "lang": "en",
        "player": player_id,
        "me": "",
        "top": "15",
        "style": "1",
        "order": "13",
        "default_order": "13",
        "weapon": "0",
        "show": "0",
        "default_weapon": "0",
        "page": "1",
        "ip_port": "151.80.47.182:27015",
        "type": "0",
        "search": "",
        "zp": "0",
        "skills": "L=60.00|L%20=75.00|M-=85.00|M=100.00|M%20=115.00|H-=130.00|H=140.00|H%20=150.00|P-=165.00|P=180.00|P%20=195.00|G=210.00"
    }
    response = requests.get(initial_url, params=params)
    player_info = {}
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, 'html.parser')
        player_info['Region'] = soup.find('div', id='u').text.strip()
        if soup.find('div', id='f0'):
            player_info['Name'] = soup.find('div', id='f0').text.strip()
        else:
            player_info['Name'] = soup.find('div', id='f1').text.strip()
        player_info['Rank'] = soup.find('p', id='i').text.strip()
        player_info['Rank Placement'] = soup.find('div', id='t').text.strip()
        player_info['Most Valuable Player'] = soup.find(id='mvp').find('a').text
        player_info['Rounds Won'] = soup.find(id='rwn').find('a').text
        player_info['C4 Planted'] = soup.find(id='bp').find('a').text
        player_info['C4 Exploded'] = soup.find(id='bc').find('a').text
        player_info['C4 Defused'] = soup.find(id='di').find('a').text

        player_info['Kills'] = soup.find(id='kills').find('a').text
        player_info['Deaths'] = soup.find(id='deaths').find('a').text
        player_info['Assists'] = soup.find(id='assists').find('a').text
        player_info['Headshots'] = soup.find(id='headshots').find('a').text
        player_info['K/D Ratio'] = soup.find(id='kdratio').find('a').text

        player_info['Shots'] = soup.find(id='shots').find('a').text
        player_info['Hits'] = soup.find(id='hits').find('a').text
        player_info['Damage'] = soup.find(id='damage').find('a').text
        player_info['Accuracy'] = soup.find(id='accuracy').find('a').text

        player_info['First Login'] = soup.find(id='firstlogin').find('a').text
        player_info['Last Login'] = soup.find(id='lastlogin').find('a').text
        player_info['Played Time'] = soup.find(id='playedtime').find('a').text

        # Extract top weapons
        top_weapons = []
        for weapon_div in soup.find_all('div', id='m'):
            weapon_name = weapon_div.find('p').text.strip()
            weapon_kills = weapon_div.find('div').text.strip()
            top_weapons.append({weapon_name: weapon_kills})
        player_info['Top Weapons'] = top_weapons
    return player_info

def get_player_info_dict(player_name):
    """
    Combines search_player and find_player_info to get stats for a player name.

    It first searches for players matching the given name. If an exact single match
    is found, it fetches detailed stats for that player. Otherwise, it returns
    the list of found players.

    Args:
        player_name (str): The name of the player to get statistics for.

    Returns:
        tuple: (player_data, mode)
            - player_data (dict):
                - If mode is 0 (single exact match): Contains detailed player statistics
                  from `find_player_info`.
                - If mode is 1 (no exact match, multiple matches, or no players found):
                  Contains the dictionary of players found by `search_player`
                  (mapping player_id to player_name). This can be an empty dict
                  if no players were found by the initial search.
            - mode (int):
                - 0 if a single player with an exact name match was found.
                - 1 if no exact match was found (could be no players, or multiple
                  players with different names, or multiple players with the same name
                  that is not an exact match to player_name).
    """
    players_dict = search_player(player_name)
    matching_players_dict = {}
    for steam_id, name in players_dict.items():
        if player_name == name:
            matching_players_dict[steam_id] = name

    if len(matching_players_dict) == 1:
        return find_player_info(list(matching_players_dict.keys())[0]), 0
    else:
        return players_dict, 1


def get_top_players(page="1"):
    """
    Fetches a specific page of the server's leaderboard from rank.tornadosw.eu.

    Args:
        page (str, optional): The page number of the leaderboard to fetch. Defaults to "1".

    Returns:
        pandas.DataFrame: A DataFrame containing the leaderboard data for the specified page.
                          Columns include: 'Rank', 'XP', 'Name', 'Kills', 'Headshots',
                          'Headshot Percentages', 'Skills'.
                          Returns an empty DataFrame if an error occurs or the page is empty.
    """
    url = "http://rank.tornadosw.eu/top15.php"
    params = {
        "lang": "en",
        "player": "",
        "style": "1",
        "order": "13",
        "default_order": "13",
        "default_weapon": "0",
        "ip_port": "151.80.47.182:27015",
        "type": "0",
        "weapon": "0",
        "search": "",
        "zp": "0",
        "skills": "L=60.00|L =75.00|M-=85.00|M=100.00|M =115.00|H-=130.00|H=140.00|H =150.00|P-=165.00|P=180.00|P =195.00|G=210.00",
        "page": page
    }
    # Fetch the webpage content
    response = requests.get(url, params)
    html_content = response.content

    # Parse the HTML content using BeautifulSoup
    soup = BeautifulSoup(html_content, 'html.parser')

    # Find the table containing player data
    table = soup.find('table')

    # Initialize lists to store player data
    ranks = []
    xps = []
    names = []
    kills = []
    headshots = []
    headshot_percentages = []
    skills = []

    # Iterate through each row in the table
    for row in table.find_all('tr')[1:]:  # Skip the header row
        columns = row.find_all('td')

        # Extract data from each column
        if row.find('td', id='p'):
            rank = row.find('td', id='p').text.strip()
        elif row.find('td', id='y'):
            rank = "3"
        elif row.find('td', id='w'):
            rank = "2"
        elif row.find('td', id='z'):
            rank = "1"
        xp = row.find('div', class_='number').text.strip()
        name = row.find('td', id='sp').text.strip()
        kill = columns[3].get_text(strip=True)
        headshots_and_percentage = row.find('td', id='hs').text.strip()
        headshot_percentage = row.find('td', id='hs').find('a').text.strip()
        headshot = headshots_and_percentage.replace(headshot_percentage, '').strip()
        skill = row.find('td', id='sk11').text.strip()
        skill_number = row.find('td', id='sk11').find('td', id='sk12').text.strip()
        skill_rank = skill.replace(skill_number, '').strip()
        skill = skill_rank + " " + skill_number
        # Append the data to the respective lists
        ranks.append(rank)
        xps.append(xp)
        names.append(name)
        kills.append(kill)
        headshots.append(headshot)
        headshot_percentages.append(headshot_percentage)
        skills.append(skill)

    # Create a DataFrame from the lists
    data = {
        'Rank': ranks,
        'XP': xps,
        'Name': names,
        'Kills': kills,
        'Headshots': headshots,
        'Headshot Percentages': headshot_percentages,
        'Skills': skills,
    }

    df = pd.DataFrame(data)
    return df
