#!/usr/bin/env python3
"""Update language and tool badges in the profile README files."""

from __future__ import annotations

import base64
import json
import os
import re
import time
from fnmatch import fnmatchcase
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / ".github" / "stack.json"
README_PATHS = [ROOT / "README.md", ROOT / "README-ru.md"]
API_ROOT = "https://api.github.com"
BADGE_BACKGROUND = "0B0E14"
TOOLS_ACCENT = "95E6CB"
STATIC_BADGE_TARGET = "#profile-badges"

LANGUAGE_META = {
    "Kotlin": ("D2A6FF", "kotlin"),
    "JavaScript": ("E6B450", "javascript"),
    "TypeScript": ("59C2FF", "typescript"),
    "Rust": ("FF8F40", "rust"),
    "Python": ("95E6CB", "python"),
    "Java": ("F07178", "openjdk"),
    "C++": ("5CCFE6", "cplusplus"),
    "C": ("B3B1AD", "c"),
    "HTML": ("FF8F40", "html5"),
    "CSS": ("59C2FF", "css3"),
    "SQL": ("AAD94C", "mysql"),
    "Shell": ("95E6CB", "gnubash"),
}


def request_json(url: str, token: str | None = None) -> object:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "MoonFoxy-profile-readme",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    for attempt in range(3):
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            if error.code not in {429, 500, 502, 503, 504} or attempt == 2:
                raise
        except URLError:
            if attempt == 2:
                raise
        time.sleep(2**attempt)
    raise RuntimeError("GitHub API retry loop ended unexpectedly")


def list_repositories(username: str, token: str | None, include_archived: bool, include_forks: bool) -> list[dict]:
    repositories: list[dict] = []
    page = 1
    while True:
        if os.getenv("GH_PAT"):
            url = f"{API_ROOT}/user/repos?visibility=all&affiliation=owner&per_page=100&page={page}"
        else:
            url = f"{API_ROOT}/users/{quote(username)}/repos?type=all&per_page=100&page={page}"
        page_items = request_json(url, token)
        if not isinstance(page_items, list):
            raise RuntimeError("GitHub returned an unexpected repository list")
        repositories.extend(page_items)
        if len(page_items) < 100:
            break
        page += 1

    return [
        repo for repo in repositories
        if repo.get("owner", {}).get("login", "").casefold() == username.casefold()
        and (include_archived or not repo.get("archived", False))
        and (include_forks or not repo.get("fork", False))
    ]


