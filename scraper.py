import os
import json
import time
import gspread
import trafilatura
import google.generativeai as genai
from google.oauth2.service_account import Credentials

# 1. Configuration
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
GOOGLE_CREDS = json.loads(os.environ["GOOGLE_CREDENTIALS"])
SHEET_ID = os.environ["GOOGLE_SHEET_ID"]

# Setup Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash-lite')

# Setup Google Sheets
scope = ['https://www.googleapis.com/auth/spreadsheets']
creds = Credentials.from_service_account_info(GOOGLE_CREDS, scopes=scope)
gc = gspread.authorize(creds)
sheet = gc.open_by_key(SHEET_ID).sheet1

def get_conference_info(url):
    try:
        downloaded = trafilatura.fetch_url(url)
        content = trafilatura.extract(downloaded, include_links=True) # Tell it to include links
        if not content: return ["Error: Page unreadable"] + ([""] * 6)

        prompt = f"""
        Extract these conference details from the text:
        - Name
        - Location
        - Status (Submission, Participation Only, or Ended)
        - Deadline (YYYY-MM-DD)
        - Start Date (YYYY-MM-DD)
        - End Date (YYYY-MM-DD)
        
        CRITICAL: If the conference on this page has 'Ended', look through the text/links 
        for a URL to the NEXT year's conference (e.g., if this is the 25th, look for the 26th).
        
        Return strictly JSON:
        {{
          "Name": "...",
          "Location": "...",
          "Status": "...",
          "Deadline": "...",
          "Start Date": "...",
          "End Date": "...",
          "New_URL": "Provide the URL to next year's page ONLY if found, otherwise null"
        }}

        Text: {content[:5000]}
        """
        
        response = model.generate_content(prompt)
        clean_json = response.text.replace('```json', '').replace('```', '').strip()
        data = json.loads(clean_json)

        return {
            "row_data": [
                data.get('Name', 'N/A'),
                data.get('Location', 'N/A'),
                data.get('Status', 'N/A'),
                data.get('Deadline', 'N/A'),
                data.get('Start Date', 'N/A'),
                data.get('End Date', 'N/A')
            ],
            "new_url": data.get('New_URL')
        }
    except Exception as e:
        return {"row_data": [f"Error: {str(e)}"] + ([""] * 5), "new_url": None}

# --- Inside the execution loop ---
for i, url in enumerate(urls):
    row_idx = i + 2
    result = get_conference_info(url)
    
    # 1. Update the Data (Columns B-G)
    sheet.update(range_name=f'B{row_idx}:G{row_idx}', values=[result["row_data"]])
    
    # 2. SELF-HEALING: If AI found a new year's link, update Column A for next time!
    if result["new_url"]:
        sheet.update_acell(f'A{row_idx}', result["new_url"])
        print(f"Updated URL to: {result['new_url']}")

print("Finished!")
