from flask import Flask, render_template, request, jsonify
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

app = Flask(__name__)

# --- Configuration ---
CREDENTIALS_PATH = 'qc-automation-461220-bd2c48165fae.json'
SPREADSHEET_ID = '1muVNIlWotyMX1Rr1owKxFo2nAeYRe0WP2CdteBk8_Ec'
SHEET_NAME = 'SDI'
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']


def find_project(full_id):
    prefix = full_id[:5]
    try:
        creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)
        service = build('sheets', 'v4', credentials=creds)
        result = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=SHEET_NAME).execute()
        values = result.get('values', [])

        if not values: return None
        header = [h.strip().lower() for h in values[0]]
        dummy_idx = header.index('dummy text')
        url_idx = header.index('login rd')
        pw_idx = header.index('pw rd')

        for row in values[1:]:
            if len(row) > dummy_idx and row[dummy_idx].strip() == prefix:
                return {
                    "url": row[url_idx] if len(row) > url_idx else None,
                    "pw": row[pw_idx] if len(row) > pw_idx else None
                }
    except Exception as e:
        print(f"Sheet Error: {e}")
    return None


def run_scraper(url, password, resp_id):
    chrome_options = Options()
    chrome_options.add_argument('--headless=new')
    chrome_options.add_argument('--no-sandbox')  # Required for Docker
    chrome_options.add_argument('--disable-dev-shm-usage')  # Required for Docker
    chrome_options.add_argument('--disable-gpu')

    # In Docker/Cloud, we don't usually need to specify the path
    driver = webdriver.Chrome(options=chrome_options)
    wait = WebDriverWait(driver, 25)

    try:
        driver.get(url)
        wait.until(EC.presence_of_element_located((By.ID, "password-input"))).send_keys(password)
        driver.find_element(By.CLASS_NAME, 'button-primary').click()

        wait.until(EC.presence_of_element_located((By.ID, "respondent-viewer")))
        form = driver.find_element(By.ID, "respondent-viewer")
        form.find_element(By.NAME, "respondentId").send_keys(resp_id)
        form.find_element(By.CSS_SELECTOR, "button.button2").click()

        wait.until(lambda d: len(d.window_handles) > 1)
        driver.switch_to.window(driver.window_handles[1])

        # Ensure summary is open
        summary_xpath = "//summary[contains(text(), 'Respondent Information')]"
        wait.until(EC.presence_of_element_located((By.XPATH, summary_xpath)))
        details = driver.find_element(By.XPATH, f"{summary_xpath}/..")
        if not details.get_attribute("open"): details.click()

        res_info = {}
        rows = driver.find_elements(By.CSS_SELECTOR, ".respondent-info-table tr")
        for row in rows:
            label = row.find_element(By.TAG_NAME, "th").text.strip().lower()
            value = row.find_element(By.TAG_NAME, "td").text.strip()
            res_info[label] = value

        questions = driver.find_elements(By.CSS_SELECTOR, "li.question-detail h2")
        last_q = questions[-1].text.strip() if questions else "No questions found"

        return {
            "success": True,
            "status": res_info.get("status", "Unknown"),
            "reason": res_info.get("term reason", "N/A"),
            "time": res_info.get("time active", "N/A"),
            "last_q": last_q
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        driver.quit()


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/check', methods=['POST'])
def check():
    resp_id = request.form.get('resp_id', '').strip()
    if not resp_id:
        return render_template('index.html', error="Please enter an ID.")

    project = find_project(resp_id)
    if not project:
        return render_template('index.html', error=f"ID Prefix '{resp_id[:5]}' not found in Sheet.")

    result = run_scraper(project['url'], project['pw'], resp_id)
    if result['success']:
        return render_template('index.html', result=result, resp_id=resp_id)
    else:
        return render_template('index.html', error=result['error'])


if __name__ == '__main__':
    # Set debug=False for internal production use
    app.run(host='0.0.0.0', port=5000, debug=True)
