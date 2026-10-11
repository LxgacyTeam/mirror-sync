
from pathlib import Path

README_FILES = (
    "README.md",
    "README_RU.md",
    "README_ZH.md",
)

BASE = "https://github.com/LxgacyTeam/LegacyUIFramework/wiki/"

SPECIAL_REPLACEMENTS = {
    "BigCityLegacy": {
        "*": {
            "https://github.com/BepInEx/BepInEx":
                "https://codeberg.org/LxgacyTeam/"
                "bepinex5-releases-mirror",
        },
    },

    "LegacyUIFramework": {
        "README.md": {
            BASE + "Documentation-on-English":
                "https://codeberg.org/LxgacyTeam/"
                "LegacyUIFramework/wiki/%5BEN%5D-Documentation",
        },

        "README_RU.md": {
            BASE + (
                "%D0%94%D0%BE%D0%BA%D1%83%D0%BC%D0%B5%D0%BD"
                "%D1%82%D0%B0%D1%86%D0%B8%D1%8F-%D0%BD%D0%B0-"
                "%D0%A0%D1%83%D1%81%D1%81%D0%BA%D0%BE%D0%BC"
            ):
                "https://codeberg.org/LxgacyTeam/"
                "LegacyUIFramework/wiki/%5BRU%5D-"
                "%D0%94%D0%BE%D0%BA%D1%83%D0%BC%D0%B5%D0%BD"
                "%D1%82%D0%B0%D1%86%D0%B8%D1%8F",
        },
    },
}


def adapt_readmes(repo_name: str, repo_dir: Path) -> list[str]:
    changed_files = []

    rules = SPECIAL_REPLACEMENTS.get(repo_name, {})

    for filename in README_FILES:
        path = repo_dir / filename

        if not path.is_file():
            continue

        original = path.read_text(encoding="utf-8")
        updated = original

        replacements = {
            **rules.get("*", {}),
            **rules.get(filename, {}),
        }

        for old, new in sorted(
            replacements.items(),
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            updated = updated.replace(old, new)

        updated = updated.replace(
            "github.com",
            "codeberg.org",
        )

        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changed_files.append(filename)

    return changed_files
