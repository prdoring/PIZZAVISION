# PIZZAVISION -- Cloud Run deployment & management (PowerShell)
# Usage: .\deploy.ps1 <command>
#
# Modeled on Sub Game's deploy.ps1. The pizzavision service lives in the SAME
# GCP project as Sub Game (subgame-488302) and shares the existing load
# balancer (sub-game-https-proxy / sub-game-urlmap). All "shared resource"
# modifications are additive and guarded -- see the setup-subdomain block.

$ErrorActionPreference = "Stop"

$PROJECT = "subgame-488302"
$REGION = "us-central1"
$SERVICE = "pizzavision"
$SUBDOMAIN = "pizzavision.patssubgame.com"

# Sub Game LB resource names we attach to (do not modify these directly)
$SHARED_PROXY = "sub-game-https-proxy"
$SHARED_URLMAP = "sub-game-urlmap"
$SHARED_CERT = "sub-game-cert"
$ROOT_DOMAIN = "patssubgame.com"

# New resources we own
$NEG_NAME = "pizzavision-neg"
$BACKEND_NAME = "pizzavision-backend"
$CERT_NAME = "pizzavision-cert"
$PATH_MATCHER = "pizzavision-matcher"

function Print-Url {
    $url = gcloud run services describe $SERVICE `
        --region=$REGION `
        --project=$PROJECT `
        --format="value(status.url)"
    Write-Host ""
    Write-Host "========================================="
    Write-Host "  PIZZAVISION is live at:"
    Write-Host "  $url"
    Write-Host "  Custom domain (after setup-subdomain + DNS):"
    Write-Host "  https://$SUBDOMAIN"
    Write-Host "========================================="
    Write-Host ""
}

function Read-EnvFile {
    param([string]$Path = ".env")
    $out = @{}
    if (-not (Test-Path $Path)) { return $out }
    foreach ($line in Get-Content $Path) {
        $t = $line.Trim()
        if (-not $t -or $t.StartsWith("#")) { continue }
        $i = $t.IndexOf("=")
        if ($i -lt 1) { continue }
        $k = $t.Substring(0, $i).Trim()
        $v = $t.Substring($i + 1).Trim()
        if (($v.StartsWith('"') -and $v.EndsWith('"')) -or
            ($v.StartsWith("'") -and $v.EndsWith("'"))) {
            $v = $v.Substring(1, $v.Length - 2)
        }
        $out[$k] = $v
    }
    return $out
}

function Get-DeployEnvVars {
    # Build the comma-joined string for `gcloud run deploy --set-env-vars`.
    # Harvests keys from the local .env so we don't have to maintain them
    # separately in Secret Manager.
    #
    # Hard-required: OPENAI_API_KEY (onboarding name generator breaks without it).
    # Soft-optional: GEMINI_API_KEY and PV_GCS_BUCKET (band-image feature
    # degrades to the skip path if either is missing; rest of the app still
    # works). Warn but don't abort if those two aren't set yet.
    $envFile = Read-EnvFile ".env"
    if (-not $envFile.ContainsKey("OPENAI_API_KEY") -or -not $envFile["OPENAI_API_KEY"]) {
        Write-Host ""
        Write-Host "!! ABORT -- OPENAI_API_KEY not found in .env"
        Write-Host "   Create .env in the project root with:"
        Write-Host "     OPENAI_API_KEY=sk-..."
        Write-Host ""
        exit 1
    }
    $key = $envFile["OPENAI_API_KEY"]
    $pairs = @(
        "GOOGLE_CLOUD_PROJECT=$PROJECT",
        "OPENAI_API_KEY=$key"
    )

    if ($envFile.ContainsKey("GEMINI_API_KEY") -and $envFile["GEMINI_API_KEY"]) {
        $pairs += "GEMINI_API_KEY=$($envFile['GEMINI_API_KEY'])"
    } else {
        Write-Host "   (warn) GEMINI_API_KEY not in .env -- band-image feature will fall back to skip."
    }

    if ($envFile.ContainsKey("PV_GCS_BUCKET") -and $envFile["PV_GCS_BUCKET"]) {
        $pairs += "PV_GCS_BUCKET=$($envFile['PV_GCS_BUCKET'])"
    } else {
        Write-Host "   (warn) PV_GCS_BUCKET not in .env -- generated images would land in container fs (lost on restart). Run .\setup-image-bucket.ps1."
    }

    return ($pairs -join ',')
}

function Assert-SubGameStillServes {
    # Mid-flight safety check during shared-resource mutations.
    try {
        $resp = Invoke-WebRequest "https://$ROOT_DOMAIN" -UseBasicParsing -TimeoutSec 10
        if ($resp.StatusCode -ge 200 -and $resp.StatusCode -lt 400) {
            Write-Host "  OK -- https://$ROOT_DOMAIN still serving (HTTP $($resp.StatusCode))"
            return
        }
        throw "patssubgame.com returned HTTP $($resp.StatusCode)"
    } catch {
        Write-Host ""
        Write-Host "!! ABORT -- https://$ROOT_DOMAIN appears broken: $_"
        Write-Host "!! Run rollback commands shown in the plan or .\deploy.ps1 teardown-subdomain"
        throw
    }
}

$command = if ($args.Count -gt 0) { $args[0] } else { "help" }
$commitArg = if ($args.Count -gt 1) { $args[1] } else { $null }

switch ($command) {
    "deploy" {
        Write-Host "Building and deploying PIZZAVISION to Cloud Run..."
        $envVars = Get-DeployEnvVars
        gcloud run deploy $SERVICE `
            --source=. `
            --region=$REGION `
            --project=$PROJECT `
            --allow-unauthenticated `
            --port=8080 `
            --session-affinity `
            --min-instances=0 `
            --max-instances=1 `
            --timeout=3600 `
            --cpu=1 `
            --memory=512Mi `
            --set-env-vars $envVars
        Print-Url
    }

    "start" {
        Write-Host "Starting PIZZAVISION (resuming traffic)..."
        gcloud run services update-traffic $SERVICE `
            --region=$REGION `
            --project=$PROJECT `
            --to-latest
        Print-Url
    }

    "stop" {
        Write-Host "Stopping PIZZAVISION (scaling to zero, no traffic)..."
        gcloud run services update $SERVICE `
            --region=$REGION `
            --project=$PROJECT `
            --no-traffic
        Write-Host "Service stopped. No instances running, no traffic served."
    }

    "restart" {
        Write-Host "Restarting PIZZAVISION (deploying new revision from same image)..."
        $image = gcloud run services describe $SERVICE `
            --region=$REGION `
            --project=$PROJECT `
            --format="value(spec.template.spec.containers[0].image)"
        $envVars = Get-DeployEnvVars
        gcloud run deploy $SERVICE `
            --region=$REGION `
            --project=$PROJECT `
            --image=$image `
            --allow-unauthenticated `
            --port=8080 `
            --session-affinity `
            --min-instances=0 `
            --max-instances=1 `
            --timeout=3600 `
            --cpu=1 `
            --memory=512Mi `
            --set-env-vars $envVars
        Print-Url
    }

    "status" {
        Write-Host "PIZZAVISION service status:"
        Write-Host ""
        gcloud run services describe $SERVICE `
            --region=$REGION `
            --project=$PROJECT `
            --format=yaml
    }

    "logs" {
        Write-Host "Recent logs for PIZZAVISION:"
        gcloud logging read `
            "resource.type=cloud_run_revision AND resource.labels.service_name=$SERVICE" `
            --project=$PROJECT `
            --limit=50 `
            --format="table(timestamp, textPayload)" `
            --freshness=1h
    }

    "url" {
        Print-Url
    }

    "setup-subdomain" {
        Write-Host "Setting up subdomain $SUBDOMAIN on the existing Sub Game load balancer..."
        Write-Host "This shares infrastructure with Sub Game. All changes are additive and"
        Write-Host "guarded -- patssubgame.com is checked between each shared-resource update."
        Write-Host ""

        # Step 0 -- Snapshot the shared resources we're about to modify.
        $ts = Get-Date -Format "yyyyMMdd-HHmmss"
        if (-not (Test-Path backup)) { New-Item -ItemType Directory backup | Out-Null }
        Write-Host "==> Snapshotting shared LB config to backup/..."
        gcloud compute url-maps export $SHARED_URLMAP `
            --destination="backup/$SHARED_URLMAP-$ts.yaml" `
            --project=$PROJECT --global 2>&1 | Write-Host
        gcloud compute target-https-proxies describe $SHARED_PROXY `
            --project=$PROJECT --format=yaml `
            | Out-File -Encoding utf8 "backup/$SHARED_PROXY-$ts.yaml"
        Write-Host "    Snapshots written:"
        Write-Host "      backup/$SHARED_URLMAP-$ts.yaml"
        Write-Host "      backup/$SHARED_PROXY-$ts.yaml"

        # Allow "already exists" failures on creation steps without stopping.
        $ErrorActionPreference = "Continue"

        Write-Host "==> Creating Serverless NEG ($NEG_NAME)..."
        gcloud compute network-endpoint-groups create $NEG_NAME `
            --region=$REGION `
            --network-endpoint-type=serverless `
            --cloud-run-service=$SERVICE `
            --project=$PROJECT 2>&1 | Write-Host

        Write-Host "==> Creating backend service ($BACKEND_NAME)..."
        # NOTE: do NOT pass --timeout here. Serverless NEGs reject backend-level
        # timeoutSec, and add-backend below will silently fail if it's set.
        # WebSocket lifetime is governed by the Cloud Run --timeout=3600 on the
        # service itself, not by the load balancer.
        gcloud compute backend-services create $BACKEND_NAME `
            --global `
            --load-balancing-scheme=EXTERNAL_MANAGED `
            --project=$PROJECT 2>&1 | Write-Host

        Write-Host "==> Adding NEG to backend service..."
        gcloud compute backend-services add-backend $BACKEND_NAME `
            --global `
            --network-endpoint-group=$NEG_NAME `
            --network-endpoint-group-region=$REGION `
            --project=$PROJECT 2>&1 | Write-Host

        Write-Host "==> Creating Google-managed SSL cert ($CERT_NAME) for $SUBDOMAIN..."
        gcloud compute ssl-certificates create $CERT_NAME `
            --domains=$SUBDOMAIN `
            --global `
            --project=$PROJECT 2>&1 | Write-Host

        $ErrorActionPreference = "Stop"

        # Step 4 -- Read-then-update the proxy cert list (defensive).
        Write-Host "==> Reading current cert list on $SHARED_PROXY..."
        $currentCerts = gcloud compute target-https-proxies describe $SHARED_PROXY `
            --project=$PROJECT `
            --format="value(sslCertificates)"
        Write-Host "    Current: $currentCerts"

        if ($currentCerts -notmatch $SHARED_CERT) {
            throw "Safety abort: $SHARED_CERT is not currently on $SHARED_PROXY. Investigate before continuing."
        }
        if ($currentCerts -match $CERT_NAME) {
            Write-Host "    $CERT_NAME already attached; skipping cert-list update."
        } else {
            # The describe output uses fully-qualified URLs (one per cert). Parse to short names.
            $certNames = ($currentCerts -split "[;\s]+" | Where-Object { $_ } | ForEach-Object {
                ($_ -split '/')[-1]
            }) -join ","
            $newList = "$certNames,$CERT_NAME"
            Write-Host "    Updating to: $newList"
            gcloud compute target-https-proxies update $SHARED_PROXY `
                --ssl-certificates=$newList `
                --global-ssl-certificates `
                --project=$PROJECT
        }

        Write-Host "==> Verifying $ROOT_DOMAIN still serves after cert update..."
        Assert-SubGameStillServes

        # Step 5 -- Additive URL-map host rule.
        Write-Host "==> Checking URL map for existing path matcher..."
        $existingMatcher = gcloud compute url-maps describe $SHARED_URLMAP `
            --project=$PROJECT --format="value(pathMatchers.name)"
        if ($existingMatcher -match $PATH_MATCHER) {
            Write-Host "    $PATH_MATCHER already exists; skipping add-path-matcher."
        } else {
            Write-Host "==> Adding path matcher to URL map (additive -- default route untouched)..."
            gcloud compute url-maps add-path-matcher $SHARED_URLMAP `
                --path-matcher-name=$PATH_MATCHER `
                --default-service=$BACKEND_NAME `
                --new-hosts=$SUBDOMAIN `
                --project=$PROJECT
        }

        Write-Host "==> Verifying $ROOT_DOMAIN still serves after URL-map update..."
        Assert-SubGameStillServes

        $staticIp = gcloud compute addresses describe sub-game-ip `
            --global --project=$PROJECT --format="value(address)" 2>$null

        Write-Host ""
        Write-Host "========================================="
        Write-Host "  Subdomain setup complete!"
        Write-Host ""
        Write-Host "  Next steps at Squarespace DNS:"
        Write-Host "    Add CNAME:  pizzavision -> $ROOT_DOMAIN."
        Write-Host "  (or A record: pizzavision -> $staticIp)"
        Write-Host ""
        Write-Host "  Then wait 15-60 min for the cert to provision."
        Write-Host "  Check status:  .\deploy.ps1 subdomain-status"
        Write-Host "========================================="
        Write-Host ""
    }

    "subdomain-status" {
        Write-Host "Subdomain status for $SUBDOMAIN"
        Write-Host ""

        Write-Host "==> SSL Certificate:"
        try {
            gcloud compute ssl-certificates describe $CERT_NAME `
                --global --project=$PROJECT `
                --format="table(name, type, managed.status, managed.domainStatus)"
        } catch {
            Write-Host "    NOT FOUND -- run .\deploy.ps1 setup-subdomain"
        }
        Write-Host ""

        Write-Host "==> URL map host rule:"
        $hosts = gcloud compute url-maps describe $SHARED_URLMAP `
            --project=$PROJECT --format="value(hostRules)" 2>$null
        if ($hosts -match $SUBDOMAIN) {
            Write-Host "    OK -- $SUBDOMAIN routes to $BACKEND_NAME"
        } else {
            Write-Host "    NOT FOUND -- run .\deploy.ps1 setup-subdomain"
        }
        Write-Host ""

        Write-Host "==> Live check:"
        try {
            $resp = Invoke-WebRequest "https://$SUBDOMAIN" -UseBasicParsing -TimeoutSec 10
            Write-Host "    HTTP $($resp.StatusCode) -- subdomain is live"
        } catch {
            Write-Host "    Not reachable yet (cert provisioning or DNS): $_"
        }
        Write-Host ""
    }

    "teardown-subdomain" {
        Write-Host "Removing pizzavision.patssubgame.com routing (LEAVES Sub Game intact)..."
        Write-Host ""

        $ErrorActionPreference = "Continue"

        # Reverse step 5: drop the URL map host rule.
        Write-Host "==> Removing path matcher from URL map..."
        gcloud compute url-maps remove-path-matcher $SHARED_URLMAP `
            --path-matcher-name=$PATH_MATCHER `
            --project=$PROJECT --quiet 2>$null

        # Reverse step 4: detach pizzavision-cert from the proxy (keep sub-game-cert).
        Write-Host "==> Reverting proxy to $SHARED_CERT only..."
        gcloud compute target-https-proxies update $SHARED_PROXY `
            --ssl-certificates=$SHARED_CERT `
            --global-ssl-certificates `
            --project=$PROJECT 2>&1 | Write-Host

        Assert-SubGameStillServes

        # Delete our owned resources.
        Write-Host "==> Deleting $CERT_NAME..."
        gcloud compute ssl-certificates delete $CERT_NAME --global --project=$PROJECT --quiet 2>$null
        Write-Host "==> Removing NEG from backend service..."
        gcloud compute backend-services remove-backend $BACKEND_NAME `
            --global --network-endpoint-group=$NEG_NAME `
            --network-endpoint-group-region=$REGION `
            --project=$PROJECT --quiet 2>$null
        Write-Host "==> Deleting backend service $BACKEND_NAME..."
        gcloud compute backend-services delete $BACKEND_NAME --global --project=$PROJECT --quiet 2>$null
        Write-Host "==> Deleting NEG $NEG_NAME..."
        gcloud compute network-endpoint-groups delete $NEG_NAME --region=$REGION --project=$PROJECT --quiet 2>$null

        $ErrorActionPreference = "Stop"

        Write-Host ""
        Write-Host "Teardown complete. Sub Game's LB is unchanged."
        Write-Host "The Cloud Run service '$SERVICE' is untouched -- use .\deploy.ps1 stop / start to manage it."
        Write-Host ""
    }

    "rollback" {
        if (-not $commitArg) {
            Write-Host "Usage: .\deploy.ps1 rollback [commit-hash]"
            Write-Host ""
            Write-Host "Deploys a specific git commit to Cloud Run."
            Write-Host "Stashes local changes, checks out the commit, deploys, then restores."
            exit 1
        }

        $resolvedCommit = git rev-parse --verify $commitArg 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Error: '$commitArg' is not a valid commit."
            exit 1
        }
        $shortHash = $resolvedCommit.Substring(0, 8)
        $commitMsg = git log -1 --format="%s" $resolvedCommit
        Write-Host "Rollback target: $shortHash - $commitMsg"

        $originalRef = git symbolic-ref --short HEAD 2>$null
        if (-not $originalRef) { $originalRef = git rev-parse HEAD }

        $stashBefore = (git stash list | Measure-Object).Count
        git stash push -u -m "deploy-rollback: auto-stash before deploying $shortHash"
        $didStash = ((git stash list | Measure-Object).Count) -gt $stashBefore

        git checkout $resolvedCommit --quiet 2>&1 | Out-Null

        $envVars = Get-DeployEnvVars
        try {
            gcloud run deploy $SERVICE `
                --source=. `
                --region=$REGION `
                --project=$PROJECT `
                --allow-unauthenticated `
                --port=8080 `
                --session-affinity `
                --min-instances=0 `
                --max-instances=1 `
                --timeout=3600 `
                --cpu=1 `
                --memory=512Mi `
                --set-env-vars $envVars
            Print-Url
        } finally {
            git checkout $originalRef --quiet 2>&1 | Out-Null
            if ($didStash) { git stash pop --quiet }
            Write-Host "Back on $originalRef."
        }
    }

    default {
        Write-Host "PIZZAVISION Cloud Run Manager"
        Write-Host ""
        Write-Host "Usage: .\deploy.ps1 [command]"
        Write-Host ""
        Write-Host "Commands:"
        Write-Host "  deploy              Build from source and deploy to Cloud Run"
        Write-Host "  start               Resume traffic to the service"
        Write-Host "  stop                Stop serving traffic (scales to zero)"
        Write-Host "  restart             Deploy new revision with same image (fresh instance)"
        Write-Host "  status              Show service status and URL"
        Write-Host "  logs                Show recent server logs"
        Write-Host "  url                 Print the public URL"
        Write-Host "  rollback [hash]     Deploy a specific commit"
        Write-Host ""
        Write-Host "Subdomain ($SUBDOMAIN):"
        Write-Host "  setup-subdomain     Add pizzavision-cert + host rule to Sub Game's LB"
        Write-Host "  subdomain-status    Check cert + URL-map + live status"
        Write-Host "  teardown-subdomain  Remove only the new resources; leaves Sub Game intact"
        Write-Host ""
        Write-Host "  help                Show this help message"
    }
}
