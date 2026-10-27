"""
Utility module for locating and validating Python installations on Windows.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import winreg
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class PythonInstallation:
    """Data model representing a discovered Python installation."""

    install_dir: Path
    executable_path: Path
    scripts_dir: Path
    version: str
    source: str
    is_current: bool = False

    def __post_init__(self) -> None:
        self.install_dir = self.install_dir.resolve()
        self.executable_path = self.executable_path.resolve()
        self.scripts_dir = self.scripts_dir.resolve()


def normalize_path(path: str | Path) -> str:
    """Normalize a filesystem path for reliable comparison."""
    if not path:
        return ""
    expanded = os.path.expandvars(str(path))
    normalized = os.path.normcase(os.path.normpath(expanded))
    return normalized.rstrip("\\/")


def paths_equal(path_a: str | Path, path_b: str | Path) -> bool:
    """Check if two filesystem paths refer to the same location."""
    return normalize_path(path_a) == normalize_path(path_b)


def get_python_version(executable_path: Path) -> str:
    """Extract Python version from executable or fallback to directory name."""
    try:
        process = subprocess.run(
            [str(executable_path), "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        output = (process.stdout or process.stderr).strip()
        match = re.search(r"Python\s+([0-9]+\.[0-9]+(\.[0-9]+)?)", output, re.IGNORECASE)
        if match:
            return match.group(1)
    except Exception:
        pass

    path_str = str(executable_path)
    match = re.search(r"python[core\-]*([0-9]+[\.\-]?[0-9]*)", path_str, re.IGNORECASE)
    if match:
        raw_version = match.group(1).replace("-", ".")
        return raw_version

    return "Unknown"


def validate_python_directory(target_path: str | Path, source: str = "Custom") -> Optional[PythonInstallation]:
    """Validate whether a path contains a genuine, functional Python installation."""
    try:
        resolved_path = Path(target_path).resolve()
    except Exception:
        return None

    if resolved_path.is_file():
        executable_path = resolved_path
        install_dir = resolved_path.parent
    elif resolved_path.is_dir():
        executable_path = resolved_path / "python.exe"
        install_dir = resolved_path
    else:
        return None

    if not executable_path.is_file():
        return None

    if "windowsapps" in str(executable_path).lower():
        return None

    try:
        if executable_path.stat().st_size == 0:
            return None
    except OSError:
        return None

    scripts_dir = install_dir / "Scripts"
    version = get_python_version(executable_path)
    is_current = paths_equal(executable_path, sys.executable)

    return PythonInstallation(
        install_dir=install_dir,
        executable_path=executable_path,
        scripts_dir=scripts_dir,
        version=version,
        source=source,
        is_current=is_current,
    )


def _detect_current_python() -> Optional[PythonInstallation]:
    """Detect the currently running Python interpreter."""
    try:
        current_exe = Path(sys.executable).resolve()
        current_dir = Path(sys.prefix).resolve()
        scripts_dir = current_dir / "Scripts"
        version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        return PythonInstallation(
            install_dir=current_dir,
            executable_path=current_exe,
            scripts_dir=scripts_dir,
            version=version,
            source="Current Process",
            is_current=True,
        )
    except Exception:
        return None


def _detect_from_registry() -> List[PythonInstallation]:
    """Detect Python installations registered in the Windows Registry."""
    installations: List[PythonInstallation] = []
    registry_roots = [
        (winreg.HKEY_CURRENT_USER, "Registry (HKCU)"),
        (winreg.HKEY_LOCAL_MACHINE, "Registry (HKLM)"),
    ]
    access_flags = [
        (winreg.KEY_WOW64_64KEY, "64-bit"),
        (winreg.KEY_WOW64_32KEY, "32-bit"),
    ]

    for root_key, root_name in registry_roots:
        for bit_flag, bit_name in access_flags:
            try:
                with winreg.OpenKey(
                    root_key,
                    r"Software\Python\PythonCore",
                    0,
                    winreg.KEY_READ | bit_flag,
                ) as core_key:
                    subkey_count = winreg.QueryInfoKey(core_key)[0]
                    for idx in range(subkey_count):
                        version_tag = winreg.EnumKey(core_key, idx)
                        try:
                            with winreg.OpenKey(core_key, rf"{version_tag}\InstallPath") as path_key:
                                raw_install_path = winreg.QueryValue(path_key, "")
                                if raw_install_path:
                                    inst = validate_python_directory(
                                        raw_install_path,
                                        f"{root_name} {bit_name}",
                                    )
                                    if inst:
                                        installations.append(inst)
                        except FileNotFoundError:
                            continue
            except FileNotFoundError:
                continue
            except PermissionError:
                continue
            except OSError:
                continue

    return installations


def _detect_from_py_launcher() -> List[PythonInstallation]:
    """Detect Python installations via py.exe launcher if available."""
    installations: List[PythonInstallation] = []
    py_tool = shutil.which("py")
    if not py_tool:
        return installations

    try:
        process = subprocess.run(
            [py_tool, "-0p"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        output = process.stdout or ""
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            match = re.search(r"([A-Za-z]:\\[^\t\r\n]+\.exe)", line)
            if match:
                exe_candidate = Path(match.group(1))
                if exe_candidate.is_file():
                    inst = validate_python_directory(exe_candidate, "Python Launcher")
                    if inst:
                        installations.append(inst)
    except Exception:
        pass

    return installations


def _detect_from_filesystem() -> List[PythonInstallation]:
    """Detect Python installations in common standard Windows directories."""
    installations: List[PythonInstallation] = []
    candidate_roots: List[Path] = []

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        local_path = Path(local_app_data)
        candidate_roots.append(local_path / "Programs" / "Python")
        candidate_roots.append(local_path / "Python")

    app_data = os.environ.get("APPDATA")
    if app_data:
        roaming_path = Path(app_data)
        candidate_roots.append(roaming_path / "uv" / "python")

    for drive_letter in ["C", "D"]:
        candidate_roots.append(Path(f"{drive_letter}:\\"))

    program_files = os.environ.get("ProgramFiles")
    if program_files:
        candidate_roots.append(Path(program_files))

    program_files_x86 = os.environ.get("ProgramFiles(x86)")
    if program_files_x86:
        candidate_roots.append(Path(program_files_x86))

    for base_root in candidate_roots:
        if not base_root.is_dir():
            continue

        try:
            for item in base_root.iterdir():
                if not item.is_dir():
                    continue

                folder_name = item.name.lower()
                if "python" in folder_name or "cpython" in folder_name:
                    inst = validate_python_directory(item, "Filesystem Scan")
                    if inst:
                        installations.append(inst)

                    nested_python = item / "python.exe"
                    if nested_python.is_file():
                        inst_nested = validate_python_directory(item, "Filesystem Scan")
                        if inst_nested:
                            installations.append(inst_nested)
        except (PermissionError, OSError):
            continue

    return installations


def _detect_from_system_path() -> List[PythonInstallation]:
    """Detect Python installations currently accessible in the process PATH."""
    installations: List[PythonInstallation] = []
    python_in_path = shutil.which("python")
    if python_in_path:
        inst = validate_python_directory(Path(python_in_path), "Process PATH")
        if inst:
            installations.append(inst)
    return installations


def detect_python_installations() -> List[PythonInstallation]:
    """Discover all Python installations on the system and return deduplicated list."""
    all_discovered: List[PythonInstallation] = []

    current = _detect_current_python()
    if current:
        all_discovered.append(current)

    all_discovered.extend(_detect_from_registry())
    all_discovered.extend(_detect_from_py_launcher())
    all_discovered.extend(_detect_from_filesystem())
    all_discovered.extend(_detect_from_system_path())

    unique_installations: List[PythonInstallation] = []
    seen_paths: Set[str] = set()

    for item in all_discovered:
        normalized_key = normalize_path(item.install_dir)
        if normalized_key not in seen_paths:
            seen_paths.add(normalized_key)
            unique_installations.append(item)

    return unique_installations


def get_default_python_installation(installations: Optional[List[PythonInstallation]] = None) -> Optional[PythonInstallation]:
    """Select the most appropriate default Python installation from discovered items."""
    candidates = installations if installations is not None else detect_python_installations()
    if not candidates:
        return None

    for item in candidates:
        if item.is_current:
            return item

    for item in candidates:
        if "Registry" in item.source:
            return item

    return candidates[0]