def language_totals(repositories: list[dict], token: str | None, excluded: set[str]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for repository in repositories:
        full_name = repository.get("full_name")
        if not full_name:
            continue
        languages = request_json(f"{API_ROOT}/repos/{full_name}/languages", token)
        if not isinstance(languages, dict):
            continue
        for language, bytes_count in languages.items():
            if language.casefold() not in excluded:
                totals[language] = totals.get(language, 0) + int(bytes_count)
    return totals


def repository_evidence(repository: dict, token: str | None) -> tuple[set[str], str]:
    full_name = repository.get("full_name")
    default_branch = repository.get("default_branch")
    if not full_name or not default_branch:
        raise RuntimeError("Repository metadata is missing a name or default branch")

    tree = request_json(
        f"{API_ROOT}/repos/{full_name}/git/trees/{quote(str(default_branch), safe='')}?recursive=1",
        token,
    )
    if not isinstance(tree, dict) or not isinstance(tree.get("tree"), list):
        raise RuntimeError(f"GitHub returned an unexpected tree for {full_name}")
    if tree.get("truncated"):
        raise RuntimeError(f"GitHub truncated the repository tree for {full_name}")

    paths: set[str] = set()
    build_files: list[dict] = []
    for item in tree["tree"]:
        path = str(item.get("path", ""))
        if not path:
            continue
        paths.add(path)
        if item.get("type") != "blob" or int(item.get("size") or 0) > 262_144:
            continue
        name = path.rsplit("/", 1)[-1]
        is_gradle_file = name in {
            "build.gradle",
            "build.gradle.kts",
            "settings.gradle",
            "settings.gradle.kts",
            "libs.versions.toml",
            "gradle.properties",
        }
        is_convention_plugin = (
            path.startswith(("buildSrc/", "build-logic/"))
            and path.endswith((".kt", ".kts", ".gradle"))
        )
        if is_gradle_file or is_convention_plugin:
            build_files.append(item)

    contents: list[str] = []
    for item in build_files:
        blob_url = item.get("url")
        if not blob_url:
            continue
        blob = request_json(str(blob_url), token)
        if not isinstance(blob, dict) or blob.get("encoding") != "base64":
            raise RuntimeError(f"GitHub returned an unexpected blob for {full_name}/{item.get('path', '')}")
        encoded = str(blob.get("content", ""))
        contents.append(base64.b64decode(encoded).decode("utf-8", errors="ignore").casefold())
    return paths, "\n".join(contents)


def detect_tools(
    repositories: list[dict],
    token: str | None,
    tools: list[dict],
    minimum_repositories: int,
    max_badges: int,
) -> list[dict]:
    hits = {str(tool["name"]): 0 for tool in tools}
    for repository in repositories:
        paths, contents = repository_evidence(repository, token)
        for tool in tools:
            detection = tool.get("detect", {})
            path_patterns = [str(pattern) for pattern in detection.get("paths", [])]
            content_patterns = [str(pattern).casefold() for pattern in detection.get("content", [])]
            path_match = any(
                fnmatchcase(path, pattern)
                for path in paths
                for pattern in path_patterns
            )
            content_match = any(pattern in contents for pattern in content_patterns)
            if path_match or content_match:
                hits[str(tool["name"])] += 1

    visible = [
        tool
        for tool in tools
        if bool(tool.get("always", False))
        or hits[str(tool["name"])] >= int(tool.get("minimum_repositories", minimum_repositories))
    ]
    return visible[:max_badges]


def badge_url(name: str, message: str | None, accent: str, logo: str | None = None) -> str:
    label = quote(name.replace(" ", "_"), safe="")
    if message is None:
        url = f"https://img.shields.io/badge/{label}-{BADGE_BACKGROUND}?style=flat-square"
    else:
        encoded_message = quote(message, safe="")
        url = f"https://img.shields.io/badge/{label}-{encoded_message}-{BADGE_BACKGROUND}?style=flat-square"
    url += f"&labelColor={BADGE_BACKGROUND}"
    if logo:
        url += f"&logo={quote(logo, safe='')}&logoColor={accent}"
    return url


def render_languages(totals: dict[str, int], minimum_percent: float, max_badges: int, russian: bool) -> str:
    total = sum(totals.values())
    ranked = sorted(totals.items(), key=lambda item: item[1], reverse=True)
    visible = [(name, size) for name, size in ranked if size / total * 100 >= minimum_percent]
    if not visible and ranked:
        visible = ranked[:1]
    visible = visible[:max_badges]

    badges = []
    for name, size in visible:
        percent = f"{size / total * 100:.1f}%"
        accent, logo = LANGUAGE_META.get(name, ("B3B1AD", None))
        badges.append(
            f'  <a href="{STATIC_BADGE_TARGET}"><img src="{badge_url(name, percent, accent, logo)}" alt="{name} {percent}"></a>'
        )

    if russian:
        note = f"Обновляется раз в неделю. Языки ниже {minimum_percent:g}% скрываются."
    else:
        note = f"Updated weekly. Languages below {minimum_percent:g}% are hidden."
    return "\n".join([
        "<p>",
        *badges,
        "</p>",
        f"<sub>{note}</sub>",
    ])


def render_tools(tools: list[dict]) -> str:
    badges = []
    for tool in tools:
        name = str(tool["name"])
        badges.append(
            f'  <a href="{STATIC_BADGE_TARGET}"><img src="{badge_url(name, None, str(tool.get("accent", TOOLS_ACCENT)), tool.get("logo"))}" alt="{name}"></a>'
        )
    return "\n".join(["<p>", *badges, "</p>"])


def replace_block(text: str, marker: str, replacement: str) -> str:
    pattern = rf"<!-- {marker}:START -->.*?<!-- {marker}:END -->"
    result, count = re.subn(pattern, f"<!-- {marker}:START -->\n{replacement}\n<!-- {marker}:END -->", text, flags=re.DOTALL)
    if count != 1:
        raise RuntimeError(f"Expected one {marker} marker pair")
    return result


def main() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    username = str(config["github_username"])
    token = os.getenv("GH_PAT") or os.getenv("GITHUB_TOKEN")
    excluded_repositories = {value.casefold() for value in config.get("excluded_repositories", [])}
    excluded_languages = {value.casefold() for value in config.get("excluded_languages", [])}

    repositories = [
        repo for repo in list_repositories(
            username,
            token,
            bool(config.get("include_archived", True)),
            bool(config.get("include_forks", False)),
        )
        if repo.get("full_name", "").casefold() not in excluded_repositories
    ]
    if not repositories:
        raise RuntimeError("No repositories found; add a GH_PAT secret for private repositories")

    totals = language_totals(repositories, token, excluded_languages)
    if not totals:
        raise RuntimeError("No language statistics returned by GitHub")

    minimum_percent = float(config.get("minimum_language_percent", 2.0))
    max_badges = int(config.get("max_language_badges", 8))
    detected_tools = detect_tools(
        repositories,
        token,
        config["tools"],
        int(config.get("minimum_tool_repositories", 1)),
        int(config.get("max_tool_badges", 16)),
    )
    if not detected_tools:
        raise RuntimeError("No tools were detected in the selected repositories")
    for readme_path in README_PATHS:
        is_russian = readme_path.name == "README-ru.md"
        text = readme_path.read_text(encoding="utf-8")
        text = replace_block(text, "STACK:LANGUAGES", render_languages(totals, minimum_percent, max_badges, is_russian))
        text = replace_block(text, "STACK:TOOLS", render_tools(detected_tools))
        readme_path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except (HTTPError, URLError) as error:
        raise SystemExit(f"GitHub API request failed: {error}") from error
