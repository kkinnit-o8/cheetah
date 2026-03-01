import subprocess
import sys
import re
import requests
from bs4 import BeautifulSoup
import json
import time

# User-Agent to look like a browser
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
}

print("="*60)
print("INVESTIGATOR - Username OSINT Tool")
print("="*60)
print("\n1. Use Sherlock to find links (requires Sherlock installed)")
print("2. Use a txt file with links")
print()

choice = input("Choose option (1 or 2): ").strip()

if choice == '1':
    name = input("Enter username: ")
    
    result = subprocess.run(
        ["sherlock", name],          # your CMD command here
        capture_output=True,   # capture stdout and stderr
        text=True,             # decode bytes to string
        shell=True             # needed for many Windows commands
    )
    
    lines = result.stdout.splitlines()
    links = [re.search(r'https?://\S+', item).group() for item in lines if re.search(r'https?://\S+', item)]
    
elif choice == '2':
    txt_file = input("Enter path to txt file with links: ").strip()
    if not txt_file:
        print("Error: No file provided!")
        sys.exit(1)
    
    try:
        with open(txt_file, 'r') as f:
            lines = f.readlines()
        # Extract links from file (handles URLs directly or one per line)
        links = [line.strip() for line in lines if line.strip().startswith('http')]
        name = input("Enter username (for filename): ")
    except FileNotFoundError:
        print(f"Error: File '{txt_file}' not found!")
        sys.exit(1)
else:
    print("Invalid choice! Exiting...")
    sys.exit(1)

if not links:
    print("Error: No links found!")
    sys.exit(1)

print("\n" + "="*60)
print("Found the following links:")
print("="*60)
for link in links:
    print(f"  • {link}")

input("\nPress Enter to start scraping the links...")

# Function to clean up scraped data
def clean_data(data):
    """Remove None, empty, and useless entries"""
    cleaned = {}
    for key, value in data.items():
        if value is None:
            continue
        if isinstance(value, str) and value.strip() == '':
            continue
        if value == 'N/A':
            continue
        # Convert BeautifulSoup objects to strings
        if hasattr(value, 'get_text'):
            value = value.get_text(strip=True)
        if isinstance(value, str) and len(value) == 0:
            continue
        if value:  # Only add non-empty values
            cleaned[key] = value
    return cleaned

