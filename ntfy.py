import urllib.request
import os
from dotenv import load_dotenv
 
load_dotenv()
 
def notify(msg, title="nX-siG"):
    req = urllib.request.Request(
        f"https://ntfy.sh/{os.environ["NTFY_TOPIC"]}",
        data=msg.encode(),
        headers={"Title": title,
                 "Priority": "default"},
    )
    urllib.request.urlopen(req)
 
notify("test notification !!!")
