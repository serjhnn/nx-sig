import urllib.request

def notify(msg, title="Termux"):
    req = urllib.request.Request(
        "https://ntfy.sh/myphone-alerts-7f3k2",
        data=msg.encode(),
        headers={"Title": title, "Priority": "high"},
    )
    urllib.request.urlopen(req)

notify("Script finished!")
