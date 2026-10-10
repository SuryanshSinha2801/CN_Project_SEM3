# Portable Windows application

This is the zero-install distribution for friends who want to use the Tkinter GUI. The
recipient does not need Python, Docker, Git, or internet access after receiving the ZIP.

## Build

From PowerShell in the repository:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-build.txt
.\package_windows.ps1
```

The build creates:

```text
dist\BLACKOUT_Portable_Windows_x64.zip
```

The script prints the ZIP's SHA-256 checksum. Send both the ZIP and that checksum to the
recipient through separate messages if possible.

## Recipient instructions

1. Download the ZIP.
2. Verify its SHA-256 checksum.
3. Extract it completely.
4. Double-click `BLACKOUT_Simulator.exe`.

The executable is built for 64-bit Windows. Executables must be built separately on each
target operating system; a Windows build does not run natively on macOS or Linux.

## SmartScreen

The executable is not commercially code-signed, so Windows SmartScreen may show an
unknown-publisher warning. This cannot be removed safely without purchasing and protecting
a trusted code-signing certificate. The checksum lets the recipient verify that the file
they received is exactly the package produced by the sender.
