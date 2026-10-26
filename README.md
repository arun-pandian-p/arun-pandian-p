#!/usr/bin/env python3
"""Refreshes the auto-generated sections of README.md.

Sections are delimited by <!-- NAME:START --> and <!-- NAME:END --> markers.
Each section that fails is left as-is, so one API hiccup never breaks the README.
"""
import datetime
import os
import pathlib
import re

import requests
import yaml

USER = os.environ.get("GH_USER", "arun-pandian-p")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
ROOT = pathlib.Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
API = "https://api.github.com"

HEADERS = {"Accept": "application/vnd.github+json"}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"


def get(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()


def clean(text, limit=90):
    """Make text safe for a markdown table cell or list item."""
    text = (text or "").splitlines()[0] if text else ""
    text = text.replace("|", "/").replace("[", "(").replace("]", ")")
    return text[:limit]


# ---------- Pinned / recent projects ----------

def pinned_graphql():
    query = """
    query($login: String!) {
      user(login: $login) {
        pinnedItems(first: 6, types: REPOSITORY) {
          nodes {
            ... on Repository {
              name url description stargazerCount pushedAt
              primaryLanguage { name }
            }
          }
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
    return r.json()["data"]["user"]["pinnedItems"]["nodes"]


def project_rows():
    rows = []
    try:
        for n in pinned_graphql():
            rows.append({
                "name": n["name"], "url": n["url"], "desc": n["description"],
                "stars": n["stargazerCount"],
                "lang": (n["primaryLanguage"] or {}).get("name", "—"),
                "pushed": n["pushedAt"][:10],
            })
    except Exception as exc:  # GraphQL failure: fall back below
        print(f"pinned query failed: {exc}")

    if not rows:  # nothing pinned, or query failed: use latest pushed repos
        for r in get(f"{API}/users/{USER}/repos?sort=pushed&per_page=6"):
            rows.append({
                "name": r["name"], "url": r["html_url"], "desc": r["description"],
                "stars": r["stargazers_count"], "lang": r["language"] or "—",
                "pushed": r["pushed_at"][:10],
            })
    return rows


def projects_md():
    lines = ["| Project | What it is | Stack | ⭐ | Last push |", "|---|---|---|---|---|"]
    for r in project_rows():
        lines.append(
            f"| [**{r['name']}**]({r['url']}) | {clean(r['desc'])} | "
            f"{r['lang']} | {r['stars']} | {r['pushed']} |"
        )
    return "\n".join(lines)


# ---------- Recent commits ----------

def activity_md():
    events = get(f"{API}/users/{USER}/events/public?per_page=100")
    items = []
    for e in events:
        if e.get("type") != "PushEvent":
            continue
        repo = e["repo"]["name"]
        day = e["created_at"][:10]
        for c in e["payload"].get("commits", []):
            msg = clean(c["message"], 80)
            items.append(
                f"- `{day}` · [{repo}](https://github.com/{repo}) · "
                f"[{msg}](https://github.com/{repo}/commit/{c['sha']})"
            )
            if len(items) >= 8:
                break
        if len(items) >= 8:
            break
    return "\n".join(items) or "_No recent public commits yet._"


# ---------- Milestones (edited by hand in YAML) ----------

def milestones_md():
    path = ROOT / "profile" / "milestones.yml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
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
    pattern = re.compile(
        rf"(<!-- {name}:START -->)(.*?)(<!-- {name}:END -->)", re.S
    )
    if not pattern.search(text):
        print(f"marker {name} not found, skipping")
        return text
    return pattern.sub(
        lambda m: f"{m.group(1)}\n{content}\n{m.group(3)}", text, count=1
    )


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


if __name__ == "__main__":
    main()
