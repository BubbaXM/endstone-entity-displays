$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$fixtureParent = (Resolve-Path -LiteralPath (Join-Path $project 'tests')).Path
$fixture = Join-Path $fixtureParent ('installer-fixture-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $fixture | Out-Null
try {
    # Generated test server, never the real bedrock_server folder.
    [System.IO.File]::WriteAllText((Join-Path $fixture 'server.properties'), "level-name=Fixture`n")
    & (Join-Path $project 'install.ps1') -Server $fixture -StageUpdate
    $local = Join-Path $fixture 'plugins/.local'
    $new = Join-Path $local 'endstone_entity_displays-0.2.2.dist-info'
    $expectedBackups = 0
    foreach ($version in @('0.1.0', '0.2.0', '0.2.1')) {
        $old = Join-Path $local "endstone_entity_displays-$version.dist-info"
        $absoluteNew = [System.IO.Path]::GetFullPath($new)
        $absoluteOld = [System.IO.Path]::GetFullPath($old)
        foreach ($path in @($absoluteNew, $absoluteOld)) {
            if (-not $path.StartsWith($fixture + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw 'Fixture metadata path escaped its isolated directory.'
            }
        }
        Move-Item -LiteralPath $absoluteNew -Destination $absoluteOld
        [System.IO.File]::WriteAllText((Join-Path $old 'METADATA'), "Metadata-Version: 2.1`nName: endstone-entity-displays`nVersion: $version`n")
        & (Join-Path $project 'install.ps1') -Server $fixture -StageUpdate
        if ((Test-Path -LiteralPath $old) -or -not (Test-Path -LiteralPath $new)) { throw 'Loader migration failed.' }
        $backups = @(Get-ChildItem -LiteralPath (Join-Path $fixture 'plugins/entity_displays/install-backups') -Directory)
        $expectedBackups++
        if ($backups.Count -ne $expectedBackups -or @($backups | Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'previous-loader-metadata/METADATA') }).Count -ne $expectedBackups) {
            throw 'Recoverable old loader backup missing.'
        }
        if (@(Get-ChildItem -LiteralPath $local -Directory | Where-Object { $_.Name -like 'endstone_entity_displays-*.dist-info' }).Count -ne 1) {
            throw 'Duplicate loader metadata after upgrade.'
        }
    }
    if (Test-Path -LiteralPath (Join-Path $fixture 'worlds')) { throw 'Installer unexpectedly changed world files.' }
    Write-Output 'Isolated fresh install and 0.1/0.2-to-0.2.2 loader migrations verified; backups kept outside discovery path.'
} finally {
    # Only this invocation's GUID fixture is removed, after resolving and checking
    # the exact absolute target remains inside this project's tests directory.
    $resolved = (Resolve-Path -LiteralPath $fixture).Path
    if (-not $resolved.StartsWith($fixtureParent + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase) -or
        (Split-Path -Leaf $resolved) -notlike 'installer-fixture-*') {
        throw 'Refusing unsafe fixture cleanup.'
    }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
