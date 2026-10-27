"""Backup, blocklist and edit-candidate tools for the library rebuild."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from .identity import IDENTITY_FIELDS, item_key

_IGNORED = ("_source_", "_replaced_from", "_manual")
_CAP = 50


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    if r.returncode != 0:
        raise ValueError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def _git_show_json(repo: Path, rev_path: str) -> dict:
    r = subprocess.run(["git", "show", rev_path], cwd=repo, capture_output=True, text=True)
    if r.returncode != 0:
        return {}
    try:
        data = json.loads(r.stdout)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _count(path: Path) -> tuple[int, int]:
    files = [p for p in path.rglob("*") if p.is_file()]
    return len(files), sum(p.stat().st_size for p in files)


def backup_library(db_dir: Path, library_dir: Path, dest: Path, tag: str) -> None:
    """Copy both folders under ``dest`` and tag HEAD locally (never pushes)."""
    db_dir, library_dir, dest = Path(db_dir), Path(library_dir), Path(dest)
    if dest.exists():
        raise ValueError(f"backup destination already exists: {dest}")
    for p in (db_dir, library_dir):
        if not p.is_dir():
            raise ValueError(f"source folder is missing: {p}")
    repo = db_dir.resolve()
    existing = _git(repo, "tag", "--list", tag).split()
    if tag in existing:
        raise ValueError(f"git tag already exists: {tag}")
    dest.mkdir(parents=True)
    try:
        shutil.copytree(db_dir, dest / "library_db")
        shutil.copytree(library_dir, dest / "aig-library")
    except OSError as e:
        shutil.rmtree(dest, ignore_errors=True)
        raise ValueError(f"backup copy failed ({e}); the partial backup was removed") from e
    try:
        _git(repo, "tag", tag)
    except ValueError as e:
        raise ValueError(f"a complete backup was written to {dest}, but creating tag {tag} failed: {e}") from e


def has_uncommitted_changes(db_dir: Path) -> bool:
    r = subprocess.run(["git", "status", "--porcelain", "--", "."], cwd=Path(db_dir).resolve(),
                       capture_output=True, text=True)
    return r.returncode == 0 and bool(r.stdout.strip())


_REF_OK = re.compile(r"^[0-9A-Za-z._/~^@{}-]+$")


def resolve_commit(repo: Path, value: str) -> str:
    """Resolve ``value`` to a full commit SHA or raise ValueError."""
    if not value or value.startswith("-") or not _REF_OK.match(value):
        raise ValueError(f"not a valid commit reference: {value!r}")
    r = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"{value}^{{commit}}"], cwd=repo,
                       capture_output=True, text=True)
    sha = r.stdout.strip()
    if r.returncode != 0 or not sha:
        raise ValueError(f"commit {value!r} not found in this repository")
    return sha


def commit_has_parent(repo: Path, sha: str) -> bool:
    return subprocess.run(["git", "rev-parse", "--verify", "-q", f"{sha}^"], cwd=repo,
                          capture_output=True).returncode == 0


def load_audit(path: Path) -> list | None:
    """Audit entries, or None when the file is missing or invalid."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, list) else None


def backup_stats(dest: Path) -> tuple[int, int]:
    return _count(Path(dest))


def _entry(city: str, list_name: str, key: str) -> dict | None:
    if list_name not in IDENTITY_FIELDS or not key:
        return None
    return {"city": city, "list": list_name, "key": key}


def _shard_label(rel: str) -> str | None:
    """``library_db/X.json`` -> ``X``; ``library_db/_country/X.json`` -> ``_country/X``."""
    parts = Path(rel).parts
    if len(parts) == 2 and parts[0] == "library_db" and not parts[1].startswith("_"):
        return Path(parts[1]).stem
    if len(parts) == 3 and parts[:2] == ("library_db", "_country"):
        return "_country/" + Path(parts[2]).stem
    return None


def _changed_shards(repo: Path, commit: str) -> list[tuple[str, str]]:
    """(label, repo-relative path) for each shard changed in ``commit``."""
    sha = resolve_commit(repo, commit)
    out = _git(repo, "diff-tree", "-z", "--no-commit-id", "--name-only", "-r", "--root", sha)
    res = []
    for rel in sorted(set(x for x in out.split("\0") if x)):
        label = _shard_label(rel)
        if label:
            res.append((label, rel))
    return res


