import requests
from bs4 import BeautifulSoup

def find_player_page_soup(player_search_query):
    initial_url = "http://rank.tornadosw.eu/top15.php"
    params = {
        "lang": "en",
        "player": "",
        "style": "1",
        "order": "13",
        "default_order": "13",
        "default_weapon": "0",
        "weapon": "0",
        "page": "1",
        "ip_port": "151.80.47.182:27015",
        "type": "0",
        "search": player_search_query
    }

    response = requests.get(initial_url, params=params)

    if response.status_code == 200:
        soup = BeautifulSoup(response.text, 'html.parser')
        target_td = soup.find('td', id='sp')
        if target_td:
            target_a = target_td.find('a', class_='glow1')
            if target_a:
                href = target_a.get('href')
                new_url = href
                new_response = requests.get(new_url)
                if new_response.status_code == 200:
                    return BeautifulSoup(new_response.content, 'html.parser')
                else:
                    print("Failed to fetch the new page:", new_response.status_code)
                    return None
            else:
                print("Target <a> tag not found.")
                return None
        else:
            print("Target <td> tag not found.")
            return None
    else:
        print("Failed to fetch the initial page:", response.status_code)
        return None

def scrap_player_info(soup):
    player_info = {}

    # Extract player name and rank
    player_info['name'] = soup.find('div', id='f0').text.strip()
    player_info['rank'] = soup.find('div', id='t').text.strip()

    # Extract current XP and progress
    player_info['current_xp'] = soup.find('div', class_='number').text.strip()
    player_info['progress'] = soup.find('div', class_='progress')['style'].split(':')[1].strip()

    # Extract MVP, rounds won, C4 stats
    player_info['mvp'] = soup.find('p', id='mvp').find('a').text.strip()
    player_info['rounds_won'] = soup.find('p', id='rwn').find('a').text.strip()
    player_info['c4_planted'] = soup.find('p', id='bp').find('a').text.strip()
    player_info['c4_exploded'] = soup.find('p', id='bc').find('a').text.strip()
    player_info['c4_defused'] = soup.find('p', id='di').find('a').text.strip()

    # Extract statistics (kills, deaths, assists, etc.)
    player_info['kills'] = soup.find('p', id='kills').find('a').text.strip()
    player_info['deaths'] = soup.find('p', id='deaths').find('a').text.strip()
    player_info['assists'] = soup.find('p', id='assists').find('a').text.strip()
    player_info['headshots'] = soup.find('p', id='headshots').find('a').text.strip()
    player_info['kd_ratio'] = soup.find('p', id='kdratio').find('a').text.strip()
    player_info['shots'] = soup.find('p', id='shots').find('a').text.strip()
    player_info['hits'] = soup.find('p', id='hits').find('a').text.strip()
    player_info['damage'] = soup.find('p', id='damage').find('a').text.strip()
    player_info['accuracy'] = soup.find('p', id='accuracy').find('a').text.strip()

    # Extract login and played time
    player_info['first_login'] = soup.find('p', id='firstlogin').find('a').text.strip()
    player_info['last_login'] = soup.find('p', id='lastlogin').find('a').text.strip()
    player_info['played_time'] = soup.find('p', id='playedtime').find('a').text.strip()

    # Extract top weapons
    top_weapons = []
    for weapon_div in soup.find_all('div', id='m'):
        weapon_name = weapon_div.find('p').text.strip()
        weapon_kills = weapon_div.find('div').text.strip()
        top_weapons.append({weapon_name: weapon_kills})
    player_info['top_weapons'] = top_weapons

    return player_info

def get_player_info_dict(player_name):
    soup = find_player_page_soup(player_name)
    if soup:
        return scrap_player_info(soup)
    else:
        return {}