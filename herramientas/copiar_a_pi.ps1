<#
.SYNOPSIS
    Envia el proyecto de campo a la Raspberry Pi por scp.

.DESCRIPTION
    Copia lo que la Pi necesita y NADA MAS. Lo que se excluye y por que:

      .venv/          se crea en la Pi; el del portatil es de Windows/x86
      datos/          es el dataset: viaja al reves, de la Pi al respaldo
      tokens.json     se genera en la Pi y no debe pasearse por la red
      modelos/pesos/  binarios grandes; se copian aparte y a proposito
      .git/           no hace falta en campo

.EXAMPLE
    .\herramientas\copiar_a_pi.ps1
    .\herramientas\copiar_a_pi.ps1 -Host 192.168.40.2
#>

param(
    [string]$Equipo = "ricevi-rasp-01.local",
    [string]$Usuario = "ricevi-rasp",
    [string]$Destino = "~/config-ricevi-campo",
    [switch]$ConPesos
)

$ErrorActionPreference = "Stop"
$Raiz = Split-Path -Parent $PSScriptRoot
Set-Location $Raiz

Write-Host "Enviando a $Usuario@$Equipo`:$Destino" -ForegroundColor Cyan

# Se prueba el enlace antes de copiar: un scp que falla a mitad deja el
# proyecto en un estado a medias que es peor que no haber empezado.
Write-Host "  comprobando el enlace..." -NoNewline
$prueba = ssh -o ConnectTimeout=5 -o BatchMode=no "$Usuario@$Equipo" "echo ok" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host " FALLO" -ForegroundColor Red
    Write-Host "  No se llega a $Equipo." -ForegroundColor Red
    Write-Host "  Comprueba, en este orden: la Pi encendida, la misma red,"
    Write-Host "  mDNS resolviendo (ping $Equipo), y el aislamiento de clientes"
    Write-Host "  DESACTIVADO en el punto de acceso."
    exit 1
}
Write-Host " OK" -ForegroundColor Green

ssh "$Usuario@$Equipo" "mkdir -p $Destino"

$carpetas = @("central", "config", "modelos", "nodos", "herramientas", "docs")
$sueltos  = @("README.md", ".gitignore")
$incluir  = @($carpetas + $sueltos | Where-Object { Test-Path $_ })

# Se empaqueta en un archivo local y se envia con scp. NO con
# "tar -cf - | ssh": en Windows PowerShell 5.1 la tuberia entre dos programas
# externos pasa los datos como texto y corrompe el tar ("Esto no parece un
# archivo tar" en la Pi).
$excluir = @("--exclude=__pycache__", "--exclude=*.pyc", "--exclude=.venv")
if (-not $ConPesos) { $excluir += "--exclude=modelos/pesos" }
$paquete = Join-Path $env:TEMP "ricevi_envio.tar"
Remove-Item $paquete -ErrorAction SilentlyContinue

Write-Host "  empaquetando $($incluir -join ', ')..." -NoNewline
tar -cf $paquete @excluir @incluir
if ($LASTEXITCODE -ne 0) { Write-Host " FALLO" -ForegroundColor Red; exit 1 }
Write-Host (" OK ({0:N1} MB)" -f ((Get-Item $paquete).Length / 1MB)) -ForegroundColor Green

Write-Host "  enviando..." -NoNewline
scp -q $paquete "$Usuario@$Equipo`:/tmp/ricevi_envio.tar"
if ($LASTEXITCODE -ne 0) { Write-Host " FALLO" -ForegroundColor Red; exit 1 }
Write-Host " OK" -ForegroundColor Green

Write-Host "  desempaquetando en la Pi..." -NoNewline
ssh "$Usuario@$Equipo" "tar -xf /tmp/ricevi_envio.tar -C $Destino && rm /tmp/ricevi_envio.tar && chmod +x $Destino/herramientas/*.sh"
if ($LASTEXITCODE -ne 0) { Write-Host " FALLO" -ForegroundColor Red; exit 1 }
Write-Host " OK" -ForegroundColor Green
Remove-Item $paquete -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Copiado." -ForegroundColor Green
if (-not $ConPesos) {
    Write-Host "Los pesos de los modelos NO se copiaron (usa -ConPesos si ya los tienes)." -ForegroundColor Yellow
}
Write-Host ""
Write-Host "Siguiente paso:"
Write-Host "  ssh -t $Usuario@$Equipo `"$Destino/herramientas/instalar_pi.sh`""
