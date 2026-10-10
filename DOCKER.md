# BLACKOUT Docker packaging and handoff

The Docker image provides the Python 3.13 simulation engine, CLI, scenarios, exports,
and automated tests. It intentionally does not launch the Tkinter window: a normal
container has no Windows desktop display. Use the local Python setup for the GUI.

## 1. Install Docker Desktop

Install Docker Desktop on both computers and confirm that Linux containers are enabled:

```powershell
docker version
```

## 2. Build the image

From `C:\codes\CN_SEM3`:

```powershell
docker build --tag cn-project-sem3:1.0 .
```

The build runs the container-compatible automated tests. A failing test makes the image
build fail.

## 3. Exercise it before sending

Validate the default presentation scenario:

```powershell
docker run --rm cn-project-sem3:1.0
```

Run the complete non-GUI test suite again:

```powershell
docker run --rm --entrypoint python cn-project-sem3:1.0 `
  -m pytest --quiet --ignore=tests/test_gui.py
```

Run one simulation and retain its CSV/JSON files on the host:

```powershell
New-Item -ItemType Directory -Force docker-results
$resultsPath = (Resolve-Path .\docker-results).Path
docker run --rm `
  --mount "type=bind,source=$resultsPath,target=/app/results" `
  cn-project-sem3:1.0 `
  run configs/presentation.yaml --output results/demo
```

Run the three-policy comparison:

```powershell
docker run --rm `
  --mount "type=bind,source=$resultsPath,target=/app/results" `
  cn-project-sem3:1.0 `
  experiment configs/presentation.yaml `
  --seeds 1 2 3 4 5 6 7 8 9 10 `
  --output results/comparison
```

## 4. Export the image for your friend

```powershell
docker image save --output CN_Project_SEM3-1.0.tar cn-project-sem3:1.0
Get-FileHash .\CN_Project_SEM3-1.0.tar -Algorithm SHA256
```

Send the `.tar` file and the displayed SHA-256 value using Drive, OneDrive, or another
large-file service. Do not send `.env`, credential, key, or local virtual-environment
files.

## 5. Friend: verify and load

Your friend should first compare the checksum with the value you sent:

```powershell
Get-FileHash .\CN_Project_SEM3-1.0.tar -Algorithm SHA256
docker image load --input .\CN_Project_SEM3-1.0.tar
docker run --rm cn-project-sem3:1.0
```

They can then run the test and experiment commands from section 3.

## Alternative: share the repository

Because the repository is public, the smaller transfer is simply the GitHub URL. Your
friend can clone it and run the same `docker build` command. Send the image archive only
when they should not need to build it themselves.

## GUI testing

For the Tkinter presentation GUI, clone or unzip the repository on the friend's machine
and use the native Python 3.13 environment:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirement.txt
python -m blackout gui
```

Forwarding X11 or running a VNC desktop inside Docker is possible, but it adds a display
server and remote-desktop layer unrelated to the network simulation. Native Tkinter is
the simpler and more reliable way to test the GUI on Windows.
