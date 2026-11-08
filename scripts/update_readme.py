#!/usr/bin/env python3
"""Auto-updates README sections: PINNED, ACTIVITY, MILESTONES, and UPDATED timestamp.
"""

import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
README_FILE = BASE_DIR / "README.md"
CONFIG_FILE = BASE_DIR / "config" / "projects.json"
MILESTONES_FILE = BASE_DIR / "profile" / "milestones.yml"

TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
API = "https://api.github.com"

HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "GitHub-Profile-Automation",
    "X-GitHub-Api-Version": "2022-11-28",
}
if TOKEN:
    HEADERS["Authorization"] = f"Bearer {TOKEN}"


def github_get(endpoint):
    request = urllib.request.Request(API + endpoint, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def clean(value, limit=120):
    if not value:
        return ""
    text = str(value).replace("|", "\\|").replace("\n", " ").strip()
    return text[:limit]


def replace_section(content, start, end, new_content):
    start_marker = f"<!-- {start} -->"
    end_marker = f"<!-- {end} -->"
    if start_marker not in content or end_marker not in content:
        print(f"Notice: Missing README markers {start} / {end}, skipping.")
        return content
    before, remaining = content.split(start_marker, 1)
    _, after = remaining.split(end_marker, 1)
    return before + start_marker + "\n" + new_content.strip() + "\n" + end_marker + after


def fetch_selected_commits(projects, limit):
    commits = []
    for repo in projects:
        try:
            data = github_get(f"/repos/{repo}/commits?per_page=1")
            if not data or not isinstance(data, list):
                continue
            commit = data[0]
            details = commit.get("commit", {})
            committer_info = details.get("committer") or details.get("author") or {}
            commit_date = committer_info.get("date", "")

            commits.append({
                "repo": repo,
                "message": details.get("message", "").split("\n")[0],
                "sha": commit.get("sha", "")[:7],
                "url": commit.get("html_url", ""),
                "date": commit_date,
            })
        except Exception as error:
            print(f"Warning: Could not fetch commits for {repo}: {error}")

    commits.sort(key=lambda item: item["date"], reverse=True)
    return commits[:limit]


def generate_activity(commits):
    if not commits:
        return "_No recent public commits found._"
    rows = []
    for item in commits:
        repo_name = item["repo"].split("/")[-1]
        commit_date = item["date"][:10] if len(item["date"]) >= 10 else "Recently"
        rows.append(
            f"- **[{clean(repo_name)}](https://github.com/{item['repo']})** "
            f"— [{clean(item['message'], 90)}]({item['url']}) "
            f"· `{item['sha']}` "
            f"· {commit_date}"
        )
    return "\n".join(rows)


def fetch_repositories(username, limit):
    repos = github_get(f"/users/{username}/repos?type=owner&sort=pushed&per_page=100")
    if not isinstance(repos, list):
        return []
    valid_repos = [repo for repo in repos if not repo.get("fork") and not repo.get("archived")]
    return valid_repos[:limit]


def generate_repository_table(repos):
    rows = [
        "| Project | What it is | Stack | ⭐ | Last push |",
        "|---|---|---|---|---|",
    ]
    for repo in repos:
        name = clean(repo.get("name"))
        description = clean(repo.get("description")) or "—"
        language = clean(repo.get("language")) or "—"
        stars = repo.get("stargazers_count", 0)
        pushed = repo.get("pushed_at", "")[:10] if repo.get("pushed_at") else "—"
        rows.append(
            f"| [**{name}**]({repo.get('html_url')}) | {description} | {language} | {stars} | {pushed} |"
        )
    return "\n".join(rows)


def load_milestones():
    if not MILESTONES_FILE.exists():
        return ""
    try:
        import yaml
        data = yaml.safe_load(MILESTONES_FILE.read_text(encoding="utf-8")) or []
    except Exception:
        # Fallback manual parser if pyyaml is not installed
        content = MILESTONES_FILE.read_text(encoding="utf-8")
        entries = content.split("- date:")
        data = []
        for entry in entries[1:]:
            date_m = re.search(r'["\'](.*?)["\']', entry)
            title_m = re.search(r'title:\s*["\']?(.*?)["\']?\n', entry)
            detail_m = re.search(r'detail:\s*["\']?(.*?)["\']?\n', entry)
            icon_m = re.search(r'icon:\s*["\']?(.*?)["\']?\n', entry)
            if title_m:
                data.append({
                    "date": date_m.group(1) if date_m else "",
                    "title": title_m.group(1) if title_m else "",
                    "detail": detail_m.group(1) if detail_m else "",
                    "icon": icon_m.group(1) if icon_m else "🎯",
                })

    data = [m for m in data if isinstance(m, dict) and m.get("title")]
    data.sort(key=lambda m: str(m.get("date", "")), reverse=True)

    lines = []
    for m in data[:6]:
        icon = m.get("icon", "🎯")
        lines.append(
            f"- {icon} **{m['title']}** · `{m.get('date', '')}`  \n"
            f"  {m.get('detail', '')}"
        )
    return "\n".join(lines)


def main():
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_FILE}")

    with open(CONFIG_FILE, "r", encoding="utf-8") as file:
        config = json.load(file)

    username = config.get("username", "arun-pandian-p")
    projects = config.get("featured_projects", [])

    with open(README_FILE, "r", encoding="utf-8") as file:
        readme = file.read()

    # 1. Update selected project commits
    commits = fetch_selected_commits(projects, config.get("recent_activity_limit", 10))
    activity = generate_activity(commits)
    readme = replace_section(readme, "ACTIVITY:START", "ACTIVITY:END", activity)

    # 2. Update public repository table
    repos = fetch_repositories(username, config.get("repository_limit", 10))
    repository_table = generate_repository_table(repos)
    readme = replace_section(readme, "PINNED:START", "PINNED:END", repository_table)

    # 3. Update milestones if present
    milestones = load_milestones()
    if milestones:
        readme = replace_section(readme, "MILESTONES:START", "MILESTONES:END", milestones)

    # 4. Update timestamp
    timestamp = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    readme = replace_section(
        readme,
        "UPDATED:START",
        "UPDATED:END",
        f"<sub>_Last refreshed: {timestamp}_</sub>",
    )

    with open(README_FILE, "w", encoding="utf-8") as file:
        file.write(readme)

    print("GitHub profile README updated successfully!")
    print(f"Selected projects checked: {len(projects)}")
    print(f"Recent commits found: {len(commits)}")
    print(f"Repositories displayed: {len(repos)}")


if __name__ == "__main__":
    main()
