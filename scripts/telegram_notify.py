import requests
import os
from dotenv import load_dotenv

# .env lives in the repo root, one level above scripts/
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

def notify(text):
    resp = requests.post(
        f"https://api.telegram.org/bot{os.environ["TOKEN"]}/sendMessage",
        data={"chat_id": os.environ["CHAT_ID"], "text": text},
        timeout=10,
    )
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram error: {data}")
    return data

if __name__ == "__main__":
    print(notify("test TOKEN "))
