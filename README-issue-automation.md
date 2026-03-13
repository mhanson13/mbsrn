# GitHub Issue Automation Setup v2

This package contains a corrected issue automation setup for `work-boots`.

## Fixes in v2

- Adds `scripts/create_labels.ps1` so labels exist before issue creation
- Uses first `# Title` heading in each issue file for the issue title
- Falls back to filename if no `# Title` heading exists
- Fails early if required labels are missing

## Included files

- `.github/issues/*.md`
- `scripts/create_labels.ps1`
- `scripts/create_issues.ps1`

## Suggested usage

From the repo root:

```powershell
.\scripts\create_labels.ps1 -DryRun
.\scripts\create_labels.ps1
.\scripts\create_issues.ps1 -DryRun
.\scripts\create_issues.ps1
```

## Prerequisites

Install GitHub CLI and authenticate locally:

```powershell
gh auth login
```
