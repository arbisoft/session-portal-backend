#!/usr/bin/env python3
"""Deterministic drift audit for the Claude Code configuration in `.claude/`.

Run from anywhere: `python3 .claude/scripts/audit_config.py` (add `--json` for machine output).
Stdlib only. Exit code 1 when any ERROR is found, 0 otherwise (WARN does not fail).

Checks (facts only; judgement calls stay with `config-maintainer-agent`):
  frontmatter   agents/skills/commands carry the fields their loader needs; names match file/dir names
  references    backticked repo paths, `.claude/...` files, skill and agent names all resolve
  toolchain     version and limit claims (Django, Python, pylint limits) match requirements/tox/pylintrc
  symbols       backticked classes, functions and settings cited in docs still exist in the code
  coverage      first-party modules that no config or doc file mentions by name
  commands      `tox -e X` envs and `manage.py X` commands named in docs exist
  rules-index   `.claude/rules/README.md` lists every rules file
  rule-scope    `paths:` globs in rule frontmatter match at least one file
  duplication   long identical lines repeated across config files
  size          always-loaded files (CLAUDE.md) stay inside the instruction budget
"""
import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CLAUDE_DIR = REPO / ".claude"
ALWAYS_LOADED = [REPO / "CLAUDE.md"]
ALWAYS_LOADED_MAX_LINES = 150
DUPLICATE_MIN_CHARS = 60
DUPLICATE_SIMILARITY = 0.4
PATH_ROOTS = (".claude/", "events/", "users/", "arbisoft_sessions_portal/", "requirements/", ".github/")
ROOT_DOCS = ("README.md", "CLAUDE.md", "DATABASE_DESIGN.md", "UPLOADS.md", "pylintrc", "tox.ini", "pytest.ini")
BUILTIN_SLASH = {"init", "help", "clear", "compact", "model", "config", "review", "fast", "mcp", "agents", "memory"}

EXTERNAL_SYMBOLS = {
    "APIClient", "APIView", "AppConfig", "CheckConstraint", "FileSystemStorage", "FilterSet",
    "GenericAPIView", "IsAuthenticated", "ListAPIView", "CreateAPIView", "ListCreateAPIView", "ModelForm",
    "ModelAdmin", "QuerySet", "RunPython", "SerializerMethodField", "TokenObtainPairView", "UploadedFile",
    "DO_NOTHING", "MEDIA_ROOT", "MEDIA_URL", "DEBUG", "ALLOWED_HOSTS", "INSTALLED_APPS", "MIGRATION_MODULES",
    "DJANGO_SETTINGS_MODULE", "DATABASES", "LOGGING", "FUTURE", "STDLIB", "THIRDPARTY", "DJANGO", "FIRSTPARTY",
    "LOCALFOLDER", "BLOCKER", "SUGGESTION", "NITPICK",
    "NOT", "NULL", "FIFO", "OPTIONS", "HEAD", "GET", "POST", "PATCH", "PUT", "DELETE", "ERROR", "WARN",
    "StreamingHttpResponse", "FileResponse", "Prefetch", "TrigramSimilarity",
    "SimpleJWT", "CorsMiddleware", "DjangoFilterBackend", "AssertionError", "DoesNotExist", "PostgreSQL",
    "JavaScript", "TypeScript", "GitHub", "FleetView", "ReportFindings", "PyCharm", "CodeQL", "OpenAPI",
    "get_object_or_404", "select_related", "prefetch_related", "bulk_create", "bulk_update", "PascalCase",
    "AddIndexConcurrently", "CreateExtension", "WebFetch", "OverheadCost", "SerializerMethodFields",
}

findings = []


def report(level, check, where, message):
    findings.append({"level": level, "check": check, "where": where, "message": message})


def rel(path):
    return str(path.relative_to(REPO))


def config_files():
    return sorted(p for p in CLAUDE_DIR.rglob("*.md") if "scripts" not in p.parts)


def read_frontmatter(path):
    text = path.read_text(encoding="utf-8")
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if not match:
        return None
    fields = {}
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and not line.startswith(" "):
            fields[key.strip()] = value.strip().strip('"')
    return fields


def agent_names():
    return {p.stem for p in (CLAUDE_DIR / "agents").glob("*.md")}


def skill_names():
    return {p.parent.name for p in (CLAUDE_DIR / "skills").glob("*/SKILL.md")}


