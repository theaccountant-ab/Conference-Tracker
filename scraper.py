import os
import json
import time
import gspread
import trafilatura
from google import genai
from google.genai import types
from google.oauth2.service_account import Credentials
from ddgs import DDGS

# 1. Setup & Authentication
try:
    GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
    GOOGLE_CREDS = json.loads(os.environ["GOOGLE_CREDENTIALS"])
    SHEET_ID = os.environ["GOOGLE_SHEET_ID"]
except KeyError as e:
    print(f"CRITICAL ERROR: Missing environment variable {e}")
    exit(1)

# Initialize the NEW Gemini Client
client = genai.Client(api_key=GEMINI_API_KEY)

# Google Sheets Auth
scope = ['https://www.googleapis.com/auth/spreadsheets']
creds = Credentials.from_service_account_info(GOOGLE_CREDS, scopes=scope)
gc = gspread.authorize(creds)
sheet = gc.open_by_key(SHEET_ID).sheet1

def find_official_url(conference_name):
    """Searches DuckDuckGo and uses Gemini to identify the correct URL."""
    search_query = f'"{conference_name}" conference university "call for papers"'
    junk_sites = ["trucks", "qq.com", "facebook", "linkedin", "youtube", "twitter", "instagram"]
    
    try:
        with DDGS() as ddgs:
            time.sleep(2) 
            results = list(ddgs.text(search_query, max_results=10))
            
            if not results:
                print("No search results found (Possible IP block by DuckDuckGo).")
                return None

            options = ""
            for i, r in enumerate(results):
                if any(junk in r['href'].lower() for junk in junk_sites):
                    continue
                options += f"Link: {r['href']}\nSnippet: {r['body']}\n\n"

            if not options:
                return None

            prompt = f"""
            Identify the OFFICIAL CONFERENCE WEBSITE for: "{conference_name}".
            Academic conferences usually live on .edu, .org, or university subdomains.
            
            Search Results:
            {options}
            
            Instructions:
            1. Return ONLY a JSON object with a single key "url".
            2. If no valid academic conference link is found, return "NONE" as the value.
            """
            
            # Using the new SDK syntax
            response = client.models.generate_content(
                model='gemini-1.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                )
            )
            
            data = json.loads(response.text)
            best_url = data.get("url", "NONE")
            
            if best_url.startswith("http") and "NONE" not in best_url:
                return best_url

    except Exception as e:
        print(f"Search failed for {conference_name}: {e}")
    
    return None

def get_conference_info(url):
    """Scrapes the URL and extracts standardized data using Gemini."""
    try:
        downloaded = trafilatura.fetch_url(url)
        content = trafilatura.extract(downloaded)
        
        if not content: 
            return ["Error: Page Content Unreadable", "", "", "", "", ""]

        prompt = f"""
        Extract the conference details from the following text.
        Return ONLY a JSON object using exactly these keys:
        "conference_name", "location", "status", "deadline", "start_date", "end_date".
        
        If a piece of information is missing, use "N/A". Format dates as YYYY-MM-DD.
        Status should be one of: "Submission", "Participation Only", or "Ended".

        Text: {content[:8000]}
        """
        
        # Using the new SDK syntax
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            )
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
        
    except json.JSONDecodeError:
        return ["Error: Failed to parse AI response", "", "", "", "", ""]
    except Exception as e:
        return [f"Error: {str(e)}", "", "", "", "", ""]

# 2. Execution Loop
print("Starting Conference Scraper...")
conference_names = sheet.col_values(1)[1:] 

for i, name in enumerate(conference_names):
    if not name.strip(): 
        continue
        
    row_idx = i + 2
    print(f"[{row_idx}/{len(conference_names) + 1}] Processing: {name}")
    
    official_url = find_official_url(name)
    
    if official_url:
        print(f"  -> Found URL: {official_url}")
        info = get_conference_info(official_url)
        row_data = [official_url] + info 
        sheet.update(values=[row_data], range_name=f'B{row_idx}:H{row_idx}')
    else:
        print("  -> Official site not found.")
        sheet.update_acell(f'B{row_idx}', "Official site not found")

    time.sleep(15) 

print("Successfully finished processing all conferences!")
