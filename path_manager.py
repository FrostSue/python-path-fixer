"""
Environment variable and Windows Registry management module.
"""

from __future__ import annotations

import ctypes
import os
import sys
import winreg
from ctypes import wintypes
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from utils import normalize_path, paths_equal


class PathScope(str, Enum):
    """Execution scopes for environment variable modifications."""

    USER = "user"
    SYSTEM = "system"
    BOTH = "both"


class PathManager:
    """Manages reading, verifying, modifying, and broadcasting Windows PATH variables."""

    USER_SUBKEY = r"Environment"
    SYSTEM_SUBKEY = r"System\CurrentControlSet\Control\Session Manager\Environment"

    @staticmethod
    def is_elevated() -> bool:
        """Check whether current process has Windows Administrator privileges."""
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin() != 0)
        except Exception:
            return False

    @staticmethod
    def request_elevation(cli_arguments: Optional[List[str]] = None) -> bool:
        """Prompt Windows UAC to elevate the current script with administrative rights."""
        try:
            script_path = os.path.abspath(sys.argv[0])
            arguments_to_pass = cli_arguments if cli_arguments is not None else sys.argv[1:]
            escaped_arguments = " ".join(
                f'"{item}"' if " " in item else item for item in arguments_to_pass
            )
            full_params = f'"{script_path}" {escaped_arguments}'.strip()

            instance_handle = ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                sys.executable,
                full_params,
                None,
                1,
            )
            return instance_handle > 32
        except Exception:
            return False

    @staticmethod
    def broadcast_environment_change() -> bool:
        """Broadcast WM_SETTINGCHANGE message so Windows processes reload environment variables."""
        try:
            broadcast_recipient = 0xFFFF
            wm_settingchange = 0x001A
            smto_abortifhung = 0x0002
            timeout_duration = 5000
            result_code = wintypes.DWORD()

            send_status = ctypes.windll.user32.SendMessageTimeoutW(
                broadcast_recipient,
                wm_settingchange,
                0,
                "Environment",
                smto_abortifhung,
                timeout_duration,
                ctypes.byref(result_code),
            )
            return bool(send_status != 0)
        except Exception:
            return False

    def _get_registry_location(self, scope: PathScope) -> Tuple[int, str]:
        """Resolve the Windows registry root key and subkey for the specified scope."""
        if scope == PathScope.USER:
            return winreg.HKEY_CURRENT_USER, self.USER_SUBKEY
        if scope == PathScope.SYSTEM:
            return winreg.HKEY_LOCAL_MACHINE, self.SYSTEM_SUBKEY
        raise ValueError(f"Scope must be USER or SYSTEM, got: {scope}")

    def get_raw_path(self, scope: PathScope) -> Tuple[str, int]:
        """Retrieve raw PATH string and registry type for the given scope."""
        root_key, subkey_path = self._get_registry_location(scope)
        try:
            with winreg.OpenKey(root_key, subkey_path, 0, winreg.KEY_READ) as open_key:
                value, reg_type = winreg.QueryValueEx(open_key, "Path")
                return str(value), int(reg_type)
        except FileNotFoundError:
            return "", winreg.REG_EXPAND_SZ

    def get_path_entries(self, scope: PathScope) -> List[str]:
        """Retrieve individual parsed PATH items for the given scope."""
        raw_val, _ = self.get_raw_path(scope)
        if not raw_val:
            return []
        return [entry.strip() for entry in raw_val.split(";") if entry.strip()]

    def is_directory_in_path(self, target_directory: Union[str, Path], scope: PathScope) -> bool:
        """Check whether a target directory already exists in the scope PATH."""
        target_normalized = normalize_path(target_directory)
        existing_items = self.get_path_entries(scope)

        for item in existing_items:
            if normalize_path(item) == target_normalized:
                return True
            expanded_item = normalize_path(os.path.expandvars(item))
            if expanded_item == target_normalized:
                return True

        return False

    def check_presence(
        self,
        directories: List[Union[str, Path]],
        scope: PathScope,
    ) -> Dict[str, bool]:
        """Check the presence status of multiple directories in the designated scope."""
        results: Dict[str, bool] = {}
        for directory in directories:
            normalized_key = str(Path(directory).resolve())
            results[normalized_key] = self.is_directory_in_path(directory, scope)
        return results

    def _write_path_to_registry(
        self,
        scope: PathScope,
        raw_path_value: str,
        reg_type: int = winreg.REG_EXPAND_SZ,
    ) -> None:
        """Persist updated PATH value to the Windows Registry."""
        root_key, subkey_path = self._get_registry_location(scope)
        access_flags = winreg.KEY_READ | winreg.KEY_WRITE

        try:
            with winreg.OpenKey(root_key, subkey_path, 0, access_flags) as open_key:
                winreg.SetValueEx(open_key, "Path", 0, reg_type, raw_path_value)
        except PermissionError as exc:
            if scope == PathScope.SYSTEM:
                raise PermissionError(
                    "Administrator privileges are required to modify the System PATH environment variable."
                ) from exc
            raise

    def add_directories_to_scope(
        self,
        directories: List[Union[str, Path]],
        scope: PathScope,
        dry_run: bool = False,
        force: bool = False,
    ) -> Dict[str, Any]:
        """Add missing directories to the selected scope PATH with duplicate prevention."""
        raw_val, reg_type = self.get_raw_path(scope)
        existing_entries = self.get_path_entries(scope)

        directories_to_add: List[str] = []
        already_present_directories: List[str] = []

        for item in directories:
            resolved_str = str(Path(item).resolve())
            already_exists = self.is_directory_in_path(item, scope)

            if already_exists and not force:
                already_present_directories.append(resolved_str)
            else:
                directories_to_add.append(resolved_str)

        if not directories_to_add:
            return {
                "scope": scope.value,
                "modified": False,
                "added": [],
                "already_present": already_present_directories,
                "success": True,
            }

        new_entries = list(existing_entries)
        for item in directories_to_add:
            new_entries.append(item)

        updated_path_str = ";".join(new_entries)
        target_reg_type = winreg.REG_EXPAND_SZ

        if not dry_run:
            self._write_path_to_registry(scope, updated_path_str, target_reg_type)

        return {
            "scope": scope.value,
            "modified": True,
            "added": directories_to_add,
            "already_present": already_present_directories,
            "success": True,
        }

    def apply_path_updates(
        self,
        directories: List[Union[str, Path]],
        scope: PathScope,
        dry_run: bool = False,
        force: bool = False,
    ) -> List[Dict[str, Any]]:
        """Apply path updates across target scopes and broadcast changes upon completion."""
        target_scopes: List[PathScope] = []
        if scope == PathScope.BOTH:
            target_scopes = [PathScope.USER, PathScope.SYSTEM]
        else:
            target_scopes = [scope]

        results: List[Dict[str, Any]] = []
        any_modified = False

        for current_scope in target_scopes:
            scope_result = self.add_directories_to_scope(
                directories=directories,
                scope=current_scope,
                dry_run=dry_run,
                force=force,
            )
            results.append(scope_result)
            if scope_result.get("modified"):
                any_modified = True

        if any_modified and not dry_run:
            self.broadcast_environment_change()

        return results
