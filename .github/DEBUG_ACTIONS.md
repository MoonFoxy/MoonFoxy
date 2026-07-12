# Local Actions debugging

GitHub Actions can be debugged locally without a GitHub runner.

Requirements:

- Python 3.10+
- `ffmpeg` on `PATH` for the four terminal GIFs
- `GITHUB_TOKEN` or `PROFILE_README_TOKEN` for live GitHub statistics

The local debugger installs Pillow when `-InstallPythonPackages` is supplied.
The generator uses the vendored JetBrains Mono font, so no system font setup is
required.

From the repository root in PowerShell:

```powershell
.\.github\scripts\debug-actions.ps1 -Workflow neofetch -InstallPythonPackages
```

Run the stack updater:

```powershell
.\.github\scripts\debug-actions.ps1 -Workflow stack -InstallPythonPackages
```

Run both:

```powershell
.\.github\scripts\debug-actions.ps1 -Workflow all -InstallPythonPackages
```

The neofetch workflow runs the generator with `--all` and verifies these files:

- `neofetch-en-dark.gif`
- `neofetch-en-light.gif`
- `neofetch-ru-dark.gif`
- `neofetch-ru-light.gif`

The local runner executes the same Python scripts as Actions. It does not push
anything; inspect the generated GIFs, README diff, and console errors locally
first.
