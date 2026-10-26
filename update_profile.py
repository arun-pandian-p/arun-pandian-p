#!/usr/bin/env python3
"""Refreshes the auto-generated sections of README.md.

Each section is delimited by <!-- NAME:START --> and <!-- NAME:END -->.
A failing section keeps its old content, so one API error never breaks the README.
"""
import datetime
import os
import pathlib
import re
import sys

import requests
import yaml

USER = os.environ.get("GH_USER", "arun-pandian-p")
TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
ROOT = pathlib.Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
MILESTONES = ROOT / "profile" / "milestones.yml"
API = "https://api.github.com"

HEADERS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "profile-readme-bot",
}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"


def get(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def clean(text, limit=90):
    """Make a string safe inside a markdown table cell or list item."""
    if not text:
        return ""
    first = str(text).strip().splitlines()[0] if str(text).strip() else ""
    first = first.replace("|", "/").replace("[", "(").replace("]", ")")
    return first[:limit]


# ---------- Projects ----------

def pinned_repos():
    """Pinned repos via GraphQL (needs a token). Returns [] if unavailable."""
    if not TOKEN:
        return []
    query = """
    query($login: String!) {
      user(login: $login) {
        pinnedItems(first: 6, types: REPOSITORY) {
          nodes { ... on Repository {
            name url description stargazerCount pushedAt
            primaryLanguage { name }
          } }
        }
      }
    }"""
    r = requests.post(
        f"{API}/graphql",
        json={"query": query, "variables": {"login": USER}},
        headers=HEADERS,
        timeout=30,
    )
    r.raise_for_status()
    body = r.json()
    if body.get("errors"):
        raise RuntimeError(body["errors"][0].get("message", "graphql error"))
    nodes = (body.get("data") or {}).get("user", {}) or {}
    return (nodes.get("pinnedItems") or {}).get("nodes") or []


def project_rows():
    rows = []
    try:
        for n in pinned_repos():
            rows.append({
                "name": n["name"],
                "url": n["url"],
                "desc": n.get("description"),
                "stars": n.get("stargazerCount", 0),
                "lang": (n.get("primaryLanguage") or {}).get("name") or "—",
                "pushed": (n.get("pushedAt") or "")[:10],
            })
    except Exception as exc:
        print(f"pinned lookup failed, using recent repos: {exc}")

    if not rows:
        repos = get(f"{API}/users/{USER}/repos?sort=pushed&per_page=6&type=owner")
        for r in repos:
            if r.get("fork"):
                continue
            rows.append({
                "name": r["name"],
                "url": r["html_url"],
                "desc": r.get("description"),
                "stars": r.get("stargazers_count", 0),
                "lang": r.get("language") or "—",
                "pushed": (r.get("pushed_at") or "")[:10],
            })
    return rows[:6]


def projects_md():
    rows = project_rows()
    if not rows:
        return "_No public projects found._"
    lines = ["| Project | What it is | Stack | ⭐ | Last push |", "|---|---|---|---|---|"]
    for r in rows:
        lines.append(
            f"| [**{clean(r['name'], 40)}**]({r['url']}) | "
            f"{clean(r['desc']) or '—'} | {clean(r['lang'], 30)} | "
            f"{r['stars']} | {r['pushed'] or '—'} |"
        )
    return "\n".join(lines)


# ---------- Recent commits ----------

def activity_md():
    events = get(f"{API}/users/{USER}/events/public?per_page=100")
    items = []
    for e in events:
        if e.get("type") != "PushEvent":
            continue
        repo = e.get("repo", {}).get("name", "")
        day = (e.get("created_at") or "")[:10]
        for c in e.get("payload", {}).get("commits", []):
            msg = clean(c.get("message"), 80) or "(no message)"
            sha = c.get("sha", "")
            items.append(
                f"- `{day}` · [{repo}](https://github.com/{repo}) · "
                f"[{msg}](https://github.com/{repo}/commit/{sha})"
            )
            if len(items) >= 8:
                return "\n".join(items)
    return "\n".join(items) or "_No recent public commits yet._"


# ---------- Milestones ----------

def milestones_md():
    if not MILESTONES.exists():
        return "_No milestones file yet._"
    data = yaml.safe_load(MILESTONES.read_text(encoding="utf-8")) or []
    data = [m for m in data if isinstance(m, dict) and m.get("title")]
    data.sort(key=lambda m: str(m.get("date", "")), reverse=True)
    lines = []
    for m in data[:6]:
        lines.append(
            f"- {m.get('icon', '🏁')} **{m['title']}** · `{m.get('date', '')}`  \n"
            f"  {m.get('detail', '')}"
        )
    return "\n".join(lines) or "_No milestones yet._"


# ---------- Marker replacement ----------

def replace(text, name, content):
    pattern = re.compile(rf"(<!-- {name}:START -->)(.*?)(<!-- {name}:END -->)", re.S)
    if not pattern.search(text):
        print(f"marker {name} not found, skipping")
        return text
    # lambda avoids backslash escapes in content being interpreted
    return pattern.sub(lambda m: f"{m.group(1)}\n{content}\n{m.group(3)}", text, count=1)


def safe(fn, fallback):
    try:
        return fn()
    except Exception as exc:
        print(f"{fn.__name__} failed: {exc}")
        return fallback


def main():
    text = README.read_text(encoding="utf-8")
    now = datetime.datetime.now(datetime.timezone.utc)

    text = replace(text, "PINNED", safe(projects_md, "_Projects unavailable right now._"))
    text = replace(text, "ACTIVITY", safe(activity_md, "_Activity unavailable right now._"))
    text = replace(text, "MILESTONES", safe(milestones_md, "_Milestones unavailable right now._"))
    text = replace(text, "UPDATED", f"<sub>_{now:%d %b %Y, %H:%M} UTC_</sub>")

    README.write_text(text, encoding="utf-8")
    print("README refreshed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