def command_names():
    return {p.stem for p in (CLAUDE_DIR / "commands").glob("*.md")}


def check_frontmatter():
    for path in sorted((CLAUDE_DIR / "agents").glob("*.md")):
        fields = read_frontmatter(path)
        if fields is None:
            report("ERROR", "frontmatter", rel(path), "missing YAML frontmatter")
            continue
        for key in ("name", "description", "tools", "model"):
            if not fields.get(key):
                report("ERROR", "frontmatter", rel(path), f"agent missing `{key}`")
        if fields.get("name") and fields["name"] != path.stem:
            report("ERROR", "frontmatter", rel(path), f"name `{fields['name']}` != filename `{path.stem}`")
    for path in sorted((CLAUDE_DIR / "skills").glob("*/SKILL.md")):
        fields = read_frontmatter(path)
        if fields is None:
            report("ERROR", "frontmatter", rel(path), "missing YAML frontmatter")
            continue
        for key in ("name", "description"):
            if not fields.get(key):
                report("ERROR", "frontmatter", rel(path), f"skill missing `{key}`")
        if fields.get("name") and fields["name"] != path.parent.name:
            report("ERROR", "frontmatter", rel(path), f"name `{fields['name']}` != dir `{path.parent.name}`")
    for path in sorted((CLAUDE_DIR / "commands").glob("*.md")):
        fields = read_frontmatter(path)
        if not fields or not fields.get("description"):
            report("ERROR", "frontmatter", rel(path), "command missing `description`")


def backticked(text):
    return re.findall(r"`([^`\n]+)`", text)


def path_candidates(token):
    token = token.strip().rstrip(",.;:)")
    token = re.sub(r":\d+(-\d+)?$", "", token)
    if any(ch in token for ch in "<>*{}$|=") or " " in token or token.startswith(("http", "-", "/")):
        return None
    if token.startswith(PATH_ROOTS) or token in ROOT_DOCS:
        return token
    return None


def check_references():
    agents, skills, commands = agent_names(), skill_names(), command_names()
    for path in config_files():
        text = path.read_text(encoding="utf-8")
        for token in backticked(text):
            candidate = path_candidates(token)
            if candidate and not (REPO / candidate).exists():
                report("ERROR", "references", rel(path), f"path does not exist: `{candidate}`")
            if re.fullmatch(r"[a-z]+(-[a-z]+)*-agent", token) and token not in agents:
                report("ERROR", "references", rel(path), f"agent does not exist: `{token}`")
            if re.fullmatch(r"/[a-z][a-z-]+", token) and token[1:] not in commands | skills | BUILTIN_SLASH:
                report("WARN", "references", rel(path), f"slash command `{token}` has no command or skill")
        for name in re.findall(r"`([a-z]+(?:-[a-z]+)+)` skill", text):
            if name not in skills:
                report("ERROR", "references", rel(path), f"skill does not exist: `{name}`")
        for name in re.findall(r"\*\*`?([a-z]+(?:-[a-z]+)+)`?\*\* skill", text):
            if name not in skills:
                report("ERROR", "references", rel(path), f"skill does not exist: `{name}`")


def pinned_version(package):
    for line in (REPO / "requirements" / "base.txt").read_text(encoding="utf-8").splitlines():
        if line.lower().startswith(package.lower() + "=="):
            return line.split("==")[1].strip()
    return None


def pylintrc_values():
    values = {}
    for line in (REPO / "pylintrc").read_text(encoding="utf-8").splitlines():
        match = re.match(r"^(max-[a-z-]+|min-[a-z-]+)\s*=\s*(\d+)\s*$", line)
        if match:
            values[match.group(1)] = int(match.group(2))
    return values


