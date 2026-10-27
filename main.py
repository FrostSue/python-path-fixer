"""
Main entry point and CLI handler for Windows Python PATH Fixer.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional

from path_manager import PathManager, PathScope
from utils import (
    PythonInstallation,
    detect_python_installations,
    get_default_python_installation,
    validate_python_directory,
)


def setup_logger(verbose: bool) -> logging.Logger:
    """Configure and return the root logger for the application."""
    log_level = logging.DEBUG if verbose else logging.INFO
    logger = logging.getLogger("python_path_fixer")
    logger.setLevel(log_level)

    if not logger.handlers:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(log_level)
        formatter = logging.Formatter(
            fmt="%(levelname)s: %(message)s" if not verbose else "[%(levelname)s] [%(name)s] %(message)s"
        )
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger


def parse_arguments(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments using argparse."""
    parser = argparse.ArgumentParser(
        prog="python-path-fixer",
        description="Automatically detect Windows Python installations and permanently configure PATH variables.",
    )

    parser.add_argument(
        "--scope",
        choices=["user", "system", "both"],
        default="user",
        help="Target environment scope for PATH modification (default: user).",
    )
    parser.add_argument(
        "--python-path",
        type=str,
        default=None,
        help="Manually specify a target Python directory or executable to add.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate the operations and display changes without modifying the registry.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force adding directories even if already detected in PATH.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable detailed debug logging output.",
    )
    parser.add_argument(
        "-l",
        "--list",
        action="store_true",
        help="Discover and display all detected Python installations and exit.",
    )
    parser.add_argument(
        "--elevate",
        action="store_true",
        help="Automatically request UAC elevation if system scope modification is requested.",
    )
    parser.add_argument(
        "--no-scripts",
        action="store_true",
        help="Do not include the Python Scripts directory in the PATH update.",
    )

    return parser.parse_args(argv)


def handle_list_command(logger: logging.Logger, manager: PathManager) -> int:
    """List all detected Python installations with their current PATH status."""
    logger.info("Scanning system for Python installations...")
    installations = detect_python_installations()

    if not installations:
        logger.warning("No Python installations detected on this system.")
        return 0

    logger.info("Discovered %d Python installation(s):\n", len(installations))

    for idx, inst in enumerate(installations, start=1):
        is_user_root = manager.is_directory_in_path(inst.install_dir, PathScope.USER)
        is_user_scripts = manager.is_directory_in_path(inst.scripts_dir, PathScope.USER)
        is_system_root = manager.is_directory_in_path(inst.install_dir, PathScope.SYSTEM)
        is_system_scripts = manager.is_directory_in_path(inst.scripts_dir, PathScope.SYSTEM)

        current_marker = " [CURRENT RUNTIME]" if inst.is_current else ""
        print(f"[{idx}] Python {inst.version}{current_marker}")
        print(f"    Source:          {inst.source}")
        print(f"    Executable:      {inst.executable_path}")
        print(f"    Installation:    {inst.install_dir}")
        print(f"    Scripts:         {inst.scripts_dir} (Exists: {inst.scripts_dir.is_dir()})")
        print(f"    User PATH:       Root: {'[YES]' if is_user_root else '[NO]'} | Scripts: {'[YES]' if is_user_scripts else '[NO]'}")
        print(f"    System PATH:     Root: {'[YES]' if is_system_root else '[NO]'} | Scripts: {'[YES]' if is_system_scripts else '[NO]'}")
        print()

    return 0


def resolve_target_installation(
    manual_path: Optional[str],
    logger: logging.Logger,
) -> Optional[PythonInstallation]:
    """Resolve target installation via manual path or auto-discovery."""
    if manual_path:
        logger.info("Validating specified Python path: %s", manual_path)
        inst = validate_python_directory(manual_path, "Manual Specification")
        if not inst:
            logger.error("Invalid Python path specified: %s", manual_path)
            return None
        return inst

    logger.info("Auto-detecting Python installations...")
    discovered = detect_python_installations()
    if not discovered:
        logger.error("Unable to locate any valid Python installation.")
        return None

    selected = get_default_python_installation(discovered)
    if not selected:
        selected = discovered[0]

    logger.info(
        "Selected Python installation: %s (v%s, %s)",
        selected.install_dir,
        selected.version,
        selected.source,
    )
    return selected


def main(argv: Optional[List[str]] = None) -> int:
    """Execute the CLI workflow and return standard exit code."""
    args = parse_arguments(argv)
    logger = setup_logger(args.verbose)
    manager = PathManager()

    if args.list:
        return handle_list_command(logger, manager)

    target_scope = PathScope(args.scope)
    requires_admin = target_scope in (PathScope.SYSTEM, PathScope.BOTH)

    if requires_admin and not manager.is_elevated():
        if args.elevate:
            logger.info("Elevation requested. Spawning elevated process with UAC prompt...")
            pass_args = [arg for arg in sys.argv[1:] if arg != "--elevate"]
            success = manager.request_elevation(pass_args)
            if success:
                logger.info("Elevated process spawned successfully.")
                return 0
            logger.error("Failed to spawn elevated process via UAC.")
            return 2

        logger.error(
            "Modifying System PATH requires Administrator privileges. "
            "Please run your terminal as Administrator, use '--elevate', or target '--scope user'."
        )
        return 2

    target_installation = resolve_target_installation(args.python_path, logger)
    if not target_installation:
        return 3

    directories_to_add: List[Path] = [target_installation.install_dir]
    if not args.no_scripts:
        directories_to_add.append(target_installation.scripts_dir)

    logger.debug("Directories designated for PATH update: %s", directories_to_add)

    if args.dry_run:
        logger.info("[DRY RUN MODE] Simulating PATH environment modifications...")

    try:
        results = manager.apply_path_updates(
            directories=directories_to_add,
            scope=target_scope,
            dry_run=args.dry_run,
            force=args.force,
        )
    except PermissionError as perm_err:
        logger.error("Permission error encountered: %s", perm_err)
        return 2
    except Exception as exc:
        logger.exception("Unexpected error occurred while updating PATH: %s", exc)
        return 1

    all_already_present = True
    any_modified = False

    for item in results:
        scope_name = item["scope"].upper()
        added = item.get("added", [])
        already_present = item.get("already_present", [])
        modified = item.get("modified", False)

        if modified:
            any_modified = True
            all_already_present = False
            action_verb = "Would add" if args.dry_run else "Successfully added"
            logger.info("[%s PATH] %s %d directory(ies):", scope_name, action_verb, len(added))
            for p in added:
                logger.info("  + %s", p)

        if already_present:
            logger.info("[%s PATH] %d directory(ies) already present:", scope_name, len(already_present))
            for p in already_present:
                logger.info("  = %s", p)

    if not any_modified and all_already_present:
        logger.info("All target directories are already present in PATH. No changes needed.")
    elif not args.dry_run and any_modified:
        logger.info("Environment variable changes have been permanently saved and broadcasted to Windows.")
        logger.info("New terminal windows will immediately recognize 'python' and 'pip' commands.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
