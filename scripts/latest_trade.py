import requests
import os
from dotenv import load_dotenv
from rich import print

import config

load_dotenv(os.path.join(config.ROOT_DIR, ".env"))


headers = {
    "accept": "application/json",
    "APCA-API-KEY-ID": os.environ["APCA_API_KEY_ID"],
    "APCA-API-SECRET-KEY": os.environ[
        "APCA_API_SECRET_KEY"
    ],
}

response = requests.get(
    config.url(),
    params={
        "symbols": ",".join(config.indices()),
        "feed": config.feed(),
    },
    headers=headers,
    timeout=15,
)
response.raise_for_status()

data = response.json()

c_ = ["bold magenta", "bold green"]

name, value = c_
trades = data['trades']
print(
    "\n".join(
        f"[{name}]{index:5s}[/{name}]: "
        f"[{value}]{trades[index]['p']:.2f}[/{value}]"
        for index in config.indices()
    )
)