def check_toolchain():
    django = pinned_version("Django")
    django_minor = ".".join(django.split(".")[:2]) if django else None
    dockerfile = (REPO / "Dockerfile").read_text(encoding="utf-8")
    python_match = re.search(r"FROM python:(\d+\.\d+)", dockerfile)
    python_minor = python_match.group(1) if python_match else None
    limits = pylintrc_values()
    docs = config_files() + [REPO / "CLAUDE.md", REPO / "README.md"]
    for path in docs:
        text = path.read_text(encoding="utf-8")
        for found in set(re.findall(r"Django (\d+\.\d+)", text)):
            if django_minor and found != django_minor:
                report("ERROR", "toolchain", rel(path), f"says Django {found}, requirements pin {django}")
        for found in set(re.findall(r"Python (\d+\.\d+)", text)):
            if python_minor and found != python_minor:
                report("ERROR", "toolchain", rel(path), f"says Python {found}, Dockerfile uses {python_minor}")
        for key, claimed in re.findall(r"`?(max-[a-z]+|min-[a-z-]+)`?\s*=\s*(\d+)", text):
            if key in limits and limits[key] != int(claimed):
                report("ERROR", "toolchain", rel(path), f"{key} = {claimed}, pylintrc has {limits[key]}")
        if re.search(r"max-line-length\D+(\d+)", text):
            claimed = int(re.search(r"max-line-length\D+(\d+)", text).group(1))
            if claimed != 120:
                report("ERROR", "toolchain", rel(path), f"line length {claimed}, tooling uses 120")


def repo_source_text():
    """Concatenated text of first-party source and config files (everything except .claude, tests data, logs)."""
    suffixes = {".py", ".ini", ".yml", ".yaml", ".txt", ".example", ".cfg", ".sh", ".md"}
    skip_dirs = {".git", ".claude", ".tox", "__pycache__", "media", ".pytest_cache", "node_modules", "migrations"}
    chunks = []
    for path in REPO.rglob("*"):
        if path.is_file() and path.suffix in suffixes and not skip_dirs & set(path.relative_to(REPO).parts):
            if path.name in {"CLAUDE.md"}:
                continue
            chunks.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(chunks)


def check_symbols():
    """Warn on class, constant and function names cited in config that no first-party file mentions.

    Third-party names (Django, DRF, Celery, ORM methods) are listed in EXTERNAL_SYMBOLS once reviewed.
    """
    corpus = repo_source_text()
    shapes = re.compile(r"[A-Z][a-z0-9]+(?:[A-Z][A-Za-z0-9]*)+|[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+|[a-z]+(?:_[a-z0-9]+)+\(\)")
    for path in config_files() + [REPO / "CLAUDE.md"]:
        reported = set()
        for token in backticked(path.read_text(encoding="utf-8")):
            base = re.sub(r"\(\)$", "", token.split(".")[0])
            if not shapes.fullmatch(token.split(".")[0]) or base in EXTERNAL_SYMBOLS or base in reported:
                continue
            if not re.search(rf"\b{re.escape(base)}\b", corpus):
                reported.add(base)
                report("WARN", "symbols", rel(path), f"`{base}` appears nowhere in first-party source or config")


def check_coverage():
    """Warn when a source module (not tests, migrations, __init__) is never named in config or docs."""
    corpus = "\n".join(p.read_text(encoding="utf-8") for p in config_files())
    corpus += "\n".join((REPO / name).read_text(encoding="utf-8") for name in ("CLAUDE.md", "README.md"))
    for app in ("events", "users", "arbisoft_sessions_portal"):
        for source in sorted((REPO / app).rglob("*.py")):
            parts = set(source.relative_to(REPO).parts)
            if parts & {"migrations", "tests", "__pycache__"} or source.name in {"__init__.py", "apps.py"}:
                continue
            camel = "".join(word.title() for word in source.stem.split("_"))
            if not any(label in corpus for label in (source.name, source.stem, camel)):
                report("WARN", "coverage", rel(source), "module is not named in CLAUDE.md, README.md or .claude/")


def tox_envs():
    text = (REPO / "tox.ini").read_text(encoding="utf-8")
    return set(re.findall(r"^\[testenv:([^\]]+)\]", text, re.M))


def management_commands():
    names = set()
    for app in ("events", "users"):
        folder = REPO / app / "management" / "commands"
        if folder.exists():
            names |= {p.stem for p in folder.glob("*.py") if p.stem != "__init__"}
    return names


def check_commands():
    envs, commands = tox_envs(), management_commands()
    builtin = {"migrate", "makemigrations", "runserver", "check", "shell", "test", "showmigrations", "sqlmigrate",
               "createsuperuser", "collectstatic", "spectacular", "dbshell", "diffsettings", "loaddata", "dumpdata"}
    docs = config_files() + [REPO / "CLAUDE.md", REPO / "README.md"]
    for path in docs:
        text = path.read_text(encoding="utf-8")
        for env in re.findall(r"tox -e ([a-z0-9-]+)", text):
            if env not in envs:
                report("ERROR", "commands", rel(path), f"`tox -e {env}` is not defined in tox.ini")
        for name in re.findall(r"manage\.py ([a-z_]+)", text):
            if name not in commands and name not in builtin:
                report("ERROR", "commands", rel(path), f"`manage.py {name}` is not a known command")


