import urllib

import requests
from bs4 import BeautifulSoup
import re

def search_player(player_search_query):
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
    players_dict = search_player(player_name)
    matching_players_dict = {}
    for steam_id, name in players_dict.items():
        if player_name == name:
            matching_players_dict[steam_id] = name

    if len(matching_players_dict) == 1:
        return find_player_info(list(players_dict.keys())[0]), 0
    else:
        return players_dict, 1
