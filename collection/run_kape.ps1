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
    IR triage set documented in targets.md. Ignored if -CompoundTarget is
    specified.

.PARAMETER CompoundTarget
    Name of a KAPE built-in compound target to collect instead of the
    curated -Targets list (e.g. "SANS_Triage", "BasicCollection" — the
    leading "!" KAPE uses for compound targets is optional here, added
    automatically). Compound targets bundle many individual targets into
    one broad, community-maintained collection; use this when you want
    KAPE's standard preset instead of this repo's scoped IR triage set.
    See collection/targets.md for more on when to prefer one over the
    other, and run `kape.exe --tlist` to see what's available on your
    KAPE install (bundled compound targets vary by version).

.PARAMETER Modules
    Comma-separated list of KAPE !Modules to run against the collected
    targets. Defaults to the set documented in targets.md. Still applies
    when -CompoundTarget is used — modules only process the artifact
    types they match, so anything the compound target collects outside
    this repo's normalized artifact types is left as raw KAPE output.

.PARAMETER KapePath
    Path to kape.exe. Defaults to "kape.exe", resolved via PATH.

.PARAMETER Help
    Show this help and exit. -h and --help are also recognized.

.EXAMPLE
    .\run_kape.ps1 -SourceDrive C: -TargetDestination D:\triage\raw -ModuleDestination D:\triage\parsed

.EXAMPLE
    .\run_kape.ps1 -SourceDrive E: -TargetDestination D:\triage\raw -ModuleDestination D:\triage\parsed `
        -CaseName CASE-2026-014 -Targets RegistryHives,EventLogs -Modules RECmd_DFIRBatch,EvtxECmd

.EXAMPLE
    .\run_kape.ps1 -SourceDrive C: -TargetDestination D:\triage\raw -ModuleDestination D:\triage\parsed `
        -CompoundTarget SANS_Triage

.EXAMPLE
    .\run_kape.ps1 --help
#>

[CmdletBinding(PositionalBinding = $false)]
param(
    # Catches a stray first bare token (e.g. a mistyped "--help", which
    # PowerShell's parameter binder won't recognize as a named flag) so it
    # can be handled below instead of silently binding to -SourceDrive.
    [Parameter(Position = 0)]
    [string]$FirstPositionalArg,

    [Alias("h")]
    [switch]$Help,

    [string]$SourceDrive,

    [string]$TargetDestination,

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

    [string]$CompoundTarget,

    [string[]]$Modules = @(
        "MFTECmd",
        "PECmd",
        "AppCompatCacheParser",
        "RECmd_DFIRBatch",
        "EvtxECmd",
        "LECmd"
    ),

    [string]$KapePath = "kape.exe"
)

# Handle -Help/-h (native PowerShell binding) and the literal "--help"/"-h"/"/?"
# tokens PowerShell's binder doesn't recognize as flags (it would otherwise
# silently bind them positionally to -SourceDrive) before any validation runs,
# so this never falls through to a parameter prompt or a real KAPE invocation.
$helpTokens = @("--help", "-help", "-h", "/?", "help")
if ($Help -or ($FirstPositionalArg -and $helpTokens -contains $FirstPositionalArg.ToLower())) {
    Get-Help -Full $PSCommandPath
    exit 0
}
if ($FirstPositionalArg) {
    Write-Host "Unrecognized argument: '$FirstPositionalArg'. All options must be passed as named parameters, e.g. -SourceDrive C:" -ForegroundColor Red
    Write-Host "Run '.\run_kape.ps1 -Help' for usage." -ForegroundColor Yellow
    exit 1
}

$missingParams = @()
if (-not $SourceDrive) { $missingParams += "-SourceDrive" }
if (-not $TargetDestination) { $missingParams += "-TargetDestination" }
if (-not $ModuleDestination) { $missingParams += "-ModuleDestination" }
if ($missingParams.Count -gt 0) {
    Write-Host "Missing required parameter(s): $($missingParams -join ', ')" -ForegroundColor Red
    Write-Host "Run '.\run_kape.ps1 -Help' for usage." -ForegroundColor Yellow
    exit 1
}

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

if ($CompoundTarget) {
    if ($PSBoundParameters.ContainsKey("Targets")) {
        Write-Host "Both -CompoundTarget and -Targets were specified; -CompoundTarget takes precedence and -Targets is ignored." -ForegroundColor Yellow
    }
    $targetList = "!" + $CompoundTarget.TrimStart("!")
    $targetMode = "KAPE compound target"
} else {
    $targetList = $Targets -join ","
    $targetMode = "curated IR triage set"
}
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
Write-Host "Target mode   : $targetMode"
Write-Host "Targets       : $targetList"
Write-Host "Modules       : $moduleList"
Write-Host "Target output : $tdest"
Write-Host "Module output : $mdest"

# Deliberately a sibling of $mdest, not inside it: KAPE's --mflush clears
# $mdest before running modules, and a transcript file held open inside
# that same directory blocks the flush (KAPE then aborts the whole module
# phase with "Could not flush module destination directory ... Exiting").
$logPath = Join-Path $ModuleDestination "$runName.log"
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

# kape.exe can exit 0 even when the module phase failed outright (e.g. a
# flush failure aborts before any module runs) or every module was skipped,
# so a clean exit code alone isn't proof of useful output — check for it.
$moduleOutputFiles = Get-ChildItem -Path $mdest -Recurse -File -ErrorAction SilentlyContinue
if (-not $moduleOutputFiles) {
    Write-Host "WARNING: kape.exe exited cleanly but $mdest contains no output files. Check $logPath for module errors (e.g. a bad module name, or a flush/permission failure)." -ForegroundColor Yellow
}

Write-Host "Done. Raw targets: $tdest"
Write-Host "Done. Module (CSV) output: $mdest"
