import os
import json
import time
import gspread
import trafilatura
import google.generativeai as genai
from google.oauth2.service_account import Credentials
from duckduckgo_search import DDGS

# 1. Setup API Keys and Sheet
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GOOGLE_CREDS = json.loads(os.environ["GOOGLE_CREDENTIALS"])
SHEET_ID = os.environ["GOOGLE_SHEET_ID"]

# Initialize Gemini (Stable version)
genai.configure(api_key=GEMINI_API_KEY)
# Using 1.5-flash: it is very fast, reliable, and has a great free tier
model = genai.GenerativeModel('gemini-1.5-flash')

# Initialize Google Sheets
scope = ['https://www.googleapis.com/auth/spreadsheets']
creds = Credentials.from_service_account_info(GOOGLE_CREDS, scopes=scope)
gc = gspread.authorize(creds)
sheet = gc.open_by_key(SHEET_ID).sheet1

def search_duckduckgo(query):
    """Searches DuckDuckGo for the conference website."""
    search_query = f"{query} conference official website 2026"
    try:
        # Latest DDGS syntax
        with DDGS() as ddgs:
            results = list(ddgs.text(search_query, max_results=3))
            if results:
                return results[0]['href']
    except Exception as e:
        print(f"DuckDuckGo search failed for {query}: {e}")
    return None

def get_conference_info(url):
    """Extracts data using Gemini."""
    try:
        downloaded = trafilatura.fetch_url(url)
        content = trafilatura.extract(downloaded)
        if not content: return ["Error: Unreadable"] + ([""] * 5)

        prompt = f"""
        Extract these conference details from the text:
        - Name
        - Location
        - Status (Submission, Participation Only, or Ended)
        - Deadline (YYYY-MM-DD)
        - Start Date (YYYY-MM-DD)
        - End Date (YYYY-MM-DD)

        Text: {content[:5000]}
        Return strictly JSON format.
        """
        
        response = model.generate_content(prompt)
        
        # Clean the response text
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
conference_names = sheet.col_values(1)[1:] 

for i, name in enumerate(conference_names):
    if not name: continue
    row_idx = i + 2
    print(f"Row {row_idx}: Processing {name}...")
    
    found_url = search_duckduckgo(name)
    
    if found_url:
        print(f"Found: {found_url}")
        info = get_conference_info(found_url)
        
        # Update Sheet: Col B=URL, Col C-H=Data
        sheet.update_acell(f'B{row_idx}', found_url)
        sheet.update(range_name=f'C{row_idx}:H{row_idx}', values=[info])
    else:
        sheet.update_acell(f'B{row_idx}', "Search found no link")

    # Wait 10 seconds to stay within Gemini's free tier limits (RPM)
    time.sleep(10)

print("Batch Update Complete!")
