param(
  [Parameter(Mandatory=$true)][string]$Path,
  [string]$TimestampUrl = "http://timestamp.digicert.com"
)
$ErrorActionPreference = "Stop"
if (-not $env:NPCREATE_SIGN_CERT_SHA1) {
  throw "Set NPCREATE_SIGN_CERT_SHA1 to the SHA1 thumbprint of your EV/OV code-signing certificate."
}
$signtool = "signtool.exe"
& $signtool sign /sha1 $env:NPCREATE_SIGN_CERT_SHA1 /fd SHA256 /tr $TimestampUrl /td SHA256 $Path
& $signtool verify /pa /v $Path
