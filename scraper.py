import os
import json
import time
import requests
import gspread
import trafilatura
from google import genai
from google.genai import types
from google.oauth2.service_account import Credentials

# 1. Setup & Authentication
try:
    GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
    SERPER_API_KEY = os.environ["SERPER_API_KEY"]
    GOOGLE_CREDS = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
except KeyError as e:
    print(f"CRITICAL ERROR: Missing environment variable {e}")
    exit(1)

# Initialize Gemini Client
client = genai.Client(api_key=GEMINI_API_KEY)

# Google Sheets Auth
scope = ['https://www.googleapis.com/auth/spreadsheets']
creds = Credentials.from_service_account_info(GOOGLE_CREDS, scopes=scope)
gc = gspread.authorize(creds)
sheet = gc.open_by_key(SHEET_ID).sheet1

def find_official_url(conference_name):
    """Uses Serper.dev (Google Search API) to find the official conference site."""
    search_url = "https://google.serper.dev/search"
    # We target 2025/2026 and specific academic terms
    payload = json.dumps({
        "q": f'"{conference_name}" conference 2025 2026 official website "call for papers"',
        "num": 5
    })
    headers = {
        'X-API-KEY': SERPER_API_KEY,
        'Content-Type': 'application/json'
    }

    try:
        response = requests.post(search_url, headers=headers, data=payload)
        results = response.json().get('organic', [])
        
        if not results:
            return None

        # Build a list of snippets for Gemini to judge
        options = ""
        for r in results:
            options += f"Link: {r.get('link')}\nSnippet: {r.get('snippet')}\n\n"

        prompt = f"""
        Identify the OFFICIAL CONFERENCE WEBSITE for: "{conference_name}".
        Academic conferences usually live on university (.edu) or organization (.org) domains.
        
        Search Results:
        {options}
        
        Instructions:
        1. Return ONLY a JSON object with a single key "url".
        2. If no result is a specific match for this conference, return "NONE".
        """
        
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        
        data = json.loads(response.text)
        best_url = data.get("url", "NONE")
        
        return best_url if best_url.startswith("http") else None

    except Exception as e:
        print(f"Serper Search failed: {e}")
    return None

def get_conference_info(url):
    """Scrapes the page and extracts data using Gemini."""
    try:
        downloaded = trafilatura.fetch_url(url)
        content = trafilatura.extract(downloaded)
        
        if not content: 
            return ["Error: Page Content Unreadable", "", "", "", "", ""]

        prompt = f"""
        Extract these details from the text. Return ONLY JSON with these exact keys:
        "conference_name", "location", "status", "deadline", "start_date", "end_date".
        Dates must be YYYY-MM-DD. Status: "Submission", "Participation Only", or "Ended".

        Text: {content[:8000]}
        """
        
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        
        data = json.loads(response.text)
        return [
            data.get('conference_name', 'N/A'),
            data.get('location', 'N/A'),
            data.get('status', 'N/A'),
            data.get('deadline', 'N/A'),
            data.get('start_date', 'N/A'),
            data.get('end_date', 'N/A')
        ]
    except Exception as e:
        return [f"Error: {str(e)}", "", "", "", "", ""]

# 2. Execution Loop
print("Starting Scraper with Serper.dev...")
conference_names = sheet.col_values(1)[1:] 

for i, name in enumerate(conference_names):
    if not name or not name.strip(): continue
    
    row_idx = i + 2
    print(f"Row {row_idx}: Searching for {name}...")
    
    official_url = find_official_url(name)
    
    if official_url:
        print(f"  -> Found: {official_url}")
        info = get_conference_info(official_url)
        # Update B through H in one go
        sheet.update(values=[[official_url] + info], range_name=f'B{row_idx}:H{row_idx}')
    else:
        print("  -> Not found.")
        sheet.update_acell(f'B{row_idx}', "Official site not found")

    # Respect Google Sheets & Gemini rate limits
    time.sleep(10)

print("Process Complete!")
