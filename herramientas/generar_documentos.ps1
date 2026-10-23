<#
.SYNOPSIS
    Regenera los documentos de docs/ en .docx y .pdf desde el markdown.

.DESCRIPTION
    Encadena los tres pasos, en este orden y no en otro:

      1. expandir_codigo.py  inserta el código real del repositorio dentro
                             de los .md, en docs/generado/
      2. md_a_docx.py        convierte esos .md a .docx en docs/entregables/
      3. docx_a_pdf.py       exporta cada .docx a .pdf con Word por COM

    POR QUE ESE ORDEN: si editas un archivo de código y regeneras sin el
    paso 1, el documento seguiría llevando el código viejo. El paso 1 es lo que
    garantiza que la guía no pueda mentir sobre el código.

.NOTES
    Cierra Word antes de ejecutarlo. Si tienes uno de los .docx abierto, el
    paso 2 fallará con "Permission denied" al intentar sobrescribirlo.
#>

$ErrorActionPreference = "Stop"
$Base = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $Base ".venv-docs\Scripts\python.exe"

# El .venv de este proyecto es el de la Raspberry Pi (Linux, aarch64). La cadena
# de documentos corre en el portatil -- necesita Word por COM -- con su propio
# entorno de Windows, .venv-docs, que no se versiona.
if ($env:RICEVI_PY_DOCS) { $Py = $env:RICEVI_PY_DOCS }
if (-not (Test-Path $Py)) {
    Write-Host "No hay entorno de Python con python-docx, pywin32 y pillow." -ForegroundColor Red
    Write-Host "Créalo con: py -3.11 -m venv .venv-docs ; .\.venv-docs\Scripts\pip install python-docx pywin32 pillow"
    exit 1
}

Write-Host "1/3  Insertando el código en los capítulos..." -ForegroundColor Cyan
& $Py (Join-Path $Base "herramientas\expandir_codigo.py")
if ($LASTEXITCODE -ne 0) { Write-Host "Faltan archivos de código." -ForegroundColor Red; exit 1 }

Write-Host "`n2/3  Generando .docx..." -ForegroundColor Cyan
& $Py (Join-Path $Base "herramientas\md_a_docx.py")
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "`n3/3  Exportando a .pdf con Word..." -ForegroundColor Cyan
& $Py (Join-Path $Base "herramientas\docx_a_pdf.py")
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "`nListo." -ForegroundColor Green
Get-ChildItem (Join-Path $Base "docs\entregables") | Sort-Object Name |
    Format-Table Name, @{n="KB";e={[math]::Round($_.Length/1KB)}}, LastWriteTime -AutoSize