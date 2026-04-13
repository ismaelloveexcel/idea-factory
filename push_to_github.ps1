# ============================================================

# IDEA FACTORY — ONE-CLICK GITHUB PUSH (NON-TECH VERSION)

# Just run this file. It will do everything.

# ============================================================

Write-Host ""
Write-Host "PUSHING TO GITHUB..." -ForegroundColor Yellow
Write-Host ""

# --- YOUR FIXED DETAILS ---

$username = "ismaelloveexcel"
$repoName = "idea-factory"

# --- ENTER TOKEN ---

Write-Host "Paste your GitHub Token (it will be hidden):"
$token = Read-Host "Token" -AsSecureString
$tokenPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
[Runtime.InteropServices.Marshal]::SecureStringToBSTR($token)
)

# --- CREATE REPO ---

Write-Host ""
Write-Host "[1/3] Creating repo..." -ForegroundColor Cyan

$headers = @{
Authorization = "token $tokenPlain"
Accept        = "application/vnd.github.v3+json"
"User-Agent"  = "push-script"
}

$body = @{
name        = $repoName
private     = $true
} | ConvertTo-Json

try {
Invoke-RestMethod -Uri "https://api.github.com/user/repos" `
-Method POST -Headers $headers -Body $body -ContentType "application/json"
Write-Host "Repo created." -ForegroundColor Green
} catch {
Write-Host "Repo already exists. Continuing..." -ForegroundColor Yellow
}

# --- INIT + COMMIT ---

Write-Host ""
Write-Host "[2/3] Preparing files..." -ForegroundColor Cyan

git init 2>$null
git add .
git commit -m "Initial commit" 2>$null

# --- PUSH ---

Write-Host ""
Write-Host "[3/3] Pushing..." -ForegroundColor Cyan

git remote remove origin 2>$null
git remote add origin "https://${username}:${tokenPlain}@github.com/${username}/${repoName}.git"
git branch -M main
git push -u origin main

Write-Host ""
Write-Host "DONE!" -ForegroundColor Green
Write-Host "https://github.com/$username/$repoName" -ForegroundColor Yellow
Write-Host ""

Read-Host "Press Enter to close"
