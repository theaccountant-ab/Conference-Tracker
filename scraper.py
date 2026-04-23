import os
import json
import time
import gspread
import trafilatura
import google.generativeai as genai
from google.oauth2.service_account import Credentials
from duckduckgo_search import DDGS

# 1. Setup
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GOOGLE_CREDS = json.loads(os.environ["GOOGLE_CREDENTIALS"])
SHEET_ID = os.environ["GOOGLE_SHEET_ID"]

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

scope = ['https://www.googleapis.com/auth/spreadsheets']
creds = Credentials.from_service_account_info(GOOGLE_CREDS, scopes=scope)
gc = gspread.authorize(creds)
sheet = gc.open_by_key(SHEET_ID).sheet1

def find_latest_url(conference_name):
    """Searches the web for the best URL for the conference name."""
    try:
        query = f"{conference_name} official conference website 2026"
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=3))
            if results:
                # Returns the first URL found
                return results[0]['href']
    except Exception as e:
        print(f"Search failed for {conference_name}: {e}")
    return None

def get_conference_info(url):
    """Scrapes the URL and uses AI to extract details."""
    try:
        downloaded = trafilatura.fetch_url(url)
        content = trafilatura.extract(downloaded)
        if not content: return ["Error: Unreadable"] + ([""] * 5)

        prompt = f"Extract from this text: Name, Location, Status (Submission/Participation Only/Ended), Deadline (YYYY-MM-DD), Start Date (YYYY-MM-DD), End Date (YYYY-MM-DD). Return JSON only.\n\nText: {content[:4000]}"
        
        response = model.generate_content(prompt)
        clean_json = response.text.replace('```json', '').replace('```', '').strip()
        data = json.loads(clean_json)

        return [
            data.get('Name', 'N/A'),
            data.get('Location', 'N/A'),
            data.get('Status', 'N/A'),
            data.get('Deadline', 'N/A'),
            data.get('Start Date', 'N/A'),
            data.get('End Date', 'N/A')
        ]
    except Exception as e:
        return [f"Error: {str(e)}"] + ([""] * 5)

# 2. Main Loop
# Now reading Names from Column A
conference_names = sheet.col_values(1)[1:] 

for i, name in enumerate(conference_names):
    if not name: continue
    row_idx = i + 2
    
    # Step A: Find the URL
    print(f"Searching for: {name}")
    url = find_latest_url(name)
    
    if url:
        # Step B: Scrape the found URL
        print(f"Found URL: {url}. Scraping...")
        info = get_conference_info(url)
        
        # Step C: Update Sheet (Col B = URL, Col C-H = Info)
        sheet.update_acell(f'B{row_idx}', url)
        sheet.update(range_name=f'C{row_idx}:H{row_idx}', values=[info])
    else:
        sheet.update_acell(f'B{row_idx}', "URL NOT FOUND")

    # Rate limiting for free tiers
    time.sleep(10)

print("Batch Update Complete!")

