#!/usr/bin/env python3
"""Generate localized, theme-aware terminal GIFs for the profile README."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = ROOT / ".github" / "profile.json"
ASCII_ART_PATH = ROOT / ".github" / "assets" / "sailor-moon-cat.txt"
FONT_PATH = ROOT / ".github" / "assets" / "fonts" / "JetBrainsMono-Variable.ttf"
ASSETS_PATH = ROOT / ".github" / "assets"
FRAMES_ROOT = ASSETS_PATH / "neofetch_frames"

WIDTH = 720
HEIGHT = 500
FPS = 15
FONT_SIZE = 13
ART_FONT_SIZE = 8
TYPING_FRAMES = 2
LINE_REVEAL_FRAMES = 7
ART_PAUSE_FRAMES = 18
CURSOR_PHASE_FRAMES = 5
CURSOR_BLINK_CYCLES = 3
FINAL_PAUSE_FRAMES = 45


THEMES = {
    "dark": {
        "background": "#0B0E14",
        "foreground": "#B3B1AD",
        "muted": "#3B4352",
        "red": "#F07178",
        "green": "#AAD94C",
        "yellow": "#E6B450",
        "blue": "#59C2FF",
        "magenta": "#D2A6FF",
        "cyan": "#95E6CB",
        "header_text": "#0B0E14",
    },
    "light": {
        "background": "#FAFAFA",
        "foreground": "#5C6166",
        "muted": "#ABB0B6",
        "red": "#F07171",
        "green": "#86B300",
        "yellow": "#F2AE49",
        "blue": "#399EE6",
        "magenta": "#A37ACC",
        "cyan": "#4CBF99",
        "header_text": "#FAFAFA",
    },
}


TEXT = {
    "en": {
        "github": "GitHub",
        "study": "Study",
        "focus": "Focus",
        "age": "Age",
        "born": "born April 2003",
        "contact": "Contact:",
        "discord": "Discord",
        "telegram": "Telegram",
        "email": "Email",
        "stats": "GitHub Stats:",
        "commits": "Commits",
        "stars": "Stars",
        "prs": "Pull requests",
        "merged": "merged",
        "languages": "Languages",
        "unavailable": "temporarily unavailable",
        "role": "Android Developer",
        "footer": "# WELCOME, [Valued Customer]!! ENJOY YOUR [Free Visit]!!",
    },
    "ru": {
        "github": "GitHub",
        "study": "Учёба",
        "focus": "Профиль",
        "age": "Возраст",
        "born": "апрель 2003",
        "contact": "Контакты:",
        "discord": "Discord",
        "telegram": "Telegram",
        "email": "Почта",
        "stats": "GitHub статистика:",
        "commits": "Коммиты",
        "stars": "Звёзды",
        "prs": "Pull requests",
        "merged": "объединено",
        "languages": "Языки",
        "unavailable": "временно недоступно",
        "role": "Android-разработчик",
        "footer": "# ДОБРО ПОЖАЛОВАТЬ, [Ценный клиент]!! ВИЗИТ [Бесплатно]!!",
    },
}


@dataclass(frozen=True)
class Variant:
    language: str
    theme: str

    @property
    def output_path(self) -> Path:
        return ASSETS_PATH / f"neofetch-{self.language}-{self.theme}.gif"

    @property
    def frame_path(self) -> Path:
        return FRAMES_ROOT / f"{self.language}-{self.theme}"


class FrameWriter:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.index = 0
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)

    def append(self, image: Image.Image, count: int = 1) -> None:
        for _ in range(count):
            self.index += 1
            image.save(self.path / f"frame_{self.index:04d}.png", "PNG")


def load_font(size: int) -> ImageFont.FreeTypeFont:
    if not FONT_PATH.exists():
        raise FileNotFoundError(f"JetBrains Mono is missing: {FONT_PATH}")
    return ImageFont.truetype(
        str(FONT_PATH),
        size,
        layout_engine=ImageFont.Layout.BASIC,
    )


def current_age(birth_year: int, birth_month: int) -> int:
    today = date.today()
    return today.year - birth_year - (today.month < birth_month)


def russian_age(age: int) -> str:
    if 11 <= age % 100 <= 14:
        suffix = "лет"
    elif age % 10 == 1:
        suffix = "год"
    elif 2 <= age % 10 <= 4:
        suffix = "года"
    else:
        suffix = "лет"
    return f"{age} {suffix}"


def github_request(query: str, variables: dict, token: str) -> dict:
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    request = Request(
        "https://api.github.com/graphql",
        data=payload,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "MoonFoxy-profile-readme",
        },
    )
    with urlopen(request, timeout=30) as response:
        result = json.loads(response.read().decode("utf-8"))
    if result.get("errors"):
        raise RuntimeError(f"GitHub GraphQL error: {result['errors']}")
    return result["data"]


def fetch_github_stats(username: str) -> dict | None:
    token = os.getenv("GITHUB_TOKEN") or os.getenv("PROFILE_README_TOKEN")
    if not token:
        print("INFO: No GitHub token; generating GIFs without live statistics.")
        return None

    query = """
    query ProfileStats($login: String!, $after: String) {
      user(login: $login) {
        contributionsCollection {
          totalCommitContributions
          restrictedContributionsCount
        }
        pullRequests(first: 1) { totalCount }
        mergedPullRequests: pullRequests(states: MERGED, first: 1) { totalCount }
        repositories(
          first: 100
          after: $after
          ownerAffiliations: OWNER
          orderBy: { field: STARGAZERS, direction: DESC }
        ) {
          nodes {
            name
            isFork
            stargazerCount
            languages(first: 10, orderBy: { field: SIZE, direction: DESC }) {
              edges { size node { name } }
            }
          }
          pageInfo { hasNextPage endCursor }
        }
      }
    }
    """

    stars = 0
    language_sizes: dict[str, int] = {}
    cursor = None
    user_data = None
    try:
        while True:
            data = github_request(query, {"login": username, "after": cursor}, token)
            user_data = data.get("user")
            if not user_data:
                raise RuntimeError(f"GitHub user not found: {username}")
            repositories = user_data["repositories"]
            for repository in repositories["nodes"]:
                if repository["name"].casefold() == username.casefold():
                    continue
                stars += int(repository["stargazerCount"])
                if repository["isFork"]:
                    continue
                for language in repository["languages"]["edges"]:
                    name = language["node"]["name"]
                    language_sizes[name] = language_sizes.get(name, 0) + int(language["size"])
            if not repositories["pageInfo"]["hasNextPage"]:
                break
            cursor = repositories["pageInfo"]["endCursor"]
    except (HTTPError, URLError, TimeoutError, RuntimeError, ValueError) as error:
        print(f"WARNING: GitHub statistics unavailable: {error}")
        return None

    contributions = user_data["contributionsCollection"]
    languages = [name for name, _ in sorted(language_sizes.items(), key=lambda item: item[1], reverse=True)[:5]]
    return {
        "commits": int(contributions["totalCommitContributions"]) + int(contributions["restrictedContributionsCount"]),
        "stars": stars,
        "pull_requests": int(user_data["pullRequests"]["totalCount"]),
        "merged_pull_requests": int(user_data["mergedPullRequests"]["totalCount"]),
        "languages": languages,
    }


def draw_segments(
    image: Image.Image,
    font: ImageFont.FreeTypeFont,
    x: float,
    y: float,
    segments: list[tuple[str, str]],
) -> float:
    draw = ImageDraw.Draw(image)
    for text, color in segments:
        draw.text((round(x), round(y)), text, fill=color, font=font)
        x += draw.textlength(text, font=font)
    return x


def draw_label_value(
    image: Image.Image,
    font: ImageFont.FreeTypeFont,
    theme: dict,
    x: int,
    y: int,
    label: str,
    value: str,
    value_color: str,
) -> None:
    label_text = f"{label}:"
    draw_segments(
        image,
        font,
        x,
        y,
        [(label_text, theme["cyan"]), ("  ", theme["foreground"]), (value, value_color)],
    )


def draw_highlight(
    image: Image.Image,
    font: ImageFont.FreeTypeFont,
    theme: dict,
    x: int,
    y: int,
    text: str,
) -> None:
    draw = ImageDraw.Draw(image)
    bbox = draw.textbbox((x, y), text, font=font)
    draw.rectangle((bbox[0] - 2, bbox[1] - 1, bbox[2] + 2, bbox[3] + 1), fill=theme["red"])
    draw.text((x, y), text, fill=theme["header_text"], font=font)


def type_text(
    image: Image.Image,
    writer: FrameWriter,
    font: ImageFont.FreeTypeFont,
    theme: dict,
    x: float,
    y: int,
    text: str,
    color: str,
) -> float:
    draw = ImageDraw.Draw(image)
    for character in text:
        draw.text((round(x), y), character, fill=color, font=font)
        x += draw.textlength(character, font=font)
        cursor_frame = image.copy()
        ImageDraw.Draw(cursor_frame).text((round(x), y), "_", fill=theme["foreground"], font=font)
        writer.append(cursor_frame)
        writer.append(image, max(1, TYPING_FRAMES - 1))
    return x


def parse_ascii_art() -> list[list[tuple[str, str]]]:
    lines = ASCII_ART_PATH.read_text(encoding="utf-8").splitlines()
    parsed: list[list[tuple[str, str]]] = []
    for source_line in lines:
        if source_line.startswith("(set_colors"):
            continue
        line = source_line.replace("\u2800", " ")
        color = "c1"
        segments: list[tuple[str, str]] = []
        cursor = 0
        while cursor < len(line):
            marker_positions = [(line.find("${c1}", cursor), "c1"), (line.find("${c2}", cursor), "c2")]
            marker_positions = [(position, name) for position, name in marker_positions if position >= 0]
            if not marker_positions:
                segments.append((line[cursor:], color))
                break
            position, next_color = min(marker_positions)
            if position > cursor:
                segments.append((line[cursor:position], color))
            color = next_color
            cursor = position + 5
        parsed.append(segments)
    return parsed


def validate_art_characters(art: list[list[tuple[str, str]]]) -> None:
    characters = {character for line in art for text, _ in line for character in text if not character.isspace()}
    unexpected = sorted(character for character in characters if not 0x2800 <= ord(character) <= 0x28FF)
    if unexpected:
        raise RuntimeError(f"ASCII art contains unsupported characters: {''.join(unexpected)}")


def draw_ascii_art(
    image: Image.Image,
    font: ImageFont.FreeTypeFont,
    theme: dict,
    art: list[list[tuple[str, str]]],
    x: int = 16,
    y: int = 66,
) -> None:
    draw = ImageDraw.Draw(image)
    ascent, descent = font.getmetrics()
    line_height = ascent + descent
    cell_width = round(draw.textlength(" ", font=font))
    dot_size = max(1, round(cell_width * 0.4))
    dot_columns = (0, cell_width - dot_size)
    dot_rows = tuple(round(row * (line_height - dot_size) / 3) for row in range(4))
    dot_positions = (
        (0, 0),
        (0, 1),
        (0, 2),
        (1, 0),
        (1, 1),
        (1, 2),
        (0, 3),
        (1, 3),
    )
    for row, segments in enumerate(art):
        current_x = float(x)
        for text, color_name in segments:
            color = theme["foreground"] if color_name == "c1" else theme["yellow"]
            for character in text:
                if character != " ":
                    pattern = ord(character) - 0x2800
                    for bit, (column, dot_row) in enumerate(dot_positions):
                        if pattern & (1 << bit):
                            left = round(current_x) + dot_columns[column]
                            top = y + row * line_height + dot_rows[dot_row]
                            draw.rectangle(
                                (left, top, left + dot_size - 1, top + dot_size - 1),
                                fill=color,
                            )
                current_x += cell_width


def profile_lines(language: str, profile: dict, age: int) -> list[tuple[str, str, str]]:
    labels = TEXT[language]
    age_text = f"{age} years" if language == "en" else russian_age(age)
    return [
        (labels["github"], f"github.com/{profile['nickname']}", "magenta"),
        (labels["study"], profile["education"][language], "yellow"),
        (labels["focus"], f"{labels['role']} · Kotlin · Jetpack Compose", "blue"),
        (labels["age"], f"{age_text} · {labels['born']}", "yellow"),
    ]


def contact_lines(language: str, profile: dict) -> list[tuple[str, str, str]]:
    labels = TEXT[language]
    contacts = profile["contacts"]
    return [
        (labels["discord"], contacts["discord"], "magenta"),
        (labels["telegram"], contacts["telegram"], "magenta"),
        (labels["email"], contacts["email"], "magenta"),
    ]


def stats_lines(language: str, stats: dict | None) -> list[tuple[str, str, str]]:
    labels = TEXT[language]
    if stats is None:
        return [("", labels["unavailable"], "red")]
    languages = ", ".join(stats["languages"]) or "Kotlin"
    if len(languages) > 34:
        languages = f"{languages[:33].rstrip(', ')}…"
    return [
        (f"{labels['commits']} ({date.today().year})", str(stats["commits"]), "green"),
        (labels["stars"], str(stats["stars"]), "green"),
        (labels["prs"], f"{stats['pull_requests']} · {stats['merged_pull_requests']} {labels['merged']}", "green"),
        (labels["languages"], languages, "red"),
    ]


def draw_revealed_lines(
    image: Image.Image,
    writer: FrameWriter,
    font: ImageFont.FreeTypeFont,
    theme: dict,
    lines: list[tuple[str, str, str]],
    x: int,
    y: int,
    line_height: int = 19,
) -> int:
    for label, value, color_name in lines:
        if label:
            draw_label_value(image, font, theme, x, y, label, value, theme[color_name])
        else:
            ImageDraw.Draw(image).text((x, y), value, fill=theme[color_name], font=font)
        writer.append(image, LINE_REVEAL_FRAMES)
        y += line_height
    return y


def assemble_gif(frame_path: Path, output_path: Path) -> None:
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-framerate",
        str(FPS),
        "-start_number",
        "1",
        "-i",
        str(frame_path / "frame_%04d.png"),
        "-filter_complex",
        "[0:v]split[a][b];[a]palettegen[p];[b][p]paletteuse=dither=sierra2_4a",
        "-loop",
        "0",
        str(output_path),
    ]
    subprocess.run(command, check=True)


def render_variant(variant: Variant, profile: dict, stats: dict | None) -> int:
    theme = THEMES[variant.theme]
    labels = TEXT[variant.language]
    font = load_font(FONT_SIZE)
    art_font = load_font(ART_FONT_SIZE)
    art = parse_ascii_art()
    validate_art_characters(art)

    image = Image.new("RGB", (WIDTH, HEIGHT), theme["background"])
    writer = FrameWriter(variant.frame_path)
    age = current_age(int(profile["birth_year"]), int(profile["birth_month"]))

    prompt_end = draw_segments(
        image,
        font,
        10,
        10,
        [
            (profile["nickname"], theme["red"]),
            ("@github", theme["yellow"]),
            (" ~> ", theme["foreground"]),
        ],
    )
    writer.append(image, 4)
    type_text(image, writer, font, theme, prompt_end, 10, f"fetch.sh -u {profile['nickname']}", theme["cyan"])

    draw_ascii_art(image, art_font, theme, art)
    writer.append(image, ART_PAUSE_FRAMES)

    right_x = 260
    draw_highlight(image, font, theme, right_x, 50, f"{profile['nickname']}@GitHub")
    writer.append(image, LINE_REVEAL_FRAMES)
    ImageDraw.Draw(image).text((right_x, 69), "-" * 22, fill=theme["muted"], font=font)
    writer.append(image, 3)
    draw_revealed_lines(image, writer, font, theme, profile_lines(variant.language, profile, age), right_x, 86)

    draw_highlight(image, font, theme, right_x, 190, labels["contact"])
    writer.append(image, LINE_REVEAL_FRAMES)
    ImageDraw.Draw(image).text((right_x, 209), "-" * 18, fill=theme["muted"], font=font)
    writer.append(image, 3)
    draw_revealed_lines(image, writer, font, theme, contact_lines(variant.language, profile), right_x, 226)

    draw_highlight(image, font, theme, right_x, 302, labels["stats"])
    writer.append(image, LINE_REVEAL_FRAMES)
    ImageDraw.Draw(image).text((right_x, 321), "-" * 18, fill=theme["muted"], font=font)
    writer.append(image, 3)
    draw_revealed_lines(image, writer, font, theme, stats_lines(variant.language, stats), right_x, 338)

    footer_y = 468
    footer_prompt_end = draw_segments(
        image,
        font,
        10,
        footer_y,
        [
            (profile["nickname"], theme["red"]),
            ("@github", theme["yellow"]),
            (" ~> ", theme["foreground"]),
        ],
    )
    writer.append(image, 4)
    cursor_x = type_text(
        image,
        writer,
        font,
        theme,
        footer_prompt_end,
        footer_y,
        labels["footer"],
        theme["green"],
    )

    for _ in range(CURSOR_BLINK_CYCLES):
        cursor_frame = image.copy()
        ImageDraw.Draw(cursor_frame).text((round(cursor_x), footer_y), "_", fill=theme["foreground"], font=font)
        writer.append(cursor_frame, CURSOR_PHASE_FRAMES)
        writer.append(image, CURSOR_PHASE_FRAMES)
    writer.append(image, FINAL_PAUSE_FRAMES)

    try:
        assemble_gif(variant.frame_path, variant.output_path)
    finally:
        shutil.rmtree(variant.frame_path, ignore_errors=True)
    print(f"Generated {variant.output_path.name}: {writer.index} frames")
    return writer.index


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="Generate every language/theme combination")
    parser.add_argument("--language", choices=("en", "ru"))
    parser.add_argument("--theme", choices=("dark", "light"))
    args = parser.parse_args()
    if args.all and (args.language or args.theme):
        parser.error("--all cannot be combined with --language or --theme")
    if not args.all and not (args.language and args.theme):
        parser.error("use --all or provide both --language and --theme")
    return args


def main() -> None:
    args = parse_args()
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    stats = fetch_github_stats(str(profile["nickname"]))
    variants = (
        [Variant(language, theme) for language in ("en", "ru") for theme in ("dark", "light")]
        if args.all
        else [Variant(args.language, args.theme)]
    )
    for variant in variants:
        render_variant(variant, profile, stats)
    if FRAMES_ROOT.exists() and not any(FRAMES_ROOT.iterdir()):
        FRAMES_ROOT.rmdir()


if __name__ == "__main__":
    main()
