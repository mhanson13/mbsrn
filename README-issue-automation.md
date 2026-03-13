# GitHub Issue Automation Setup

This folder contains a simple issue automation setup for the `work-boots` repository.

## What is included

- `.github/issues/*.md` issue templates/content files
- `scripts/create_issues.ps1` PowerShell script to create GitHub issues with `gh`

## Prerequisites

Install GitHub CLI and authenticate locally:

```powershell
gh auth login
```

## Usage

From the repository root:

```powershell
.\scripts\create_issues.ps1
```

Dry run:

```powershell
.\scripts\create_issues.ps1 -DryRun
```

Use a different repo:

```powershell
.\scripts\create_issues.ps1 -Repo "owner/repo"
```

## Suggested placement in your repo

Copy these into your actual repo:

- `.github/issues/`
- `scripts/create_issues.ps1`

Then run the script from the repo root after authenticating with GitHub CLI.
