import os
import sys
import django
from bs4 import BeautifulSoup
import time

sys.path.append(r'C:\Users\AB\mon_projet_epb\epb_smart')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'epb_smart.settings')
django.setup()

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

URL = "https://www.portdebejaia.dz/situation-des-navires/"

def diagnostic():
    print("🌐 Lancement du navigateur...")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()))
    try:
        driver.get(URL)
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.TAG_NAME, "table")))
        time.sleep(2)
        html = driver.page_source
    finally:
        driver.quit()

    soup = BeautifulSoup(html, 'html.parser')
    tables = soup.find_all('table')
    print(f"Nombre de tableaux : {len(tables)}")
    for i, table in enumerate(tables):
        rows = table.find_all('tr')
        print(f"\nTableau {i+1} : {len(rows)} lignes")
        if not rows:
            continue
        # Afficher les 2 premières lignes
        for r in rows[:2]:
            cells = r.find_all(['th', 'td'])
            cell_texts = [cell.get_text(strip=True) for cell in cells]
            print(f"  {cell_texts}")

if __name__ == "__main__":
    diagnostic()