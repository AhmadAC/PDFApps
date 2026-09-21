#!/usr/bin/env python3
"""
create_shortcut.py
Creates application shortcuts and registers file associations for PDFApps
on Windows 10/11 and Fedora Kinoite (KDE Plasma) without compiling to an executable.
"""

import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path


def get_pythonw_executable() -> str:
    """Finds pythonw.exe for windowless execution on Windows."""
    current_exe = sys.executable
    dir_name = os.path.dirname(current_exe)

    candidates = [
        os.path.join(dir_name, "pythonw.exe"),
        re.sub(
            r"python\.exe$", "pythonw.exe", current_exe, flags=re.IGNORECASE
        ),
        os.path.join(sys.exec_prefix, "pythonw.exe"),
        os.path.join(sys.base_exec_prefix, "pythonw.exe"),
        os.path.join(sys.base_exec_prefix, "Scripts", "pythonw.exe"),
    ]

    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate

    which_path = shutil.which("pythonw.exe") or shutil.which("pythonw")
    if which_path and os.path.isfile(which_path):
        return which_path

    return current_exe


def find_entry_script(project_root: Path) -> Path:
    """Detects the main PDFApps entry point script in the project directory."""
    candidates = [
        "main.py",
        "pdfapps.py",
        "PDFApps.py",
        "run.py",
        "app.py",
    ]
    for name in candidates:
        p = project_root / name
        if p.is_file():
            return p

    for p in project_root.glob("*.py"):
        if p.name == "create_shortcut.py":
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="ignore")
            if "PDFApps – entry point" in content or "MainWindow()" in content:
                return p
        except Exception:
            continue

    return project_root / "main.py"


def register_windows_association(
    app_name: str, python_exe: str, target_script: Path, icon_path: Path
):
    """
    Registers PDFApps under HKCU so Windows recognizes it as a valid handler
    for .pdf files without needing compilation or administrator rights.
    """
    import winreg
    import ctypes

    prog_id = f"{app_name}.Assoc"
    # %1 tells Windows to forward the double-clicked PDF file path to the script
    open_command = f'"{python_exe}" "{target_script}" "%1"'

    try:
        # 1. Create the ProgID and set the execution command
        with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER, rf"Software\Classes\{prog_id}"
        ) as key:
            winreg.SetValueEx(
                key, "", 0, winreg.REG_SZ, f"{app_name} PDF Document"
            )

        with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER,
            rf"Software\Classes\{prog_id}\shell\open\command",
        ) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, open_command)

        if icon_path and icon_path.exists():
            with winreg.CreateKey(
                winreg.HKEY_CURRENT_USER,
                rf"Software\Classes\{prog_id}\DefaultIcon",
            ) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(icon_path))

        # 2. Add to .pdf OpenWithProgids so it shows up in "Open With"
        with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER, r"Software\Classes\.pdf\OpenWithProgids"
        ) as key:
            winreg.SetValueEx(key, prog_id, 0, winreg.REG_NONE, b"")

        # 3. Register Application Capabilities for Windows 10/11 Default Apps settings
        capabilities_path = rf"Software\{app_name}\Capabilities"
        with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER, capabilities_path
        ) as key:
            winreg.SetValueEx(
                key, "ApplicationName", 0, winreg.REG_SZ, app_name
            )
            winreg.SetValueEx(
                key,
                "ApplicationDescription",
                0,
                winreg.REG_SZ,
                f"{app_name} — fast desktop PDF editor",
            )

        with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER, rf"{capabilities_path}\FileAssociations"
        ) as key:
            winreg.SetValueEx(key, ".pdf", 0, winreg.REG_SZ, prog_id)

        with winreg.CreateKey(
            winreg.HKEY_CURRENT_USER, r"Software\RegisteredApplications"
        ) as key:
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, capabilities_path)

        # 4. Notify the Windows Shell to immediately refresh associations
        SHCNE_ASSOCCHANGED = 0x08000000
        SHCNF_IDLIST = 0x0000
        ctypes.windll.shell32.SHChangeNotify(
            SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None
        )

        print(
            f"[SUCCESS] Registered Windows default app capabilities for {app_name}"
        )
    except Exception as e:
        print(f"[ERROR] Failed registering Windows file association: {e}")


