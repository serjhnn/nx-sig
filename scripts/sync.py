# sync: keeps the data folder (config "storage_dir") the
# same on the phone (Termux) and the PC (Linux) with
# Syncthing. The devices connect directly, over Wi-Fi, a
# phone hotspot or USB tethering; no internet or outside
# server is used (global discovery and relays are off).
#
#   python scripts/sync.py setup        install, set up
#                                       and start syncthing,
#                                       print this device's
#                                       ID
#   python scripts/sync.py setup <ID>   the same, and share
#                                       the folder with
#                                       device <ID>
#   python scripts/sync.py status       ID, peers, folder
#   python scripts/sync.py stop         stop syncthing
#   python scripts/sync.py              run the tests
#
# pairing: run 'setup' on both devices, then 'setup <ID>'
# on each one with the other's ID. Before the first sync
# only one device should have data in the folder, or the
# files that differ end up as *.sync-conflict-* copies.
#
# syncthing runs with its own config in SYNC_HOME, so it
# doesn't touch another syncthing on the same device. Its
# web page is at the address 'status' prints. Replaced or
# deleted files are kept in {storage_dir}/.stversions
# (the last KEEP_VERSIONS of each).
#
# public functions:
#   setup(peer_id=None)
#       install if needed, start, configure; return the
#       device ID
#   status_lines()
#       lines for 'status'
#   stop()
#       stop syncthing, True if it was running
#   stignore_text(old)
#       .stignore content with the patterns added
#   check_device_id(text)
#       the ID in canonical form, or raise SyncError

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

import storage

FOLDER_ID = "nx-sig-data"
FOLDER_LABEL = "nx-sig data"
SYNC_HOME = os.path.expanduser("~/.config/nx-sig-sync")
CONFIG_XML = os.path.join(SYNC_HOME, "config.xml")
LOG_PATH = os.path.join(SYNC_HOME, "syncthing.log")
KEEP_VERSIONS = "10"
START_WAIT_SECONDS = 30
# files only one device uses: the lock, the logs, the
# pid and heartbeats of the processes running here, and
# storage.py's temp files during an atomic write
IGNORE = [
    ".lock",
    "logs",
    "mtsig.pid",
    "mtsig_status.json",
    "ladders_status.json",
    ".tmp_*",
]
# 8 groups of 7 base32 characters
DEVICE_ID_RE = re.compile(r"[A-Z2-7]{7}(-[A-Z2-7]{7}){7}")


class SyncError(Exception):
    pass


def setup(peer_id=None):
    """
    install syncthing if missing, start it, share the
    data folder (with peer_id too, when given), return
    this device's ID
    """
    if peer_id:
        peer_id = check_device_id(peer_id)
    _install()
    os.makedirs(storage.DB_DIR, exist_ok=True)
    _write_stignore()
    _start()
    api = _Api()
    my_id = api.get("/rest/system/status")["myID"]
    api.patch(
        "/rest/config/options",
        {
            # direct connections only, no outside server
            "globalAnnounceEnabled": False,
            "relaysEnabled": False,
            "natEnabled": False,
            "urAccepted": -1,
            "startBrowser": False,
        },
    )
    if peer_id and peer_id != my_id:
        _add_device(api, peer_id)
    _share_folder(api, my_id, peer_id)
    # the "Default Folder" (~/Sync) of a new syncthing
    api.delete("/rest/config/folders/default")
    return my_id


def status_lines():
    """this device's ID, the peers and the folder"""
    if not _running():
        return ["syncthing is not running,",
                "start it with 'sync.py setup'"]
    api = _Api()
    my_id = api.get("/rest/system/status")["myID"]
    conns = api.get("/rest/system/connections")
    lines = ["this device:"] + _split_id(my_id)
    lines.append("peers:")
    peers = {
        dev_id: conn
        for dev_id, conn in conns["connections"].items()
        if dev_id != my_id
    }
    for dev_id, conn in peers.items():
        state = ("connected" if conn["connected"]
                 else "not connected")
        lines.append(f"  {dev_id[:7]} {state}")
    if not peers:
        lines.append("  none, add one: setup <ID>")
    folder = api.get(
        f"/rest/db/status?folder={FOLDER_ID}"
    )
    lines.append(f"folder: {folder['state']}, "
                 f"{folder['needFiles']} to fetch")
    lines.append(f"web page: http://{api.address}")
    return lines


