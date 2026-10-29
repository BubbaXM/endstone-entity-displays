param([string]$Server = (Join-Path $PSScriptRoot '../bedrock_server'), [switch]$StageUpdate)
$ErrorActionPreference = 'Stop'
# Explicit staging never needs to inspect processes (CIM can be unavailable in
# restricted shells). Without -StageUpdate retain the normal running check.
$serverRunning = if ($StageUpdate) { $true } else { [bool](Get-CimInstance Win32_Process -Filter "Name='bedrock_server.exe'") }
$serverRoot = (Resolve-Path -LiteralPath $Server).Path
if (-not (Test-Path -LiteralPath (Join-Path $serverRoot 'server.properties') -PathType Leaf)) {
    throw 'Not a Bedrock server folder.'
}
$pluginRoot = Join-Path $serverRoot 'plugins'
$localRoot = Join-Path $pluginRoot '.local'
$package = Join-Path $localRoot 'endstone_entity_displays'
$metadata = Join-Path $localRoot 'endstone_entity_displays-0.2.2.dist-info'
$legacyMetadata = @('0.1.0', '0.2.0', '0.2.1') | ForEach-Object { Join-Path $localRoot "endstone_entity_displays-$_.dist-info" }
$acceptedMetadata = @($metadata) + @($legacyMetadata)
$source = Join-Path $PSScriptRoot 'src/endstone_entity_displays'
$files = @('__init__.py', 'plugin.py', 'placement.py', 'packs.py', 'packets.py', 'store.py', 'renderer.py', 'api.py', 'transforms.py', 'catalog.py', 'spider.py', 'assets/display_packs.zip', 'assets/pack_index.json')

function Assert-InstallPath([string]$Target) {
    $absolute = [System.IO.Path]::GetFullPath($Target)
    if (-not $absolute.StartsWith($pluginRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw 'Install target escapes the server plugin directory.'
    }
    $current = $absolute
    while ($current.Length -ge $pluginRoot.Length) {
        if ((Test-Path -LiteralPath $current) -and (Get-Item -LiteralPath $current -Force).LinkType) {
            throw "Refusing a linked install path: $current"
        }
        $current = Split-Path -Parent $current
    }
}

foreach ($target in (@($localRoot, $package, $metadata, (Join-Path $package 'assets')) + @($legacyMetadata))) {
    Assert-InstallPath $target
}
foreach ($file in $files) {
    if (-not (Test-Path -LiteralPath (Join-Path $source $file) -PathType Leaf)) {
        throw "Missing source: $file. Run python -B tools/build_packs.py first."
    }
    Assert-InstallPath (Join-Path $package $file)
}
foreach ($file in @('METADATA', 'entry_points.txt')) {
    Assert-InstallPath (Join-Path $metadata $file)
}
if (Test-Path -LiteralPath $localRoot) {
    $conflicts = Get-ChildItem -LiteralPath $localRoot -Directory -Force |
        Where-Object { $_.Name -like 'endstone_entity_displays-*.dist-info' -and $_.FullName -notin $acceptedMetadata }
    if ($conflicts) { throw 'Another Entity Displays version exists; refusing duplicate entry points.' }
}
$presentMetadata = @($acceptedMetadata | Where-Object { Test-Path -LiteralPath $_ })
if ($presentMetadata.Count -gt 1) {
    throw 'Both old and new loader metadata already exist; refusing duplicate entry points.'
}
$previousMetadata = if ($presentMetadata.Count) { $presentMetadata[0] } else { $metadata }
$backup = $null
if ((Test-Path -LiteralPath $package) -or (Test-Path -LiteralPath $previousMetadata)) {
    $metadataFile = Join-Path $previousMetadata 'METADATA'
    Assert-InstallPath $metadataFile
    if (-not (Test-Path -LiteralPath $metadataFile -PathType Leaf) -or
        -not ((Get-Content -LiteralPath $metadataFile -Raw) -match '(?m)^Name: endstone-entity-displays\r?$')) {
        throw 'Refusing to overwrite an unowned or incomplete plugin install.'
    }
    if ($serverRunning -and -not $StageUpdate) {
        throw 'Stop the server normally, or use -StageUpdate to stage files for its next restart.'
    }
    $backup = Join-Path $pluginRoot ('entity_displays/install-backups/' + [guid]::NewGuid().ToString('N'))
    Assert-InstallPath $backup
    New-Item -ItemType Directory -Path $backup | Out-Null
    foreach ($folder in @($package, $previousMetadata)) {
        if (Test-Path -LiteralPath $folder) { Copy-Item -LiteralPath $folder -Destination $backup -Recurse }
    }
}
New-Item -ItemType Directory -Path $package, $metadata, (Join-Path $package 'assets') -Force | Out-Null
$stagedFiles = @()
try {
    foreach ($file in $files) {
        $stage = Join-Path $package ('.ed-stage-' + [guid]::NewGuid().ToString('N') + '.tmp')
        Copy-Item -LiteralPath (Join-Path $source $file) -Destination $stage
        $stagedFiles += @{ Stage = $stage; Target = (Join-Path $package $file) }
    }
    $utf8 = [System.Text.UTF8Encoding]::new($false)
    # Generated Endstone discovery metadata; no wheel, pip or global Python changes.
    $generated = @{
        'METADATA' = "Metadata-Version: 2.1`nName: endstone-entity-displays`nVersion: 0.2.2`nSummary: Programmable block displays with transforms and special door/chest models`nRequires-Python: >=3.10`n"
        'entry_points.txt' = "[endstone]`nentity_displays = endstone_entity_displays:EntityDisplaysPlugin`n"
    }
    foreach ($file in $generated.Keys) {
        $stage = Join-Path $metadata ('.ed-stage-' + [guid]::NewGuid().ToString('N') + '.tmp')
        [System.IO.File]::WriteAllText($stage, $generated[$file], $utf8)
        $stagedFiles += @{ Stage = $stage; Target = (Join-Path $metadata $file) }
    }
    foreach ($file in $stagedFiles) {
        if (Test-Path -LiteralPath $file.Target) {
            if (-not $backup) { throw 'Unexpected existing file; refusing to replace without a backup.' }
            [System.IO.File]::Replace($file.Stage, $file.Target, (Join-Path $backup ('before-replace-' + [guid]::NewGuid().ToString('N'))))
        } else {
            [System.IO.File]::Move($file.Stage, $file.Target)
        }
    }
    if ($previousMetadata -ne $metadata -and (Test-Path -LiteralPath $previousMetadata)) {
        # Exact owned previous loader only; retain it recoverably outside .local so
        # Python discovers one entry point. Never move plugin data or worlds.
        $oldLoaderBackup = Join-Path $backup 'previous-loader-metadata'
        Assert-InstallPath $previousMetadata
        Assert-InstallPath $oldLoaderBackup
        Move-Item -LiteralPath $previousMetadata -Destination $oldLoaderBackup
    }
} finally {
    # Only remove temporary files created by this invocation, never plugin/world data.
    foreach ($file in $stagedFiles) {
        if (Test-Path -LiteralPath $file.Stage) { Remove-Item -LiteralPath $file.Stage }
    }
}
Write-Output 'Entity Displays 0.2.2 installed directly. Restart to activate protocol 2225 support. Existing resource packs are unchanged.'
Write-Output 'No running server was stopped or reloaded; no live world pack lists were changed.'
