# PIZZAVISION -- one-time setup for the generated-band-image bucket.
#
# Scope is intentionally narrow: this script only touches the GCS bucket
# that holds AI-generated band photos. It does NOT modify the Cloud Run
# service, Firestore, the load balancer, DNS, or anything else in the
# project's infra stack -- see deploy.ps1 for those.
#
# What it does, in order:
#   1. Enables the Cloud Storage API on the project (idempotent).
#   2. Creates gs://<project>-pizzavision-images if it doesn't exist.
#   3. Switches the bucket to fine-grained ACLs so blob.make_public()
#      works (the new bucket default is Uniform, which blocks it).
#   4. Grants the Cloud Run service account roles/storage.objectAdmin
#      on JUST this bucket (no project-level role changes).
#
# Idempotent: safe to re-run; every step checks current state first.
#
# Usage:
#   .\setup-image-bucket.ps1
#
# After running:
#   1. Add GEMINI_API_KEY and PV_GCS_BUCKET to your local .env (the script
#      prints the exact lines at the end).
#   2. Deploy: .\deploy.ps1 deploy   (deploy.ps1 threads both vars through)

$ErrorActionPreference = "Stop"

# Mirror the constants from deploy.ps1.
$PROJECT = "subgame-488302"
$REGION  = "us-central1"
$SERVICE = "pizzavision"

# GCS bucket names must be globally unique, lowercase, and DNS-compatible.
# Namespacing under the project ID gives us global uniqueness while
# staying readable.
$BUCKET = "$PROJECT-pizzavision-images"


function Write-Step {
    param([string]$Msg)
    Write-Host ""
    Write-Host "==> $Msg" -ForegroundColor Cyan
}

function Confirm-Or-Abort {
    param([string]$Prompt)
    Write-Host ""
    Write-Host $Prompt -ForegroundColor Yellow
    $resp = Read-Host "Continue? [y/N]"
    if ($resp -ne 'y' -and $resp -ne 'Y') {
        Write-Host "Aborted by user." -ForegroundColor Red
        exit 1
    }
}


Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host "  PIZZAVISION band-image bucket setup" -ForegroundColor Green
Write-Host "  Project: $PROJECT"
Write-Host "  Region:  $REGION"
Write-Host "  Bucket:  gs://$BUCKET"
Write-Host "=========================================" -ForegroundColor Green


# -------- Preflight: gcloud installed + authenticated --------
$gcloudCmd = Get-Command gcloud -ErrorAction SilentlyContinue
if (-not $gcloudCmd) {
    Write-Host "gcloud CLI not found in PATH." -ForegroundColor Red
    Write-Host "Install: https://cloud.google.com/sdk/docs/install"
    exit 1
}

$activeAccount = gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>$null
if (-not $activeAccount) {
    Write-Host "No active gcloud account. Run: gcloud auth login" -ForegroundColor Red
    exit 1
}
Write-Step "gcloud authenticated as $activeAccount"


# -------- Step 1: enable the Storage API --------
Write-Step "Enabling storage.googleapis.com (idempotent)"
gcloud services enable storage.googleapis.com --project=$PROJECT


# -------- Step 2: create the bucket (if absent) --------
# Use `list --filter` instead of `describe` for the existence check.
# `describe` exits non-zero with stderr ERROR output when the bucket is
# missing, and gcloud.ps1 surfaces that as a NativeCommandError that
# terminates the script under $ErrorActionPreference = "Stop". `list`
# returns an empty result instead -- clean exit code, no error noise.
$bucketExists = $false
$listed = gcloud storage buckets list --project=$PROJECT --filter="name=$BUCKET" --format="value(name)" 2>$null
if ($LASTEXITCODE -eq 0 -and $listed -and ($listed | Out-String).Trim()) {
    $bucketExists = $true
}