def create_windows_shortcut(
    app_name: str,
    python_exe: str,
    target_script: Path,
    working_dir: Path,
    icon_path: Path,
):
    """Creates a Windows .lnk shortcut in the project folder, Desktop, and Start Menu."""
    destinations = [
        working_dir / f"{app_name}.lnk",
    ]

    user_profile = os.environ.get("USERPROFILE")
    appdata = os.environ.get("APPDATA")

    if user_profile:
        desktop_dir = Path(user_profile) / "Desktop"
        if desktop_dir.is_dir():
            destinations.append(desktop_dir / f"{app_name}.lnk")

    if appdata:
        start_menu_dir = (
            Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        )
        if start_menu_dir.is_dir():
            destinations.append(start_menu_dir / f"{app_name}.lnk")

    def ps_quote(s):
        return "'" + str(s).replace("'", "''") + "'"

    print(f"Target interpreter : {python_exe}")
    print(f"Target script      : {target_script}")

    for dest in destinations:
        if dest.exists():
            try:
                dest.unlink()
            except Exception:
                pass

        ps_command = f"""
        $WshShell = New-Object -ComObject WScript.Shell
        $Shortcut = $WshShell.CreateShortcut({ps_quote(dest)})
        $Shortcut.TargetPath = {ps_quote(python_exe)}
        $Shortcut.Arguments = {ps_quote(f'"{target_script}"')}
        $Shortcut.WorkingDirectory = {ps_quote(working_dir)}
        $Shortcut.Description = "PDFApps — fast desktop PDF editor"
        """
        if icon_path and icon_path.exists():
            ps_command += f"\n$Shortcut.IconLocation = {ps_quote(icon_path)}"

        ps_command += "\n$Shortcut.Save()"

        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_command],
                check=True,
                capture_output=True,
                text=True,
            )
            print(f"[SUCCESS] Created shortcut: {dest}")
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Failed creating {dest}: {e.stderr.strip()}")


def create_linux_shortcut(
    app_name: str,
    python_exe: str,
    target_script: Path,
    working_dir: Path,
    icon_path: Path,
):
    desktop_entry = f"""[Desktop Entry]
Version=1.0
Type=Application
Name={app_name}
GenericName=PDF Editor
Comment=Fast desktop PDF editor
Exec="{python_exe}" "{target_script}" %F
Path={working_dir}
Icon={icon_path if icon_path and icon_path.exists() else 'application-pdf'}
Terminal=false
StartupNotify=true
MimeType=application/pdf;
Categories=Office;Viewer;Graphics;
"""

    home_dir = Path.home()
    destinations = [
        working_dir / "pdfapps.desktop",
        home_dir / ".local" / "share" / "applications" / "pdfapps.desktop",
    ]

    desktop_folder = home_dir / "Desktop"
    if desktop_folder.is_dir():
        destinations.append(desktop_folder / "pdfapps.desktop")

    for dest in destinations:
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            dest.write_text(desktop_entry, encoding="utf-8")
            dest.chmod(
                dest.stat().st_mode | stat.S_IXUSR | stat.S_IRUSR | stat.S_IWUSR
            )

            if "Desktop" in str(dest):
                shutil_gio = shutil.which("gio")
                if shutil_gio:
                    subprocess.run(
                        [
                            shutil_gio,
                            "set",
                            str(dest),
                            "metadata::trusted",
                            "true",
                        ],
                        check=False,
                        capture_output=True,
                    )

            print(f"[SUCCESS] Created shortcut: {dest}")
        except Exception as e:
            print(f"[ERROR] Failed writing to {dest}: {e}")

    if shutil.which("update-desktop-database"):
        subprocess.run(
            [
                "update-desktop-database",
                str(home_dir / ".local" / "share" / "applications"),
            ],
            check=False,
            capture_output=True,
        )


def main():
    project_root = Path(__file__).resolve().parent
    app_name = "PDFApps"

    target_script = find_entry_script(project_root)
    if not target_script.exists():
        print(f"Error: Entry point script not found in {project_root}.")
        sys.exit(1)

    print(f"Configuring shortcuts and associations for {app_name}...")

    if sys.platform == "win32":
        python_exe = get_pythonw_executable()
        ico = project_root / "icon.ico"
        png = project_root / "icon_512.png"
        icon_path = ico if ico.exists() else (png if png.exists() else None)

        # 1. Create standard .lnk shortcuts
        create_windows_shortcut(
            app_name, python_exe, target_script, project_root, icon_path
        )
        # 2. Register file handler for Windows Default Apps & Open With
        register_windows_association(
            app_name, python_exe, target_script, icon_path
        )

    elif sys.platform.startswith("linux"):
        python_exe = sys.executable
        png = project_root / "icon_512.png"
        ico = project_root / "icon.ico"
        icon_path = png if png.exists() else (ico if ico.exists() else None)

        create_linux_shortcut(
            app_name, python_exe, target_script, project_root, icon_path
        )
    else:
        print(f"Unsupported operating system: {sys.platform}")


if __name__ == "__main__":
    main()