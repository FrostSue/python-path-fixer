# Python PATH Fixer for Windows

A robust, production-ready Windows system administration CLI tool written in Python. It automatically discovers local Python installations, verifies whether Python and its `Scripts` directories are present in the User or System `PATH` environment variables, and permanently adds them without creating duplicate entries or requiring system reboots.

---

## Features

- **Automated Python Detection:** Identifies Python runtimes from the currently executing interpreter, Windows Registry (`HKCU` & `HKLM` across 32-bit and 64-bit views), Python Launcher (`py.exe`), and standard filesystem paths (`AppData`, `Program Files`, root drives, and uv/virtual installations).
- **Execution Stub Filtering:** Automatically filters out zero-byte Microsoft Store execution stubs (`WindowsApps\python.exe`).
- **Comprehensive PATH Management:** Supports modifying User-level (`HKCU\Environment`) and System-level (`HKLM\...\Session Manager\Environment`) environment variables.
- **Duplicate Prevention:** Intelligently checks existing entries using path normalization, variable expansion, and case-insensitive comparison to prevent redundant or malformed entries.
- **Immediate Propagation Without Reboot:** Dispatches the `WM_SETTINGCHANGE` Windows API broadcast via `SendMessageTimeoutW` so newly opened terminal sessions immediately recognize `python` and `pip` commands.
- **UAC Elevation Handling:** Detects Windows Administrator privileges and provides self-elevation capability (`--elevate`) via Windows User Account Control when System-level changes are requested.
- **Zero External Dependencies:** Built strictly using the Python Standard Library (`winreg`, `ctypes`, `pathlib`, `argparse`, `logging`).

---

## Architecture Overview

The repository is modularized into dedicated components following separation of concerns:

```
python-path-fixer/
│
├── main.py              # CLI entry point, argument parsing, workflow execution
├── path_manager.py      # Windows Registry interaction, PATH updates, Win32 broadcasting
├── utils.py             # Python runtime discovery, executable validation, path normalization
├── requirements.txt     # Optional developer/testing dependencies
├── LICENSE              # MIT License
└── README.md            # Project documentation
```

### Module Responsibilities

1. **`main.py`**
   - Configures CLI arguments using `argparse`.
   - Initializes structured console logging with verbosity control.
   - Orchestrates detection, validation, elevation checking, and PATH updates.
   - Returns standardized exit codes for scripting and automation.

2. **`path_manager.py`**
   - Interacts directly with Windows Registry keys via `winreg`.
   - Performs duplicate-aware append operations on `REG_EXPAND_SZ` variables.
   - Evaluates administrator privileges via `ctypes.windll.shell32.IsUserAnAdmin`.
   - Triggers `ShellExecuteW` with `runas` verbs for UAC privilege escalation.
   - Invokes `ctypes.windll.user32.SendMessageTimeoutW` with `WM_SETTINGCHANGE` to notify Windows Explorer and shell processes.

3. **`utils.py`**
   - Encapsulates Python installations in a typed `PythonInstallation` dataclass.
   - Scans system registries and filesystem trees.
   - Validates candidate executables and queries version information.
   - Provides path normalization and case-insensitive equivalence checks.

---

## Requirements

- **Operating System:** Windows 10, Windows 11, or Windows Server 2016+
- **Python Version:** Python 3.8 or higher
- **Dependencies:** None (Pure Python Standard Library)

---

## Installation

Clone the repository to your local machine:

```powershell
git clone https://github.com/FrostSue/python-path-fixer.git
cd python-path-fixer
```

No package installation is required to run the CLI. Optional development tools can be installed via:

```powershell
pip install -r requirements.txt
```

---

## Usage Guide

### 1. Discover and Inspect Python Installations

List all detected Python runtimes and inspect their current presence in User and System PATH:

```powershell
python main.py --list
```

*Example Output:*
```text
INFO: Scanning system for Python installations...
INFO: Discovered 3 Python installation(s):

[1] Python 3.15.2 [CURRENT RUNTIME]
    Source:          Current Process
    Executable:      C:\Users\<User>\AppData\Local\Python\pythoncore-3.15-64\python.exe
    Installation:    C:\Users\<User>\AppData\Local\Python\pythoncore-3.15-64
    Scripts:         C:\Users\<User>\AppData\Local\Python\pythoncore-3.15-64\Scripts (Exists: True)
    User PATH:       Root: [NO] | Scripts: [NO]
    System PATH:     Root: [NO] | Scripts: [NO]
```

---