def stop():
    """stop syncthing, True if it was running"""
    if not _running():
        return False
    _Api().post("/rest/system/shutdown")
    return True


def check_device_id(text):
    """
    a device ID as syncthing shows it, case and spaces
    don't matter; raise SyncError if it isn't one
    """
    dev_id = re.sub(r"\s", "", text).upper()
    if not DEVICE_ID_RE.fullmatch(dev_id):
        raise SyncError(f"not a device ID: {text}")
    return dev_id


def stignore_text(old):
    """old .stignore content with the IGNORE patterns
    that are missing added at the end"""
    lines = old.splitlines()
    missing = [p for p in IGNORE if p not in lines]
    if not missing:
        return old
    if old and not old.endswith("\n"):
        old += "\n"
    return old + "\n".join(missing) + "\n"


def _split_id(dev_id):
    # 63 characters: two lines fit the 48-wide screen
    return ["  " + dev_id[:31], "  " + dev_id[32:]]


def _termux():
    return "TERMUX_VERSION" in os.environ


def _install():
    if shutil.which("syncthing"):
        return
    if _termux():
        cmd = ["pkg", "install", "-y", "syncthing"]
    elif shutil.which("apt"):
        cmd = ["sudo", "apt", "install", "-y", "syncthing"]
    else:
        raise SyncError(
            "install syncthing with your package "
            "manager, then run this again"
        )
    print("installing syncthing:", " ".join(cmd))
    subprocess.run(cmd, check=True)


def _write_stignore():
    path = os.path.join(storage.DB_DIR, ".stignore")
    try:
        with open(path) as f:
            old = f.read()
    except FileNotFoundError:
        old = ""
    new = stignore_text(old)
    if new != old:
        with open(path, "w") as f:
            f.write(new)


def _running():
    if not os.path.exists(CONFIG_XML):
        return False
    try:
        _Api().get("/rest/system/ping")
    except (OSError, SyncError):
        return False
    return True


def _start():
    if _running():
        return
    os.makedirs(SYNC_HOME, exist_ok=True)
    # syncthing 1.x creates ~/Sync on its first start
    # without this
    env = {**os.environ, "STNODEFAULTFOLDER": "1"}
    cmd = [
        "syncthing",
        "serve",
        "--no-browser",
        f"--home={SYNC_HOME}",
    ]
    with open(LOG_PATH, "a") as log:
        process = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
            # closing the shell doesn't stop it
            start_new_session=True,
        )
    deadline = time.monotonic() + START_WAIT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SyncError(
                "syncthing stopped right after starting,"
                f" see {LOG_PATH}"
            )
        if _running():
            return
        time.sleep(0.5)
    raise SyncError(
        f"syncthing didn't answer, see {LOG_PATH}"
    )


def _add_device(api, dev_id):
    try:
        api.get(f"/rest/config/devices/{dev_id}")
        return
    except SyncError:
        pass
    device = api.get("/rest/config/defaults/device")
    # an empty name takes the name the device sends
    device.update(
        deviceID=dev_id, name="", addresses=["dynamic"]
    )
    api.put(f"/rest/config/devices/{dev_id}", device)


def _share_folder(api, my_id, peer_id):
    try:
        folder = api.get(
            f"/rest/config/folders/{FOLDER_ID}"
        )
    except SyncError:
        folder = api.get("/rest/config/defaults/folder")
        folder["versioning"].update(
            type="simple",
            params={"keep": KEEP_VERSIONS},
        )
    folder.update(
        id=FOLDER_ID,
        label=FOLDER_LABEL,
        path=storage.DB_DIR,
        type="sendreceive",
        fsWatcherEnabled=True,
    )
    have = {d["deviceID"] for d in folder["devices"]}
    for dev_id in (my_id, peer_id):
        if dev_id and dev_id not in have:
            folder["devices"].append({"deviceID": dev_id})
    api.put(f"/rest/config/folders/{FOLDER_ID}", folder)