#now scrape all links to get all info possible about user:
links_data = {}
for link in links:
    print(f"\nScraping {link}...")
    try:
        # Fetch the page
        response = requests.get(link, timeout=10, headers=headers)
        response.raise_for_status()
        
        # Parse HTML
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Initialize base data
        page_data = {
            'url': link,
            'title': soup.title.string if soup.title else 'N/A',
        }
        
        # Chess.com
        if 'chess.com' in link:
            page_data['site'] = 'Chess.com'
            page_data['username'] = soup.find('h1', class_='username')
            page_data['rating'] = soup.find('span', class_='rating')
            page_data['title'] = soup.find('span', class_='title')
            page_data['country'] = soup.find('span', class_='country')
            page_data['followers'] = soup.find(text=re.compile('Followers'))
            page_data['member_since'] = soup.find(text=re.compile('Member since'))
            page_data['games_played'] = soup.find(text=re.compile('Games Played'))
            
        # GitHub
        elif 'github.com' in link:
            page_data['site'] = 'GitHub'
            page_data['username'] = soup.find('span', class_='p-nickname')
            page_data['name'] = soup.find('span', class_='p-name')
            page_data['bio'] = soup.find('div', class_='p-note')
            page_data['location'] = soup.find('span', class_='p-label')
            page_data['followers'] = soup.find('a', href=re.compile('followers'))
            page_data['following'] = soup.find('a', href=re.compile('following'))
            page_data['repos'] = soup.find(text=re.compile('repositories'))
            page_data['profile_pic'] = soup.find('img', class_='Avatar')
            
        # YouTube
        elif 'youtube.com' in link:
            page_data['site'] = 'YouTube'
            page_data['channel_name'] = soup.find('h1', class_='title')
            page_data['subscribers'] = soup.find(text=re.compile('subscribers'))
            page_data['views'] = soup.find(text=re.compile('views'))
            page_data['upload_count'] = soup.find(text=re.compile('upload'))
            page_data['description'] = soup.find('yt-formatted-string', class_='content')
            
        # DeviantArt
        elif 'deviantart.com' in link:
            page_data['site'] = 'DeviantArt'
            page_data['username'] = soup.find('h1', class_='user-title')
            page_data['followers'] = soup.find('a', href=re.compile('watchers'))
            page_data['bio'] = soup.find('div', class_='user-bio')
            page_data['gallery_count'] = soup.find(text=re.compile('Deviations'))
            page_data['status'] = soup.find('div', class_='status')
            
        # GitHub (alternative detection)
        elif 'github.com' in link and 'github' in link.lower():
            page_data['site'] = 'GitHub'
            page_data['username'] = soup.find('span', {'itemprop': 'name'})
            page_data['bio'] = soup.find('div', {'data-bio-text': True})
            page_data['followers'] = soup.find(text=re.compile('[0-9]+ followers'))
            
        # Scratch (MIT)
        elif 'scratch.mit.edu' in link:
            page_data['site'] = 'Scratch'
            page_data['username'] = soup.find('h1')
            page_data['followers'] = soup.find(text=re.compile('followers'))
            page_data['following'] = soup.find(text=re.compile('following'))
            page_data['projects'] = soup.find(text=re.compile('Shared Projects'))
            page_data['bio'] = soup.find('div', class_='bio')
            page_data['country'] = soup.find(text=re.compile('Country'))
            
        # Roblox
        elif 'roblox.com' in link:
            page_data['site'] = 'Roblox'
            page_data['username'] = soup.find('h1', class_='username')
            page_data['user_id'] = soup.find('span', class_='user-id')
            page_data['followers'] = soup.find(text=re.compile('followers'))
            page_data['friends'] = soup.find(text=re.compile('friends'))
            page_data['groups'] = soup.find(text=re.compile('groups'))
            
        # Sketchfab
        elif 'sketchfab.com' in link:
            page_data['site'] = 'Sketchfab'
            page_data['username'] = soup.find('h1', class_='user-name')
            page_data['followers'] = soup.find(text=re.compile('followers'))
            page_data['models'] = soup.find(text=re.compile('[0-9]+ models'))
            page_data['verified'] = soup.find('span', class_='verified')
            
        # TikTok
        elif 'tiktok.com' in link:
            page_data['site'] = 'TikTok'
            page_data['username'] = soup.find('h1', class_='username')
            page_data['followers'] = soup.find(text=re.compile('followers'))
            page_data['likes'] = soup.find(text=re.compile('likes'))
            page_data['video_count'] = soup.find(text=re.compile('videos'))
            page_data['bio'] = soup.find('h2', class_='bio')
            
        # Geocaching
        elif 'geocaching.com' in link:
            page_data['site'] = 'Geocaching'
            page_data['username'] = soup.find('h1', class_='profile-name')
            page_data['caches_found'] = soup.find(text=re.compile('Caches Found'))
            page_data['caches_hidden'] = soup.find(text=re.compile('Caches Hidden'))
            page_data['favorite_points'] = soup.find(text=re.compile('Favorite Points'))
            page_data['member_since'] = soup.find(text=re.compile('Member Since'))
            
        # Xbox Gamertag
        elif 'xboxgamertag.com' in link or 'xbox' in link:
            page_data['site'] = 'Xbox'
            page_data['gamertag'] = soup.find('h1', class_='gamertag')
            page_data['achievements'] = soup.find(text=re.compile('Achievements'))
            page_data['gamerscore'] = soup.find(text=re.compile('Gamerscore'))
            page_data['followers'] = soup.find(text=re.compile('followers'))
            
        # Wikipedia
        elif 'wikipedia.org' in link:
            page_data['site'] = 'Wikipedia'
            first_para = soup.find('p')
            if first_para:
                page_data['first_paragraph'] = first_para
            
        # Generic extraction for any site
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc:
            page_data['meta_description'] = meta_desc
        meta_author = soup.find('meta', attrs={'name': 'author'})
        if meta_author:
            page_data['meta_author'] = meta_author
        
        # Clean up the data before saving (removes None, empty, useless entries)
        page_data = clean_data(page_data)
        
        # Save to dictionary
        links_data[link] = page_data
        print(f"✓ Successfully scraped {link}")
        time.sleep(1)  # Be respectful to servers
        
    except Exception as e:
        print(f"✗ Error scraping {link}: {e}")
        links_data[link] = {'error': str(e), 'url': link}

# Save all data to JSON file
output_file = f'{name}_investigation.json'
with open(output_file, 'w') as f:
    json.dump(links_data, f, indent=2, default=str)
    
print(f"\n{'='*60}")
print(f"✓ Data saved to {output_file}")
print(f"✓ Total profiles scraped: {len(links)}")
print(f"✓ Total data collected: {len(links_data)}")
print(f"{'='*60}")
    