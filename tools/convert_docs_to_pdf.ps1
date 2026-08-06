# ---------------------------------------------------------------------------
# convert_docs_to_pdf.ps1
#
# Browsers cannot embed .docx or .pptx, so every attached Office document needs
# a PDF rendition sitting next to it. build.py looks for "<same name>.pdf" in
# the same folder and embeds that; without it the document degrades to a plain
# download button and the build prints a warning.
#
# Run this from the repo root after adding or replacing any .docx / .pptx that
# a project attaches, then commit the generated PDFs:
#
#     powershell -ExecutionPolicy Bypass -File tools/convert_docs_to_pdf.ps1
#
# Requires Microsoft Word / PowerPoint on the machine (COM automation). It is a
# Windows-only convenience, NOT part of the build — build.py stays pure stdlib
# and runs anywhere. On other platforms use LibreOffice instead:
#
#     soffice --headless --convert-to pdf --outdir files "files/Some Report.docx"
#
# Existing PDFs are skipped unless the source is newer, so re-running is cheap.
# ---------------------------------------------------------------------------

param([switch]$Force)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$searchDirs = @('files', 'thesis', 'projects/src')

$wdFormatPDF  = 17
$ppSaveAsPDF  = 32

$docs = @()
foreach ($d in $searchDirs) {
    $full = Join-Path $root $d
    if (Test-Path $full) {
        $docs += Get-ChildItem -Path $full -Recurse -File -Include *.docx, *.doc, *.pptx, *.ppt
    }
}

if (-not $docs) { "No Office documents found."; exit 0 }

$word = $null
$ppt  = $null
$made = 0
$skipped = 0

try {
    foreach ($doc in $docs) {
        $pdf = [IO.Path]::ChangeExtension($doc.FullName, '.pdf')
        if ((Test-Path $pdf) -and -not $Force -and
            (Get-Item $pdf).LastWriteTime -ge $doc.LastWriteTime) {
            $skipped++
            continue
        }

        $rel = $doc.FullName.Substring($root.Length + 1)
        "converting $rel"

        if ($doc.Extension -match '^\.docx?$') {
            if ($null -eq $word) {
                $word = New-Object -ComObject Word.Application
                $word.Visible = $false
                $word.DisplayAlerts = 0
            }
            $d = $word.Documents.Open($doc.FullName, $false, $true)  # ReadOnly
            try   { $d.ExportAsFixedFormat($pdf, $wdFormatPDF) }
            finally { $d.Close($false) }
        }
        else {
            if ($null -eq $ppt) {
                $ppt = New-Object -ComObject PowerPoint.Application
            }
            $p = $ppt.Presentations.Open($doc.FullName, $true, $false, $false)
            try   { $p.SaveAs($pdf, $ppSaveAsPDF) }
            finally { $p.Close() }
        }
        $made++
    }
}
finally {
    if ($word) { $word.Quit() }
    if ($ppt)  { $ppt.Quit() }
}

"$made converted, $skipped already current"