class _Api:
    """the REST API of the syncthing in SYNC_HOME, its
    address and key are read from config.xml"""

    def __init__(self):
        gui = ET.parse(CONFIG_XML).getroot().find("gui")
        self.address = gui.findtext("address")
        self.key = gui.findtext("apikey")
        tls = gui.get("tls") == "true"
        scheme = "https" if tls else "http"
        self.base = f"{scheme}://{self.address}"

    def get(self, path):
        return self._call("GET", path)

    def post(self, path):
        return self._call("POST", path)

    def put(self, path, data):
        return self._call("PUT", path, data)

    def patch(self, path, data):
        return self._call("PATCH", path, data)

    def delete(self, path):
        try:
            return self._call("DELETE", path)
        except SyncError:
            # it wasn't there
            return None

    def _call(self, method, path, data=None):
        body = None
        headers = {"X-API-Key": self.key}
        if data is not None:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(
            self.base + path,
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(
                req, timeout=10
            ) as resp:
                text = resp.read().decode()
        except urllib.error.HTTPError as e:
            raise SyncError(
                f"{method} {path}: {e.code}"
            ) from None
        return json.loads(text) if text.strip() else None


def _main(args):
    try:
        if args[0] == "setup" and len(args) <= 2:
            peer = args[1] if len(args) == 2 else None
            my_id = setup(peer)
            print("syncing", storage.DB_DIR)
            print("this device's ID:")
            print("\n".join(_split_id(my_id)))
            if not peer:
                print("pair: on the other device run")
                print("  sync.py setup <this ID>")
        elif args == ["status"]:
            print("\n".join(status_lines()))
        elif args == ["stop"]:
            print("stopped" if stop() else "not running")
        else:
            print("usage: sync.py setup [ID] | status "
                  "| stop")
            return 2
    except (SyncError, OSError) as e:
        print("error:", e, file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as e:
        print("error: install failed:", e,
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__" and len(sys.argv) > 1:
    sys.exit(_main(sys.argv[1:]))

elif __name__ == "__main__":
    import unittest

    ID = (
        "ABCDEFG-HIJKLMN-OPQRSTU-VWXYZ23-"
        "4567ABC-DEFGHIJ-KLMNOPQ-RSTUVWX"
    )

    class SyncTests(unittest.TestCase):
        def test_device_id(self):
            self.assertEqual(check_device_id(ID), ID)
            # pasted lower case, with spaces or a newline
            low = ID.lower()
            messy = " " + low[:20] + "\n" + low[20:]
            self.assertEqual(check_device_id(messy), ID)
            for bad in ("", "ABC", ID[:-1], ID + "-A"):
                with self.assertRaises(SyncError):
                    check_device_id(bad)
            # 0, 1, 8, 9 aren't base32
            with self.assertRaises(SyncError):
                check_device_id(ID.replace("2", "0"))

        def test_stignore_new(self):
            text = stignore_text("")
            self.assertEqual(text.splitlines(), IGNORE)

        def test_stignore_keeps_own(self):
            old = "my.csv\n.lock"
            text = stignore_text(old)
            lines = text.splitlines()
            self.assertEqual(lines[:2], ["my.csv", ".lock"])
            self.assertEqual(lines.count(".lock"), 1)
            self.assertTrue(set(IGNORE) <= set(lines))
            # nothing more to add the second time
            self.assertEqual(stignore_text(text), text)

        def test_split_id(self):
            lines = _split_id(ID)
            joined = lines[0] + "-" + lines[1]
            self.assertEqual(joined.replace(" ", ""), ID)
            for line in lines:
                self.assertLessEqual(len(line), 48)

    unittest.main()