def build_blocklist(audit_path: Path, git_commit: str | None, repo: Path) -> list[dict]:
    seen: set[tuple] = set()
    result: list[dict] = []

    def add(city, list_name, key):
        e = _entry(city, list_name, key)
        if e and (e["city"], e["list"], e["key"]) not in seen:
            seen.add((e["city"], e["list"], e["key"]))
            result.append(e)

    sha = resolve_commit(repo, git_commit) if git_commit is not None else None
    entries = load_audit(audit_path)
    if entries is not None:
        for e in entries:
            if not isinstance(e, dict) or e.get("action") != "delete":
                continue
            cat, city = e.get("category"), e.get("city")
            if cat not in IDENTITY_FIELDS or not city:
                continue
            snap = e.get("item_snapshot")
            if isinstance(snap, dict) and snap:
                key = item_key(cat, snap)
            else:
                name = e.get("item_name")
                field = IDENTITY_FIELDS[cat][0][0]
                key = item_key(cat, {field: name}) if name else ""
            add(city, cat, key)

    if sha and commit_has_parent(repo, sha):
        for label, rel in _changed_shards(repo, sha):
            old = _git_show_json(repo, f"{sha}^:{rel}")
            new = _git_show_json(repo, f"{sha}:{rel}")
            for list_name, items in old.items():
                if list_name not in IDENTITY_FIELDS or not isinstance(items, list):
                    continue
                new_keys = {item_key(list_name, i) for i in new.get(list_name) or [] if isinstance(i, dict)}
                for item in items:
                    if isinstance(item, dict):
                        k = item_key(list_name, item)
                        if k and k not in new_keys:
                            add(label, list_name, k)
    return sorted(result, key=lambda e: (e["city"], e["list"], e["key"]))


def _content(item: dict) -> dict:
    return {k: v for k, v in item.items() if not k.startswith(_IGNORED)}


def _load_shard(db: Path, label: str) -> dict:
    p = Path(db) / (label + ".json")
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _all_labels(db: Path) -> list[str]:
    db = Path(db)
    labels = [p.stem for p in db.glob("*.json") if not p.name.startswith("_")]
    labels += ["_country/" + p.stem for p in (db / "_country").glob("*.json")]
    return sorted(labels)


def _index(shard: dict) -> dict[tuple, dict]:
    idx = {}
    for list_name, items in shard.items():
        if list_name not in IDENTITY_FIELDS or not isinstance(items, list):
            continue
        for it in items:
            if isinstance(it, dict):
                k = item_key(list_name, it)
                if k:
                    idx.setdefault((list_name, k), it)
    return idx


def _label_of(item: dict, list_name: str) -> str:
    return str(item.get("name") or item.get("item") or item.get("tip") or item.get("text")
               or item.get("english") or item.get("mode") or item_key(list_name, item))


def write_edit_candidates(old_db: Path, new_db: Path, git_commit: str | None, repo: Path, out: Path) -> None:
    candidates: set[str] = set()
    if git_commit is not None:
        sha = resolve_commit(repo, git_commit)
        candidates.update(label for label, _ in _changed_shards(repo, sha))
    # audit cities from the old library's audit log
    for e in load_audit(Path(old_db) / "_audit.json") or []:
        if isinstance(e, dict) and e.get("city"):
            candidates.add(str(e["city"]))

    lines = ["# Edit candidates", "",
             "Old items that are missing from, or differ in, the new library. "
             "Re-apply anything worth keeping through the UI.", ""]
    nothing = True
    for label in sorted(candidates):
        old, new = _index(_load_shard(old_db, label)), _index(_load_shard(new_db, label))
        rows = []
        for (lst, key), item in sorted(old.items()):
            if (lst, key) not in new:
                rows.append((lst, item, "missing in new library"))
            elif _content(item) != _content(new[(lst, key)]):
                rows.append((lst, item, "differs in new library"))
        if not rows:
            continue
        nothing = False
        lines += [f"## {label}", ""]
        for lst, item, why in rows:
            lines.append(f"- [{lst}] {_label_of(item, lst)} ({why})")
            lines.append("  ```json")
            lines.append("  " + json.dumps(_content(item), ensure_ascii=False, sort_keys=True))
            lines.append("  ```")
        lines.append("")
    if nothing:
        lines += ["No candidate cities have differing items.", ""]

    lines += ["## Old items without a provenance marker", "",
              "Lower confidence: most are probably old extraction output, not hand edits.", ""]
    any_unmarked = False
    for label in _all_labels(old_db):
        names = []
        for lst, items in sorted(_load_shard(old_db, label).items()):
            if lst not in IDENTITY_FIELDS or not isinstance(items, list):
                continue
            for it in items:
                if isinstance(it, dict) and item_key(lst, it) and not it.get("_source_file"):
                    names.append(f"[{lst}] {_label_of(it, lst)}")
        if not names:
            continue
        any_unmarked = True
        names.sort()
        lines += [f"### {label} ({len(names)})", ""]
        lines += [f"- {n}" for n in names[:_CAP]]
        if len(names) > _CAP:
            lines.append(f"- ... and {len(names) - _CAP} more")
        lines.append("")
    if not any_unmarked:
        lines += ["None.", ""]
    Path(out).write_text("\n".join(lines), encoding="utf-8")