def rule_paths(path):
    match = re.match(r"---\n(.*?)\n---\n", path.read_text(encoding="utf-8"), re.S)
    if not match or "paths:" not in match.group(1):
        return None
    return re.findall(r"^\s*-\s*[\"']?([^\"'\n]+?)[\"']?\s*$", match.group(1), re.M)


def check_rule_scopes():
    """A path-scoped rule whose globs match nothing never loads: that is silent drift."""
    for path in sorted((CLAUDE_DIR / "rules").glob("*.md")):
        for pattern in rule_paths(path) or []:
            if not any(REPO.glob(pattern)):
                report("ERROR", "rule-scope", rel(path), f"paths glob matches no file: {pattern}")


def check_rules_index():
    index = (CLAUDE_DIR / "rules" / "README.md").read_text(encoding="utf-8")
    for path in sorted((CLAUDE_DIR / "rules").glob("*.md")):
        if path.name != "README.md" and f"`{path.name}`" not in index:
            report("ERROR", "rules-index", rel(path), "not listed in .claude/rules/README.md")
    for name in re.findall(r"^\|\s*`([a-z-]+\.md)`", index, re.M):
        if not (CLAUDE_DIR / "rules" / name).exists():
            report("ERROR", "rules-index", "rules/README.md", f"lists missing file `{name}`")


def shingles(text, size=3):
    words = re.findall(r"[a-z0-9_]+", text.lower())
    return {" ".join(words[i:i + size]) for i in range(max(len(words) - size + 1, 1))}


def instruction_lines(path):
    """Prose bullets worth comparing: outside code fences/tables, long enough to carry a rule.

    Pointer lines (naming a `.claude/` file) and lines marked `<!-- audit:keep -->` are intentional repeats."""
    in_fence = False
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        text = line.strip().lstrip("-*0123456789. ").strip()
        is_pointer = ".claude/skills/" in text or ".claude/rules/" in text or "audit:keep" in text
        if not in_fence and not is_pointer and not line.lstrip().startswith(("|", "#")) and len(text) >= DUPLICATE_MIN_CHARS:
            yield number, text


def check_duplication():
    """Flag near-identical instructions that live in two different files (Jaccard on word trigrams)."""
    entries = []
    for path in config_files() + [REPO / "CLAUDE.md"]:
        entries.extend((rel(path), number, text, shingles(text)) for number, text in instruction_lines(path))
    for index, (file_a, line_a, text_a, grams_a) in enumerate(entries):
        for file_b, line_b, _, grams_b in entries[index + 1:]:
            if file_a == file_b:
                continue
            overlap = len(grams_a & grams_b) / len(grams_a | grams_b)
            if overlap >= DUPLICATE_SIMILARITY:
                report("WARN", "duplication", f"{file_a}:{line_a} ~ {file_b}:{line_b}",
                       f"{overlap:.0%} similar: {text_a[:70]}...")


def check_size():
    for path in ALWAYS_LOADED:
        lines = len(path.read_text(encoding="utf-8").splitlines())
        if lines > ALWAYS_LOADED_MAX_LINES:
            report("WARN", "size", rel(path), f"{lines} lines (> {ALWAYS_LOADED_MAX_LINES}); move detail to rules/")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="emit findings as JSON")
    args = parser.parse_args()
    for check in (check_frontmatter, check_references, check_toolchain, check_symbols, check_coverage, check_commands,
                  check_rules_index, check_rule_scopes, check_duplication, check_size):
        check()
    errors = [f for f in findings if f["level"] == "ERROR"]
    if args.json:
        print(json.dumps(findings, indent=2))
    elif not findings:
        print("audit_config: clean")
    else:
        for item in sorted(findings, key=lambda f: (f["level"], f["check"], f["where"])):
            print(f"[{item['level']}] {item['check']:<11} {item['where']} — {item['message']}")
        print(f"\n{len(errors)} error(s), {len(findings) - len(errors)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
