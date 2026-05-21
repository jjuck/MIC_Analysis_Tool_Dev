$ErrorActionPreference = 'Stop'

param(
    [Parameter(Mandatory = $true)]
    [string]$WorkbookPath,

    [Parameter(Mandatory = $true)]
    [string]$OutputDir
)

function Get-SafeName {
    param([string]$Name)
    $invalid = [IO.Path]::GetInvalidFileNameChars()
    $safe = $Name
    foreach ($ch in $invalid) {
        $safe = $safe.Replace($ch, '_')
    }
    return $safe
}

$resolvedWorkbook = (Resolve-Path $WorkbookPath).Path
if (-not (Test-Path $OutputDir)) {
    New-Item -ItemType Directory -Path $OutputDir | Out-Null
}
$resolvedOutput = (Resolve-Path $OutputDir).Path

$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false

try {
    $workbook = $excel.Workbooks.Open($resolvedWorkbook)
    foreach ($sheet in $workbook.Worksheets) {
        $safeName = Get-SafeName $sheet.Name
        $pdfPath = Join-Path $resolvedOutput ($safeName + '.pdf')
        $sheet.ExportAsFixedFormat(0, $pdfPath)
        Write-Output ('PDF=' + $pdfPath)
    }
    $workbook.Close($false)
}
finally {
    $excel.Quit()
    [System.Runtime.Interopservices.Marshal]::ReleaseComObject($excel) | Out-Null
}
