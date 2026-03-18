import requests
from dotenv import load_dotenv
import os

load_dotenv()

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send(msg):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    r = requests.post(url, data={"chat_id": CHAT_ID, "text": msg})
    return r.json()

if not TOKEN or not CHAT_ID:
    print("ERROR: TELEGRAM_BOT_TOKEN ya TELEGRAM_CHAT_ID .env ma nathi!")
else:
    print("Sending test message...")
    res = send("Stock Agent Test\n\nTelegram connected successfully!\n\nBUY RELIANCE @ 2450 | SL: 2413 | Target: 2523 | Qty: 4")
    if res.get("ok"):
        print("SUCCESS - Message sent!")
    else:
        print(f"FAILED - {res}")
