# KeyHigh Windows 11 port

This folder contains a Windows 11-friendly port of the macOS app.

## What it does
- loads paired videos from `Resources/` named `*_idle.*` and `*_run.*`
- shows one always-on-top transparent overlay per character
- reacts to global typing input
- supports drag, click boost, size changes, add/remove, and quit from the context menu
- includes a system tray icon for show/hide/quit

## Run
```powershell
cd windows
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python keyhigh_windows.py
```

## Build an EXE
```powershell
.\build.ps1
```

## Build an installer
1. Build the EXE first.
2. Open `installer\KeyHigh.iss` in Inno Setup.
3. Compile it to create `dist\KeyHigh-Setup.exe`.

## Notes
- This is a Windows implementation, not a Swift/AppKit build.
- The macOS code in the repo is left intact.
- If your videos have alpha/odd codecs, re-encode them to H.264/H.265 MP4 or M4V for best compatibility.