### 2. Preview Changes (Dry Run)

Simulate what would be modified without making changes to the Windows Registry:

```powershell
python main.py --dry-run
```

---

### 3. Add Auto-Detected Python to User PATH (Default)

Automatically detects the primary Python installation and permanently adds both the installation directory and the `Scripts` directory to the current user's `PATH`:

```powershell
python main.py
```

---

### 4. Target System-Level PATH with UAC Elevation

Modifying system-wide environment variables requires Windows Administrator permissions. Use `--scope system` or `--scope both` along with `--elevate` to prompt the Windows UAC dialog if running from a standard terminal:

```powershell
python main.py --scope system --elevate
```

Alternatively, open PowerShell or Command Prompt as Administrator and run:

```powershell
python main.py --scope system
```

---

### 5. Manually Specify a Python Installation

If you wish to configure a specific or portable Python installation:

```powershell
python main.py --python-path "C:\Python312"
```

You may also specify the executable directly:

```powershell
python main.py --python-path "C:\Python312\python.exe"
```

---

### 6. Exclude the Scripts Directory

If you only want the root Python folder added without `Scripts`:

```powershell
python main.py --no-scripts
```

---

### 7. Force Addition of Duplicate Entries

By default, existing entries are skipped. Use `--force` to append entries regardless:

```powershell
python main.py --force
```

---

### 8. Enable Verbose Debug Output

Enable detailed diagnostics during execution:

```powershell
python main.py -v
```

---

## Command-Line Options Reference

| Option | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `--scope` | `user` \| `system` \| `both` | `user` | Target Windows environment scope for the modification. |
| `--python-path` | `string` | `None` | Explicit path to a Python directory or executable. |
| `--dry-run` | `flag` | `False` | Simulates operations without writing to the registry. |
| `--force` | `flag` | `False` | Adds directories even if already detected in PATH. |
| `-v`, `--verbose` | `flag` | `False` | Enables verbose debug logging output. |
| `-l`, `--list` | `flag` | `False` | Lists detected installations and their PATH status, then exits. |
| `--elevate` | `flag` | `False` | Requests Windows UAC elevation if system scope requires it. |
| `--no-scripts` | `flag` | `False` | Excludes the `Scripts` directory from the PATH update. |
| `-h`, `--help` | `flag` | - | Displays usage help and exits. |

---

## Exit Codes

The application uses standard semantic exit codes suitable for CI/CD pipelines, PowerShell scripts, and batch automation:

| Exit Code | Meaning | Description |
| :---: | :--- | :--- |
| `0` | **Success** | Operations completed successfully, changes applied, or already up to date. |
| `1` | **Runtime Error** | An unexpected exception occurred during execution. |
| `2` | **Permission Error** | Administrative privileges are required to modify the target scope. |
| `3` | **Installation Error** | No Python installation could be located, or specified path is invalid. |

---

## Windows Registry Details

### Registry Keys Modified

- **User PATH:**
  ```text
  HKEY_CURRENT_USER\Environment
  Value Name: Path
  Type: REG_EXPAND_SZ (or REG_SZ)
  ```
- **System PATH:**
  ```text
  HKEY_LOCAL_MACHINE\System\CurrentControlSet\Control\Session Manager\Environment
  Value Name: Path
  Type: REG_EXPAND_SZ
  ```

### Change Notification

After updating the registry, the utility broadcasts a `WM_SETTINGCHANGE` message to all top-level windows:

```c
SendMessageTimeoutW(
    HWND_BROADCAST,
    WM_SETTINGCHANGE,
    0,
    (LPARAM)L"Environment",
    SMTO_ABORTIFHUNG,
    5000,
    &dwResult
);
```

This signals running shells and desktop processes that environment variables have changed, enabling newly opened shells to pick up the changes immediately.

---

## Troubleshooting

### Python is not recognized in an existing terminal
Environment variables are read by terminal processes upon startup. After applying changes, close and reopen your PowerShell, Command Prompt, or VS Code terminal window.

### Access is denied when targeting System scope
Run the terminal as Administrator, or pass the `--elevate` flag so the script prompts for administrative privileges via UAC:
```powershell
python main.py --scope system --elevate
```

### Windows Store app launches instead of Python
Windows includes zero-byte execution aliases in `AppData\Local\Microsoft\WindowsApps`. `python-path-fixer` intentionally filters these out and adds your real Python installation to your user environment so your actual interpreter takes precedence.

---

## License

This project is licensed under the [MIT License](LICENSE).
