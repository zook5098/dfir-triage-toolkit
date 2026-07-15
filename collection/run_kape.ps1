<#
.SYNOPSIS
    Wrapper around KAPE that runs a curated Target/Module set for IR triage.

.DESCRIPTION
    Invokes kape.exe (assumed installed and on PATH) once, collecting the
    configured !Targets from the source and immediately processing the
    collected data with the configured !Modules (EZ Tools). Target and
    module selection defaults to the set documented in targets.md; both
    are override-able for one-off runs.

    Output is written under a per-run, timestamped case folder so repeat
    runs against the same host never clobber prior evidence:
        <TargetDestination>\<CaseName>_<timestamp>\        (raw KAPE targets)
        <ModuleDestination>\<CaseName>_<timestamp>\         (EZ Tools CSV output)

.PARAMETER SourceDrive
    Drive letter or UNC path KAPE collects from. Use "C:" for a live local
    triage, or a drive letter / path to a mounted image.

.PARAMETER TargetDestination
    Root folder for raw KAPE target output. A per-run subfolder is created
    under this path.

.PARAMETER ModuleDestination
    Root folder for parsed (EZ Tools) module output. A per-run subfolder is
    created under this path.

.PARAMETER CaseName
    Case/incident identifier used in the output folder name. Defaults to
    the local hostname.

.PARAMETER Targets
    Comma-separated list of KAPE !Targets to collect. Defaults to the
    IR triage set documented in targets.md.

.PARAMETER Modules
    Comma-separated list of KAPE !Modules to run against the collected
    targets. Defaults to the set documented in targets.md.

.PARAMETER KapePath
    Path to kape.exe. Defaults to "kape.exe", resolved via PATH.

.EXAMPLE
    .\run_kape.ps1 -SourceDrive C: -TargetDestination D:\triage\raw -ModuleDestination D:\triage\parsed

.EXAMPLE
    .\run_kape.ps1 -SourceDrive E: -TargetDestination D:\triage\raw -ModuleDestination D:\triage\parsed `
        -CaseName CASE-2026-014 -Targets RegistryHives,EventLogs -Modules RECmd,EvtxECmd
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SourceDrive,

    [Parameter(Mandatory = $true)]
    [string]$TargetDestination,

    [Parameter(Mandatory = $true)]
    [string]$ModuleDestination,

    [string]$CaseName = $env:COMPUTERNAME,

    [string[]]$Targets = @(
        "RegistryHives",
        "EventLogs",
        "FileSystem",
        "Prefetch",
        "ScheduledTasks",
        "Amcache",
        "LNKFilesAndFolders"
    ),

    [string[]]$Modules = @(
        "MFTECmd",
        "PECmd",
        "AppCompatCacheParser",
        "RECmd",
        "EvtxECmd",
        "LECmd"
    ),

    [string]$KapePath = "kape.exe"
)

$ErrorActionPreference = "Stop"

function Assert-KapeAvailable {
    param([string]$Path)

    $resolved = Get-Command $Path -ErrorAction SilentlyContinue
    if (-not $resolved) {
        throw "kape.exe not found at '$Path' or on PATH. Install KAPE or pass -KapePath."
    }
    return $resolved.Source
}

$kapeExe = Assert-KapeAvailable -Path $KapePath

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$runName = "${CaseName}_${timestamp}"

$tdest = Join-Path $TargetDestination $runName
$mdest = Join-Path $ModuleDestination $runName

New-Item -ItemType Directory -Path $tdest -Force | Out-Null
New-Item -ItemType Directory -Path $mdest -Force | Out-Null

$targetList = $Targets -join ","
$moduleList = $Modules -join ","

$kapeArgs = @(
    "--tsource", $SourceDrive,
    "--tdest", $tdest,
    "--target", $targetList,
    "--mdest", $mdest,
    "--module", $moduleList,
    "--mflush"
)

Write-Host "KAPE binary   : $kapeExe"
Write-Host "Source        : $SourceDrive"
Write-Host "Targets       : $targetList"
Write-Host "Modules       : $moduleList"
Write-Host "Target output : $tdest"
Write-Host "Module output : $mdest"

$logPath = Join-Path $mdest "run_kape.log"
Start-Transcript -Path $logPath -Append | Out-Null

try {
    & $kapeExe @kapeArgs
    if ($LASTEXITCODE -ne 0) {
        throw "kape.exe exited with code $LASTEXITCODE"
    }
}
finally {
    Stop-Transcript | Out-Null
}

Write-Host "Done. Raw targets: $tdest"
Write-Host "Done. Module (CSV) output: $mdest"
