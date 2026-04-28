#!/usr/bin/env python3
"""
✈️ טוסטוס — מעקב טיסות + התראות טלגרם
"""

import time
import json
import os
import hashlib
import schedule
import requests
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

TELEGRAM_BOT_TOKEN     = "8105701826:AAHS24biqRziOcDI6ELtAEPdmrlsFw_GMXs"
TELEGRAM_CHAT_ID       = "-5227193437"
TARGET_URL             = "https://www.tustus.co.il/Arkia/Home"
CHECK_INTERVAL_MINUTES = 15
STATE_FILE             = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen_tustus.json")

def now():
    return datetime.now().strftime("%d/%m %H:%M")

def load_seen():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    return set()

def save_seen(seen):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen), f, ensure_ascii=False)

def build_driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1440,900")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/147.0.0.0 Safari/537.36"
    )
    opts.add_argument("--lang=he-IL")
    return webdriver.Chrome(options=opts)

def scrape_tustus():
    driver = build_driver()
    flights = []
    try:
        driver.get(TARGET_URL)
        
        # ממתין שהכרטיסים יטענו
        wait = WebDriverWait(driver, 20)
        try:
            wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "a, div, article")
            ))
        except Exception:
            pass
        time.sleep(5)

        # מנסה למצוא כרטיסי טיסה לפי תוכן הטקסט
        # האתר מציג כרטיסים עם "טיסה ל" ומחיר
        page_source = driver.page_source
        
        # מחפש את כל האלמנטים שמכילים "טיסה"
        elements = driver.find_elements(By.XPATH, 
            "//*[contains(text(),'טיסה') or contains(text(),'להזמנה')]"
        )
        
        # מנסה גם לפי מבנה כרטיס
        cards = driver.find_elements(By.CSS_SELECTOR, 
            "[class*='card'], [class*='Card'], [class*='item'], [class*='Item'], [class*='deal'], [class*='flight'], [class*='offer']"
        )
        
        if not cards:
            # נסיון נוסף — כל div שמכיל תמונה וטקסט
            cards = driver.find_elements(By.CSS_SELECTOR, "a[href*='flight'], a[href*='deal'], a[href*='order']")
        
        print(f"[{now()}] 🔍 נמצאו {len(cards)} כרטיסים")

        seen_titles = set()
        for card in cards:
            try:
                text = card.text.strip()
                if not text or len(text) < 5:
                    continue
                if "טיסה" not in text and "₪" not in text and "$" not in text:
                    continue

                lines = [l.strip() for l in text.split("\n") if l.strip()]
                
                title = ""
                price = ""
                dates = ""
                
                for line in lines:
                    if "טיסה ל" in line or "חופשה ב" in line:
                        title = line
                    elif "₪" in line or "$" in line:
                        price = line
                    elif "/" in line and ("יום" in line or "-" in line):
                        dates = line

                if not title:
                    title = lines[0] if lines else ""
                
                if not title or title in seen_titles:
                    continue
                    
                seen_titles.add(title)

                try:
                    link = card.get_attribute("href") or TARGET_URL
                    if link and not link.startswith("http"):
                        link = "https://www.tustus.co.il" + link
                except Exception:
                    link = TARGET_URL

                uid = hashlib.md5(f"{title}{price}{dates}".encode()).hexdigest()[:12]

                flights.append({
                    "id": uid,
                    "title": title,
                    "price": price,
                    "dates": dates,
                    "url": link or TARGET_URL,
                })
                
            except Exception:
                continue

    except Exception as e:
        print(f"[{now()}] ❌ שגיאת סריקה: {e}")
    finally:
        driver.quit()

    print(f"[{now()}] ✈️ סה\"כ {len(flights)} טיסות זוהו")
    return flights

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }, timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[{now()}] ❌ שגיאת טלגרם: {e}")
        return False

def format_message(f):
    lines = ["✈️ <b>טיסה חדשה בטוסטוס!</b>", ""]
    lines.append(f"📍 <b>{f['title']}</b>")
    if f["dates"]:
        lines.append(f"📅 {f['dates']}")
    if f["price"]:
        lines.append(f"💰 {f['price']}")
    lines.append(f"🔗 <a href='{f['url']}'>להזמנה באתר טוסטוס</a>")
    lines.append(f"\n🕐 {now()}")
    return "\n".join(lines)

def check():
    print(f"\n[{now()}] 🔄 סריקה...")
    seen = load_seen()
    flights = scrape_tustus()
    new = [f for f in flights if f["id"] not in seen]

    if not new:
        print(f"[{now()}] ✅ אין חדש ({len(flights)} טיסות, כולן מוכרות)")
        return

    print(f"[{now()}] 🆕 {len(new)} טיסות חדשות!")
    for f in new:
        print(f"  → {f['title']} | {f['price']} | {f['dates']}")
        if send_telegram(format_message(f)):
            seen.add(f["id"])
        time.sleep(1)

    save_seen(seen)

if __name__ == "__main__":
    print("=" * 50)
    print("✈️  טוסטוס מוניטור — מתחיל")
    print("=" * 50)

    check()

    send_telegram(
        f"✅ <b>בוט טוסטוס פעיל!</b>\n"
        f"📡 סריקה כל {CHECK_INTERVAL_MINUTES} דקות\n"
        f"🌐 tustus.co.il"
    )

    schedule.every(CHECK_INTERVAL_MINUTES).minutes.do(check)
    print(f"\n⏰ בודק כל {CHECK_INTERVAL_MINUTES} דקות. Ctrl+C לעצירה.\n")

    while True:
        schedule.run_pending()
        time.sleep(30)
