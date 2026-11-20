from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

import click
from loguru import logger
from omegaconf import OmegaConf

from codebase_analyzer.bots.manager import BotManager
from codebase_analyzer.control.loop import LoopManager


def calculate_path_hash(path: Path | str) -> str:
    """Calculate the hash256 of the given path."""

    # Resolve the absolute path and check if it exists
    path = Path(path).expanduser().resolve()
    logger.debug(f"For cache hash: {path=}")
    return hashlib.sha256(str(path).encode()).hexdigest()


def get_cache_root(repo_root: Path) -> Path:
    """Gets the cache root path for the given repo path."""
    # TODO: Make the cache root configurable
    return Path(__file__).parent.parent / ".cache" / calculate_path_hash(repo_root)


def remove_files_in_folder(p: Path) -> None:
    """Remove all files in folder p recursively."""
    for child in p.glob("*"):
        if child.is_file():
            child.unlink()
        else:
            shutil.rmtree(child)


def _path(
    path: Path | str,
    check_exist: bool = False,
    mkdir: bool = False,
    clean: bool = False,
) -> Path:
    p = Path(path).expanduser().resolve()
    if check_exist and not p.exists():
        raise ValueError(f"{p=} does not exist.")
    if mkdir and not p.exists():
        p.mkdir(parents=True)
    if clean and p.exists():
        remove_files_in_folder(p)
    logger.debug(f"{p=}")
    return p


def main(
    repo_root: Path,
    entry_point: Path,
    config_path: Path,
    cache_root: Path | None = None,
    clean_cache: bool = False,
    update_cache: bool = False,
    **kwargs: Any,
) -> None:
    """Codezoom - A cluster of coding bots
    Codebase Analyzer module
    """
    cache_root = cache_root or get_cache_root(repo_root)
    cache_root = _path(cache_root, mkdir=True, clean=clean_cache)
    repo_root = _path(repo_root, check_exist=True)
    config_path = _path(config_path, check_exist=True)
    entry_point = _path(entry_point, check_exist=True)

    # TODO: Add schema validation for config
    config = OmegaConf.load(config_path)

    # Singleton manager
    loop_manager = LoopManager()
    bot_manager = BotManager.from_repo(
        repo_root=repo_root,
        cache_root=cache_root,
        entry_point=entry_point,
        update_cache=update_cache,
        loop=loop_manager,
        config=config.manager,
        **kwargs,
    )

    # TODO: We may want a separate master bot to have more flexibility
    # TODO: Currently if the root_bot only have one child, the performance is bad.
    loop_manager.interaction_loop(bot_manager.repo_bot)


@click.command()
@click.option(
    "--repo-root",
    "-r",
    type=Path,
    required=True,
    help="Path to the root of the repository to analyze.",
)
@click.option(
    "--entry-point",
    "-e",
    type=Path,
    required=True,
    # TODO: Detect the entry_point automatically
    help="Relative or absoluate path to the entry_point file in the repository. ",
)
@click.option(
    "--cache-root",
    "-cache",
    type=Path,
    help="Path to the root cache repo. Will cacluate based on sha256 of repo root if not assigned",
)
@click.option(
    "--config-path",
    "-config",
    type=Path,
    help="Path to the config yaml file. See example at `/config.yaml.example`",
)
@click.option(
    "--clean-cache",
    "-u",
    type=bool,
    default=False,
    help="Whether to clean the cache before running.",
)
@click.option(
    "--update-cache",
    "-u",
    type=bool,
    default=False,
    help="In case existing cache is provided, whether to update it or use whatever cache found.",
)
def cli(
    repo_root: Path,
    entry_point: Path,
    cache_root: Path,
    config_path: Path,
    clean_cache: bool,
    update_cache: bool,
) -> None:
    """Codebase Analyzer CLI."""
    main(
        repo_root=repo_root,
        cache_root=cache_root,
        entry_point=entry_point,
        config_path=config_path,
        clean_cache=clean_cache,
        update_cache=update_cache,
    )


## TODO: Make the following a test
# repo_root = Path("/Users/jun/Projects/ChatGPT/src/only_v1").resolve()
# entry_point = Path("/Users/jun/Projects//ChatGPT/src/only_v1/V1.py").resolve()
# cache_root = Path("shared_cache/ChatGPT_V1/").resolve()
# config_path = Path("config.yaml").resolve()
# main(
#     repo_root=repo_root,
#     entry_point=entry_point,
#     cache_root=cache_root,
#     update_cache=False,
#     config_path=config_path,
# )

if __name__ == "__main__":
    cli()
