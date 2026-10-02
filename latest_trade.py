import requests
import json
import os
from dotenv import load_dotenv
from rich import print


load_dotenv()
with open("config.json") as f:
    config = json.load(f)


headers = {
    "accept": "application/json",
    "APCA-API-KEY-ID": os.environ["APCA_API_KEY_ID"],
    "APCA-API-SECRET-KEY": os.environ["APCA_API_SECRET_KEY"]
}

response = requests.get(config["url"], 
    params = {
        "symbols": ",".join(config["indices"]), 
        "feed": config["feed"]
        },
    headers=headers)

data = response.json()

c_ = ["bold magenta", "bold green"]

print("\n".join(
    f"[{c_[0]}]{index}[/{c_[0]}]: [{c_[1]}]{data['trades'][index]['p']:.2f}[/{c_[1]}]" 
    for index in config["indices"])
    )


