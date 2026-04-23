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

def find_official_url(conference_name):
    """Refined search to find academic finance conferences."""
    # We add specific academic keywords to the search to avoid 'Trucks' and 'Apps'
    search_query = f'"{conference_name}" conference university "call for papers"'
    
    # Sites we definitely want to ignore
    junk_sites = ["trucks", "qq.com", "facebook", "linkedin", "youtube", "twitter", "instagram"]
    
    try:
        with DDGS() as ddgs:
            # We look at 10 results to find the diamond in the rough
            results = list(ddgs.text(search_query, max_results=10))
            if not results:
                return None

            options = ""
            for i, r in enumerate(results):
                # Skip obvious commercial junk
                if any(junk in r['href'].lower() for junk in junk_sites):
                    continue
                options += f"[{i}] Link: {r['href']}\nSnippet: {r['body']}\n\n"

            # We ask the AI to be a strict judge
            prompt = f"""
            Identify the OFFICIAL CONFERENCE WEBSITE for: "{conference_name}".
            Academic conferences usually live on .edu, .org, or university subdomains.
            
            Search Results:
            {options}
            
            Instructions:
            1. Look for a link that mentions the specific conference name and '2025' or '2026'.
            2. Reject generic university homepages (like just 'ox.ac.uk') unless it's the specific event page.
            3. Reject commercial sites (Trucks, Music, Social Media).
            4. Return ONLY the URL. If no result is a specific match, return 'NONE'.
            """
            
            response = model.generate_content(prompt)
            best_url = response.text.strip()
            
            if "http" in best_url and "NONE" not in best_url:
                return best_url
    except Exception as e:
        print(f"Search failed: {e}")
    return None

def get_conference_info(url):
    """Scrapes the chosen URL and extracts data."""
    try:
        downloaded = trafilatura.fetch_url(url)
        content = trafilatura.extract(downloaded)
        if not content: return ["Error: Page Content Unreadable"] + ([""] * 5)

        prompt = f"""
        Extract the following from this text:
        - Conference Name
        - Location
        - Status (Submission, Participation Only, or Ended)
        - Deadline (YYYY-MM-DD)
        - Start Date (YYYY-MM-DD)
        - End Date (YYYY-MM-DD)

        Text: {content[:5000]}
        Return ONLY JSON.
        """
        
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

# 2. Execution
conference_names = sheet.col_values(1)[1:] 

for i, name in enumerate(conference_names):
    if not name: continue
    row_idx = i + 2
    print(f"Row {row_idx}: Finding official site for {name}...")
    
    official_url = find_official_url(name)
    
    if official_url and "http" in official_url:
        print(f"Scraping Official Site: {official_url}")
        info = get_conference_info(official_url)
        sheet.update_acell(f'B{row_idx}', official_url)
        sheet.update(range_name=f'C{row_idx}:H{row_idx}', values=[info])
    else:
        sheet.update_acell(f'B{row_idx}', "Official site not found")

    time.sleep(12) # Slightly longer sleep to ensure high quality results

print("Success!")
