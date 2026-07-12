[CmdletBinding()]
param(
    [ValidateSet("neofetch", "stack", "all")]
    [string]$Workflow = "neofetch",
    [switch]$InstallPythonPackages
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "../..")).Path

function Resolve-Python {
    $candidates = @()
    foreach ($name in @("python", "python3", "py")) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($null -ne $command) {
            $candidates += $command.Source
        }
    }

    foreach ($directory in @(
        (Join-Path $env:LOCALAPPDATA "Python"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python")
    )) {
        if (Test-Path -LiteralPath $directory -PathType Container) {
            $candidates += Get-ChildItem -LiteralPath $directory -Filter "python.exe" -File -Recurse |
                Select-Object -ExpandProperty FullName
        }
    }

    foreach ($candidate in $candidates | Select-Object -Unique) {
        try {
            & $candidate -c "import sys; assert sys.version_info >= (3, 10)"
            if ($LASTEXITCODE -eq 0) {
                return $candidate
            }
        } catch {
            # Continue looking for another local Python executable.
        }
    }

    throw "Python 3.10+ was not found. Install Python locally, then run this script again."
}

function Require-Executable([string]$Name) {
    if ($null -eq (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name was not found on PATH. Install it locally before debugging this workflow."
    }
}

function Invoke-CheckedNative([string]$FilePath, [string[]]$Arguments) {
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath exited with code $LASTEXITCODE."
    }
}

$Python = Resolve-Python
$env:PYTHONPATH = $Root

if ($InstallPythonPackages) {
    Invoke-CheckedNative $Python @("-m", "pip", "install", "--upgrade", "pip")
    Invoke-CheckedNative $Python @("-m", "pip", "install", "Pillow>=11,<13")
}

Push-Location $Root
try {
    if (-not [string]::IsNullOrWhiteSpace($env:PROFILE_README_TOKEN)) {
        if ([string]::IsNullOrWhiteSpace($env:GITHUB_TOKEN)) {
            $env:GITHUB_TOKEN = $env:PROFILE_README_TOKEN
        }
        if ([string]::IsNullOrWhiteSpace($env:GH_PAT)) {
            $env:GH_PAT = $env:PROFILE_README_TOKEN
        }
    }

    if ($Workflow -in @("neofetch", "all")) {
        Require-Executable "ffmpeg"
        Invoke-CheckedNative $Python @(".github\scripts\generate_terminal_gif.py", "--all")
        foreach ($name in @(
            "neofetch-en-dark.gif",
            "neofetch-en-light.gif",
            "neofetch-ru-dark.gif",
            "neofetch-ru-light.gif"
        )) {
            $output = Join-Path $Root ".github\assets\$name"
            if (-not (Test-Path -LiteralPath $output -PathType Leaf) -or (Get-Item -LiteralPath $output).Length -eq 0) {
                throw "Expected GIF was not generated: $output"
            }
        }
    }

    if ($Workflow -in @("stack", "all")) {
        Invoke-CheckedNative $Python @(".github\scripts\update_stack.py")
    }
} finally {
    Pop-Location
}

Write-Host "Local workflow debug completed: $Workflow" -ForegroundColor Green
