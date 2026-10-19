# gen_deps: writes the module map, assets/modules.html,
# from the imports of the code, so the map and the code
# say the same
#
#   python scripts/gen_deps.py          write the map
#   python scripts/gen_deps.py --check  exit 1 if it is
#                                       out of date
#
# the page is a template: only the lines between
# BEGIN and END are written, the rest is edited by
# hand. it reads the code with ast, nothing is run:
#   modules    the .py files of scripts/, its
#              engines/, shell/ and mtsig/, and of
#              tests/ (group tests)
#   imports    every import, but not the ones under
#              if __name__ == "__main__"
#   loaded     the modules loaded by name (importlib):
#              commands loads every shell/*_cmd.py,
#              notifier the values of its CHANNELS
#   text       the first sentence of the header comment
#
# public functions:
#   modules()     {id: [group, text, imports, loaded]}
#   page()        the text of the map
#   up_to_date()  True if the map matches it

import ast
import json
import os
import re
import sys

ROOT_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)
SCRIPTS = os.path.join(ROOT_DIR, "scripts")
TESTS = os.path.join(ROOT_DIR, "tests")
PATH = os.path.join(ROOT_DIR, "assets", "modules.html")
FOLDERS = ("", "engines", "shell", "mtsig")
BEGIN = "// BEGIN modules, written by gen_deps.py\n"
END = "// END modules\n"

# the folders and the notify channels give the other
# groups, every module left is a tool
CORE = {"config", "storage", "trade_engine"}
ENGINES = {
    "tasks_owner",
    "process",
    "chart",
    "ladder",
    "alerts",
}


def _paths():
    """{id: path}, the id is the path in scripts/
    without .py, e.g. shell/ui, or tests/ and the
    name for a test, e.g. tests/test_storage"""
    found = {}
    folders = [
        (f, os.path.join(SCRIPTS, f)) for f in FOLDERS
    ]
    folders.append(("tests", TESTS))
    for folder, full in folders:
        for name in sorted(os.listdir(full)):
            if not name.endswith(".py"):
                continue
            # paths.py only sets sys.path for the tests
            if name in ("__init__.py", "paths.py"):
                continue
            stem = name[: -len(".py")]
            key = f"{folder}/{stem}" if folder else stem
            found[key] = os.path.join(full, name)
    return found


def _is_main(node):
    """True for if __name__ == "__main__":"""
    test = getattr(node, "test", None)
    return (
        isinstance(node, ast.If)
        and isinstance(test, ast.Compare)
        and isinstance(test.left, ast.Name)
        and test.left.id == "__name__"
    )


def _import_nodes(node):
    for child in ast.iter_child_nodes(node):
        if _is_main(child):
            continue
        if isinstance(child, (ast.Import, ast.ImportFrom)):
            yield child
        yield from _import_nodes(child)


def _resolve(dotted, folder, known):
    """the id of an imported name, or None for a
    package outside scripts/; a bare name in mtsig/
    is its neighbor first (sys.path), in tests/ a
    name in mtsig/ too (tests/paths.py)"""
    key = dotted.replace(".", "/")
    near = "mtsig" if folder == "tests" else folder
    while key:
        for found in (f"{near}/{key}", key):
            if found in known:
                return found
        key = key.rpartition("/")[0]
    return None


def _imports(tree, folder, known):
    found = set()
    for node in _import_nodes(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif node.level or not node.module:
            continue
        else:
            # from shell import ui is shell/ui
            names = [
                f"{node.module}.{a.name}"
                for a in node.names
            ]
        for name in names:
            key = _resolve(name, folder, known)
            if key:
                found.add(key)
    return found


def _channels(tree):
    """the values of notifier's CHANNELS dict"""
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) == "CHANNELS"
            for t in node.targets
        ):
            return list(
                ast.literal_eval(node.value).values()
            )
    return []


def _loaded(key, tree, known):
    if key == "commands":
        return sorted(
            k
            for k in known
            if k.startswith("shell/") and k.endswith("_cmd")
        )
    if key == "notifier":
        return [k for k in _channels(tree) if k in known]
    return []


def _text(tree, source):
    """the first sentence of the docstring or of the
    header comment, without its 'name:'"""
    doc = ast.get_docstring(tree)
    lines = []
    if doc:
        lines = doc.split("\n\n")[0].splitlines()
    else:
        for line in source.splitlines():
            if not line.startswith("#"):
                break
            line = line.lstrip("#").strip()
            if not line:
                break
            lines.append(line)
    text = " ".join(lines)
    text = re.sub(r"^[\w ]+: ", "", text)
    text = re.split(r"(?<=[.:])\s", text)[0].rstrip(".:")
    return text[:1].upper() + text[1:] if text else ""


def _group(key, channels):
    if key in CORE:
        return "core"
    if key in ENGINES or key.startswith("engines/"):
        return "engine"
    if key == "notifier" or key in channels:
        return "notify"
    if key.startswith("mtsig/"):
        return "mtsig"
    if key.startswith("shell/") or key == "commands":
        return "shell"
    if key.startswith("tests/"):
        return "tests"
    return "tools"


def modules():
    paths = _paths()
    known = set(paths)
    trees, sources = {}, {}
    for key, path in paths.items():
        with open(path, encoding="utf-8") as f:
            sources[key] = f.read()
        trees[key] = ast.parse(sources[key], path)
    channels = _loaded("notifier", trees["notifier"], known)
    found = {}
    for key, tree in trees.items():
        folder = key.rpartition("/")[0]
        imports = _imports(tree, folder, known)
        imports.discard(key)
        # an imported module is not also loaded by name
        loaded = [
            k
            for k in _loaded(key, tree, known)
            if k not in imports
        ]
        found[key] = [
            _group(key, channels),
            _text(tree, sources[key]),
            sorted(imports),
            loaded,
        ]
    return found


def _data():
    lines = ["const MODS = {\n"]
    for key, value in modules().items():
        lines.append(f"  {json.dumps(key)}: ")
        lines.append(json.dumps(value) + ",\n")
    return "".join(lines) + "};\n"


def page():
    with open(PATH, encoding="utf-8") as f:
        text = f.read()
    head, _, rest = text.partition(BEGIN)
    _, _, tail = rest.partition(END)
    if not tail:
        raise ValueError(f"{PATH} has no BEGIN/END")
    return head + BEGIN + _data() + END + tail


def up_to_date():
    try:
        with open(PATH, encoding="utf-8") as f:
            return f.read() == page()
    except (OSError, ValueError):
        return False


if __name__ == "__main__":
    if sys.argv[1:] == ["--check"]:
        if up_to_date():
            print("ok: assets/modules.html is up to date")
            sys.exit(0)
        print(
            "assets/modules.html is out of date, run "
            "python scripts/gen_deps.py"
        )
        sys.exit(1)
    text = page()
    with open(PATH, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"wrote {os.path.relpath(PATH)}")
