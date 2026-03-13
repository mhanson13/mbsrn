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
        if ($line -match '^#\s+(.+)$') {
            return $Matches[1].Trim()
        }
    }

    return [System.IO.Path]::GetFileNameWithoutExtension($Path).Replace("-", " ")
}

function Get-LabelsFromFileName {
    param([string]$Name)

    switch -Wildcard ($Name) {
        "*notification-provider*"  { return @("backend", "configuration") }
        "*notification-dispatch*"  { return @("backend", "notifications") }
        "*tenant*"                 { return @("backend", "saas") }
        "*business-settings*"      { return @("backend", "settings") }
        "*reminder*"               { return @("backend", "reliability") }
        "*lead-event*"             { return @("backend", "observability") }
        "*pilot*"                  { return @("pilot", "planning") }
        "*operator*"               { return @("frontend", "ops") }
        default                    { return @("backend") }
    }
}

function Ensure-LabelsExist {
    param([string]$Repo, [switch]$DryRun)

    $desiredLabels = @(
        @{ Name = "backend";       Color = "1D76DB"; Description = "Backend work" },
        @{ Name = "frontend";      Color = "5319E7"; Description = "Frontend work" },
        @{ Name = "notifications"; Color = "FBCA04"; Description = "Notification system" },
        @{ Name = "reliability";   Color = "D93F0B"; Description = "Reliability and hardening" },
        @{ Name = "saas";          Color = "0E8A16"; Description = "SaaS and multi-tenant readiness" },
        @{ Name = "settings";      Color = "C2E0C6"; Description = "Business settings and configuration" },
        @{ Name = "observability"; Color = "BFDADC"; Description = "Metrics, events, and tracing" },
        @{ Name = "pilot";         Color = "F9D0C4"; Description = "Pilot readiness" },
        @{ Name = "planning";      Color = "FEF2C0"; Description = "Planning and backlog shaping" },
        @{ Name = "ops";           Color = "0052CC"; Description = "Operational/admin workflows" },
        @{ Name = "configuration"; Color = "E99695"; Description = "Environment and provider configuration" }
    )

    $existingLabels = @{}
    $labelLines = gh label list --repo "$Repo" --limit 200
    foreach ($line in $labelLines) {
        $labelName = ($line -split '\s+')[0].Trim()
        if ($labelName) {
            $existingLabels[$labelName] = $true
        }
    }

    foreach ($label in $desiredLabels) {
        if ($existingLabels.ContainsKey($label.Name)) {
            Write-Host "Label exists: $($label.Name)"
            continue
        }

        $cmd = "gh label create `"$($label.Name)`" --repo `"$Repo`" --color `"$($label.Color)`" --description `"$($label.Description)`""
        if ($DryRun) {
            Write-Host "[DRY RUN] $cmd"
        }
        else {
            Write-Host "Creating label: $($label.Name)"
            gh label create "$($label.Name)" --repo "$Repo" --color "$($label.Color)" --description "$($label.Description)"
        }
    }
}

function Get-ExistingIssueTitles {
    param([string]$Repo)

    $titles = @{}
    $issueLines = gh issue list --repo "$Repo" --limit 200 --state all --json title | ConvertFrom-Json
    foreach ($issue in $issueLines) {
        if ($issue.title) {
            $titles[$issue.title] = $true
        }
    }
    return $titles
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

Write-Host "Ensuring labels exist..."
Ensure-LabelsExist -Repo $Repo -DryRun:$DryRun
Write-Host ""

$existingIssueTitles = Get-ExistingIssueTitles -Repo $Repo

foreach ($file in $files) {
    $title = Get-TitleFromMarkdown -Path $file.FullName
    $labels = Get-LabelsFromFileName -Name $file.Name
    $labelArg = ($labels -join ",")

    if ($existingIssueTitles.ContainsKey($title)) {
        Write-Host "Skipping existing issue: $title"
        continue
    }

    $cmd = "gh issue create --repo `"$Repo`" --title `"$title`" --body-file `"$($file.FullName)`" --label `"$labelArg)`""

    if ($DryRun) {
        Write-Host "[DRY RUN] gh issue create --repo `"$Repo`" --title `"$title`" --body-file `"$($file.FullName)`" --label `"$labelArg`""
    }
    else {
        Write-Host "Creating issue: $title"
        gh issue create --repo "$Repo" --title "$title" --body-file "$($file.FullName)" --label "$labelArg"
    }
}

Write-Host ""
Write-Host "Done."