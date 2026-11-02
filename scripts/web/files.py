# files: the files of the web pages the server sends,
# from the folder web/ (the pages, their style and
# scripts, the fonts) and assets/logo.svg
#
#   python tests/test_web.py   the tests
#
# the paths:
#   /             web/index.html, the main page
#                 (a page gets web/frame.html, the top
#                 bar and the menu, at its line
#                 <!-- frame -->, with the server's
#                 token for the changes, see api.py)
#   /trades       web/trades.html, the trades page
#   /ladders      web/ladders.html, the ladders page
#   /alerts       web/alerts.html, the alerts page
#   /basetrades   web/basetrades.html, the
#                 basetrades page
#   /logo         a page with the logo, as wide as the
#                 screen
#   /logo.svg     assets/logo.svg
#   /style.css    web/style.css, the style every page
#                 shares
#   /js/<f>       a .js of web/js/
#   /fonts/<f>    a .woff2 of web/fonts/
#
# public functions:
#   find(path, token)
#       (body, content type) of path, None if it
#       isn't one of them; token: the server's
#   page(file, token)
#       a page of web/ with its frame

import os

import config

WEB_DIR = os.path.join(config.ROOT_DIR, "web")
LOGO_PATH = os.path.join(
    config.ROOT_DIR, "assets", "logo.svg"
)
STYLE_PATH = os.path.join(WEB_DIR, "style.css")
INDEX_PATH = os.path.join(WEB_DIR, "index.html")
TRADES_PATH = os.path.join(WEB_DIR, "trades.html")
LADDERS_PATH = os.path.join(WEB_DIR, "ladders.html")
ALERTS_PATH = os.path.join(WEB_DIR, "alerts.html")
BASETRADES_PATH = os.path.join(WEB_DIR, "basetrades.html")
FRAME_PATH = os.path.join(WEB_DIR, "frame.html")
FRAME_MARK = b"<!-- frame -->"
TOKEN_MARK = b"{{token}}"
JS_DIR = os.path.join(WEB_DIR, "js")
FONTS_DIR = os.path.join(WEB_DIR, "fonts")
HTML = "text/html; charset=utf-8"
# the files of a path: {path: (file, content type)}
PATHS = {
    "/": (INDEX_PATH, HTML),
    "/trades": (TRADES_PATH, HTML),
    "/ladders": (LADDERS_PATH, HTML),
    "/alerts": (ALERTS_PATH, HTML),
    "/basetrades": (BASETRADES_PATH, HTML),
    "/logo.svg": (LOGO_PATH, "image/svg+xml"),
    "/style.css": (STYLE_PATH, "text/css; charset=utf-8"),
}
# the folders: {prefix: (folder, ending, content type)}
FOLDERS = {
    "/js/": (
        JS_DIR,
        ".js",
        "text/javascript; charset=utf-8",
    ),
    "/fonts/": (FONTS_DIR, ".woff2", "font/woff2"),
}
# /logo: the logo, a link to the main page
LOGO_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport"
 content="width=device-width, initial-scale=1">
<title>nX-sig</title>
<link rel="stylesheet" href="/style.css">
<style>
body {
  display: flex;
  align-items: center;
  justify-content: center;
}
img {
  width: min(520px, calc(100vw - 32px));
  height: auto;
}
</style>
</head>
<body>
<a href="/"><img src="/logo.svg" alt="nX-sig"></a>
</body>
</html>
"""


def find(path, token):
    """(body, content type) of path (without its
    ?query), None if it isn't one of the paths above;
    a page gets token, the server's"""
    if path == "/logo":
        return LOGO_PAGE.encode(), HTML
    if path in PATHS:
        file, kind = PATHS[path]
        if kind == HTML:
            return page(file, token), kind
        return _read(file), kind
    for prefix, found in FOLDERS.items():
        file = _in_folder(path, prefix, *found[:2])
        if file:
            return _read(file), found[2]
    return None


def page(file, token):
    """the page in file with web/frame.html at its
    frame line, token (the server's) in the frame"""
    frame = _read(FRAME_PATH).rstrip(b"\n")
    frame = frame.replace(TOKEN_MARK, token.encode())
    return _read(file).replace(FRAME_MARK, frame, 1)


def _in_folder(path, prefix, folder, ending):
    """the file of a <prefix><name><ending> path, None
    if there is none; only the names in folder, so no
    other file can be asked for"""
    name = path.removeprefix(prefix)
    if name == path or not name.endswith(ending):
        return None
    if name not in os.listdir(folder):
        return None
    return os.path.join(folder, name)


def _read(path):
    with open(path, "rb") as f:
        return f.read()
