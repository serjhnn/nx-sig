import urllib.request
import os
from dotenv import load_dotenv
 
# .env lives in the repo root, one level above scripts/
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
 
def notify(msg, title="nX-siG"):
    req = urllib.request.Request(
        f"https://ntfy.sh/{os.environ["NTFY_TOPIC"]}",
        data=msg.encode(),
        headers={"Title": title,
                 "Priority": "default"},
    )
    urllib.request.urlopen(req)
 
notify("test notification !!!")