if ($bucketExists) {
    Write-Step "Bucket gs://$BUCKET already exists; skipping create"
} else {
    Confirm-Or-Abort "About to create gs://$BUCKET in $REGION."
    Write-Step "Creating bucket gs://$BUCKET"
    # --public-access-prevention=inherited lets per-object ACLs make the
    # generated PNGs publicly readable (which is what blob.make_public()
    # in image_store.py needs).
    gcloud storage buckets create "gs://$BUCKET" `
        --location=$REGION `
        --project=$PROJECT `
        --public-access-prevention=inherited
}


# -------- Step 3: make sure UBLA is off (fine-grained ACLs) --------
# gcloud storage buckets create defaults to Uniform Bucket-Level Access ON,
# which blocks blob.make_public(). Explicitly disable it (idempotent).
Write-Step "Ensuring fine-grained ACLs (Uniform Bucket-Level Access = off)"
gcloud storage buckets update "gs://$BUCKET" `
    --no-uniform-bucket-level-access `
    --project=$PROJECT


# -------- Step 4: detect the Cloud Run service account --------
Write-Step "Detecting Cloud Run service account for '$SERVICE'"
# Same wrapper-stderr issue as Step 2: if the Cloud Run service doesn't
# exist yet (first-time setup), `describe` errors out under EA=Stop.
# Temporarily relax so we can fall back to the default compute SA.
$serviceSA = $null
$prevEA = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$rawSA = gcloud run services describe $SERVICE `
    --region=$REGION `
    --project=$PROJECT `
    --format="value(spec.template.spec.serviceAccountName)" 2>$null
$serviceDescribeOk = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $prevEA

if ($serviceDescribeOk -and $rawSA -and ($rawSA | Out-String).Trim()) {
    $serviceSA = ($rawSA | Out-String).Trim()
}

if (-not $serviceSA) {
    # Cloud Run service doesn't exist yet, or it's using the default
    # Compute Engine service account. Fall back to the default.
    $projectNumber = gcloud projects describe $PROJECT --format="value(projectNumber)"
    if (-not $projectNumber) {
        Write-Host "Could not look up project number for $PROJECT" -ForegroundColor Red
        exit 1
    }
    $serviceSA = "$projectNumber-compute@developer.gserviceaccount.com"
    Write-Host "    Service has no custom SA (or doesn't exist yet)."
    Write-Host "    Using default compute SA: $serviceSA"
} else {
    Write-Host "    Found: $serviceSA"
}


# -------- Step 5: grant storage.objectAdmin on the bucket --------
Write-Step "Granting roles/storage.objectAdmin on gs://$BUCKET to the service account"
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" `
    --member="serviceAccount:$serviceSA" `
    --role="roles/storage.objectAdmin" `
    --project=$PROJECT | Out-Null
Write-Host "    Binding applied (or already present)."


# -------- Done. Print the next steps. --------
Write-Host ""
Write-Host "=========================================" -ForegroundColor Green
Write-Host "  Setup complete!" -ForegroundColor Green
Write-Host ""
Write-Host "  Bucket:          gs://$BUCKET"
Write-Host "  Service account: $serviceSA (storage.objectAdmin)"
Write-Host ""
Write-Host "  Next steps:" -ForegroundColor Yellow
Write-Host "    1. Get a Gemini API key:"
Write-Host "         https://aistudio.google.com/app/apikey"
Write-Host ""
Write-Host "    2. Add these two lines to your local .env:"
Write-Host "         GEMINI_API_KEY=...your_key..." -ForegroundColor Gray
Write-Host "         PV_GCS_BUCKET=$BUCKET" -ForegroundColor Gray
Write-Host ""
Write-Host "    3. Deploy:"
Write-Host "         .\deploy.ps1 deploy" -ForegroundColor Gray
Write-Host "       (deploy.ps1 reads .env and threads both vars into"
Write-Host "        the Cloud Run service automatically.)"
Write-Host "========================================="
Write-Host ""
