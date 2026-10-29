"""Optional local models; disabling a pack also stops serving its file endpoints."""

from dataclasses import replace
from pathlib import Path

from eidolon.characters import Character


def mount_models(
    characters: dict[str, Character], root: Path | None, *, enabled: bool
) -> dict[str, Character]:
    mounted = {}
    for key, character in characters.items():
        directory = root / key if root is not None else character.stand_model
        if not enabled:
            character = replace(character, stand_model=None, default_outfit=None)
        elif directory is not None:
            if (directory / "model.json").is_file() and (
                directory / "animations.json"
            ).is_file():
                outfit = character.default_outfit
                if outfit is None or not outfit.startswith("stand_3d/"):
                    outfit = f"stand_3d/{key}-default"
                character = replace(
                    character, stand_model=directory.resolve(), default_outfit=outfit
                )
            else:
                character = replace(character, stand_model=None, default_outfit=None)
        mounted[key] = character
    return mounted
