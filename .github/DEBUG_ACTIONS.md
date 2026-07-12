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

## Private repositories and detected tools

Without `PROFILE_README_TOKEN`, the stack updater scans only public,
non-archived repositories. To include private repositories, create a
fine-grained personal access token with access to the repositories that should
contribute to the profile and grant these read-only repository permissions:

- `Metadata` for repository and language statistics
- `Contents` for Gradle files and GitHub Actions workflow detection

Store it as the repository Actions secret `PROFILE_README_TOKEN`. Never add the
token to this repository or a local environment file that can be committed.

For local PowerShell debugging, set the token only for the current process:

```powershell
$env:PROFILE_README_TOKEN = "<token>"
.\.github\scripts\debug-actions.ps1 -Workflow stack
Remove-Item Env:PROFILE_README_TOKEN
```

Tool badges are detected from active repository trees, Gradle build files,
version catalogs, convention plugins, and workflow paths. Android Studio stays
pinned because an IDE cannot be inferred reliably from repository contents.
