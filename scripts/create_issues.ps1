param(
    [string]$Repo = "mhanson13/work-boots",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Require-GitHubCli {
    $gh = Get-Command gh -ErrorAction SilentlyContinue
    if (-not $gh) {
        throw "GitHub CLI ('gh') is not installed or not on PATH. Install it from https://cli.github.com/ and run 'gh auth login'."
    }
}

function Get-IssueFiles {
    param([string]$BasePath)

    Get-ChildItem -Path $BasePath -Filter *.md | Sort-Object Name
}

function Get-TitleFromMarkdown {
    param([string]$Path)

    $lines = Get-Content -Path $Path
    foreach ($line in $lines) {
        if ($line -match '^#\s+(.+)$') { return $Matches[1].Trim() }
        if ($line -match '^##\s+(.+)$') { return $Matches[1].Trim() }
    }
    return [System.IO.Path]::GetFileNameWithoutExtension($Path)
}

function Get-LabelsFromFileName {
    param([string]$Name)

    switch -Wildcard ($Name) {
        "*notification*" { return @("backend","notifications") }
        "*tenant*"       { return @("backend","saas") }
        "*settings*"     { return @("backend","settings") }
        "*reminder*"     { return @("backend","reliability") }
        "*event*"        { return @("backend","observability") }
        "*pilot*"        { return @("pilot","planning") }
        "*operator*"     { return @("frontend","ops") }
        "*provider*"     { return @("backend","configuration") }
        default          { return @("backend") }
    }
}

Require-GitHubCli

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Resolve-Path (Join-Path $scriptDir "..")
$issueDir = Join-Path $repoRoot ".github\issues"

if (-not (Test-Path $issueDir)) {
    throw "Issue directory not found: $issueDir"
}

$files = Get-IssueFiles -BasePath $issueDir
if (-not $files) {
    throw "No issue markdown files found in $issueDir"
}

Write-Host "Repo: $Repo"
Write-Host "Issue dir: $issueDir"
Write-Host ""

foreach ($file in $files) {
    $title = Get-TitleFromMarkdown -Path $file.FullName
    $labels = Get-LabelsFromFileName -Name $file.Name
    $labelArg = ($labels -join ",")

    if ($DryRun) {
        Write-Host "[DRY RUN] gh issue create --repo $Repo --title `"$title`" --body-file `"$($file.FullName)`" --label `"$labelArg`""
    } else {
        Write-Host "Creating issue: $title"
        gh issue create --repo $Repo --title "$title" --body-file "$($file.FullName)" --label "$labelArg"
    }
}

Write-Host ""
Write-Host "Done."
