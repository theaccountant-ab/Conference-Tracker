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
        # Fetch webpage content
        downloaded = trafilatura.fetch_url(url)
        content = trafilatura.extract(downloaded)
        if not content: return ["Error: No content found"] * 6

        # AI Prompt
        prompt = f"""
        Extract the following conference details from the text below:
        - Name
        - Location
        - Status (Choose one: 'Submission', 'Participation Only', or 'Ended')
        - Submission Deadline (YYYY-MM-DD)
        - Start Date (YYYY-MM-DD)
        - End Date (YYYY-MM-DD)

        Text: {content[:5000]}
        Return strictly JSON format.
        """
        
        response = model.generate_content(prompt)
        # Clean the response string to get valid JSON
        raw_text = response.text.replace('```json', '').replace('```', '').strip()
        data = json.loads(raw_text)

        return [
            data.get('Name', 'N/A'),
            data.get('Location', 'N/A'),
            data.get('Status', 'N/A'),
            data.get('Submission Deadline', 'N/A'),
            data.get('Start Date', 'N/A'),
            data.get('End Date', 'N/A')
        ]
    except Exception as e:
        return [f"Error: {str(e)}"] + ([""] * 5)

# 2. Execution
urls = sheet.col_values(1)[1:]  # Column A, ignore header

for i, url in enumerate(urls):
    print(f"Scraping {i+1}/{len(urls)}: {url}")
    result = get_conference_info(url)
    
    # Update Sheet (Columns B to G)
    row_idx = i + 2
    sheet.update(range_name=f'B{row_idx}:G{row_idx}', values=[result])
    
    # Stay within free-tier rate limits (15 requests per minute)
    time.sleep(5) 

print("Finished!")
