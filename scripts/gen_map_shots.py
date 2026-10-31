# gen_map_shots: takes the module map pictures of
# README.md (assets/map-*.png) from assets/modules.html
# in a headless Chromium, so they can be made again when
# the map changes
#
#   python scripts/gen_map_shots.py
#   python scripts/gen_map_shots.py --chromium PATH
#       with that Chromium, not Playwright's own
#
# needs Playwright for Python, which is not in
# requirements.txt (a PC tool, not for Termux):
#   pip install playwright
#   python -m playwright install chromium
#
# the pictures: the modules view with process selected
# and the types view as it opens, each in the light and
# the dark theme, without the footnote; the page's
# fonts come from Google Fonts, so take them online
#
# public functions:
#   shots()    [(path, view, theme)] of the pictures
#   take(chromium=None)
#              take every picture, return their paths

import importlib.util
import os
import sys

ROOT_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
PAGE = os.path.join(ROOT_DIR, "assets", "modules.html")
VIEWS = ("modules", "types")
THEMES = ("light", "dark")
# the browser window; the pictures are 1.5 times as
# large, sharp on a high-resolution screen
WIDTH, HEIGHT, SCALE = 1400, 900, 1.5
# the module selected in the modules view
SELECTED = "process"


def shots():
    """(path, view, theme) of each picture"""
    return [
        (
            os.path.join(
                ROOT_DIR,
                "assets",
                f"map-{view}-{theme}.png",
            ),
            view,
            theme,
        )
        for theme in THEMES
        for view in VIEWS
    ]


def take(chromium=None):
    """take every picture with chromium (a path, or
    Playwright's own); return their paths"""
    from playwright.sync_api import sync_playwright

    url = "file://" + PAGE
    taken = []
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(
                executable_path=chromium
            )
        except Exception as e:
            # Playwright's message is a long box
            first = str(e).strip().splitlines()[0]
            raise SystemExit(
                f"no Chromium: {first}\n"
                "install it with python -m playwright "
                "install chromium, or give one with "
                "--chromium PATH"
            ) from None
        for path, view, theme in shots():
            page = browser.new_page(
                viewport={"width": WIDTH, "height": HEIGHT},
                device_scale_factor=SCALE,
                color_scheme=theme,
            )
            page.goto(f"{url}#{view}")
            # the fonts, then the drawing of the lines
            page.evaluate(
                "document.fonts.ready.then(() => true)"
            )
            page.wait_for_timeout(500)
            if view == "modules":
                page.click(f"#n-{SELECTED}")
                # not hovering a module any more
                page.mouse.move(0, 0)
                page.wait_for_timeout(300)
            page.evaluate(
                "document.querySelectorAll('.foot')"
                ".forEach(f => f.hidden = true)"
            )
            page.locator(".wrap").screenshot(path=path)
            page.close()
            taken.append(path)
        browser.close()
    return taken


def _main(args):
    chromium = None
    if args[:1] == ["--chromium"] and len(args) == 2:
        chromium = args[1]
    elif args:
        print(
            "usage: gen_map_shots.py [--chromium PATH]",
            file=sys.stderr,
        )
        return 2
    if importlib.util.find_spec("playwright") is None:
        print(
            "needs Playwright: pip install playwright, "
            "then python -m playwright install chromium",
            file=sys.stderr,
        )
        return 1
    for path in take(chromium):
        print(f"wrote {os.path.relpath(path)}")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
