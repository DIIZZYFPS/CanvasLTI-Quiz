import ast
import os
import re
import sys


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)

# import name -> the distribution that provides it, where they differ
DISTRIBUTION_FOR_MODULE = {
    "dotenv": "python-dotenv",
    "docx": "python-docx",
    "flask_caching": "flask-caching",
    "pymupdf": "pymupdf",
    "werkzeug": "flask",   # a hard dependency of Flask, imported directly for HTTPException
}
# Declared for the deployment, not imported by the app
RUNTIME_ONLY = {"gunicorn"}


def _normalise(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def _requirements(filename="requirements.txt"):
    names, lines = set(), []
    with open(os.path.join(ROOT, filename)) as f:
        for raw in f:
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            lines.append(line)
            names.add(_normalise(re.split(r"[<>=!~\[ ]", line, maxsplit=1)[0]))
    return names, lines


def _imported_modules():
    modules = set()
    for base, _dirs, files in os.walk(os.path.join(ROOT, "app")):
        if "assets" in base:
            continue
        for name in files:
            if name.endswith(".py"):
                tree = ast.parse(open(os.path.join(base, name)).read())
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        modules.update(alias.name.split(".")[0] for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                        modules.add(node.module.split(".")[0])
    modules.update(["dotenv"])  # main.py / app package use it; keep the check simple and explicit
    return {m for m in modules if m not in sys.stdlib_module_names and m != "app"}


def test_every_third_party_import_is_declared():
    """Regression: `requests` (imported in two files) and, via keys.py, pycryptodome were used
    but never listed, so a clean install worked only by accident of transitive dependencies."""
    declared, _ = _requirements()
    missing = sorted(
        module for module in _imported_modules()
        if _normalise(DISTRIBUTION_FOR_MODULE.get(module, module)) not in declared
    )
    assert not missing, f"imported but not in requirements.txt: {missing}"


def test_nothing_declared_is_unused():
    declared, _ = _requirements()
    used = {_normalise(DISTRIBUTION_FOR_MODULE.get(m, m)) for m in _imported_modules()}
    unused = sorted(declared - used - {_normalise(n) for n in RUNTIME_ONLY})
    assert not unused, f"declared in requirements.txt but never imported: {unused}"


def test_every_requirement_is_bounded_above():
    """An open-ended `flask` lets a redeploy pull in a breaking major release with no code change."""
    _, lines = _requirements()
    unbounded = [line for line in lines if "<" not in line]
    assert not unbounded, f"no upper bound: {unbounded}"


def test_test_tooling_is_not_a_runtime_dependency():
    declared, _ = _requirements()
    assert not declared & {"pytest", "ruff"}
    dev, _ = _requirements("requirements-dev.txt")
    assert {"pytest", "ruff"} <= dev


def test_parsing_writes_nothing_to_stdout(capsys):
    """The parser used to print() a line per question to the server's stdout."""
    from app.utils.parser import parse_quiz_text
    parse_quiz_text("Q?\nA) one\nB) two\nAnswer: A\n\nType: E\nExplain.")
    assert capsys.readouterr().out == ""
