#!/usr/bin/env bash
# Create or update what GitHub Actions needs to deploy Hawanama. No keys are stored: workflows
# running on main of PakAirQuality/paqi_hawanama exchange their OIDC token for the deployer account.
# Idempotent. Usage: infra/ci/apply.sh   (needs gcloud auth with owner on hawanama-2)
set -euo pipefail
PROJECT="${PROJECT:-hawanama-2}"
NUMBER=152782825429
REPO_ID=1179618537  # the numeric ID of PakAirQuality/paqi_hawanama: a name can be re-registered
POOL=github
PROVIDER=paqi-hawanama
SA="github-deployer@${PROJECT}.iam.gserviceaccount.com"
BUILD_SA="${NUMBER}-compute@developer.gserviceaccount.com"
BUCKET=gs://hawanama-2-ci-builds
DIR="$(cd "$(dirname "$0")" && pwd)"

gcloud services enable sts.googleapis.com --project "$PROJECT"

gcloud iam service-accounts describe "$SA" --project "$PROJECT" >/dev/null 2>&1 ||
  gcloud iam service-accounts create github-deployer --project "$PROJECT" \
    --display-name "GitHub Actions deployer"

gcloud iam workload-identity-pools describe "$POOL" --location global --project "$PROJECT" >/dev/null 2>&1 ||
  gcloud iam workload-identity-pools create "$POOL" --location global --project "$PROJECT" \
    --display-name "GitHub Actions"

CONDITION="assertion.repository_id=='${REPO_ID}' && assertion.ref=='refs/heads/main'"
MAPPING="google.subject=assertion.sub,attribute.repository_id=assertion.repository_id,attribute.ref=assertion.ref"
if gcloud iam workload-identity-pools providers describe "$PROVIDER" --workload-identity-pool "$POOL" \
    --location global --project "$PROJECT" >/dev/null 2>&1; then
  ACTION=update-oidc
else
  ACTION=create-oidc
fi
gcloud iam workload-identity-pools providers "$ACTION" "$PROVIDER" --workload-identity-pool "$POOL" \
  --location global --project "$PROJECT" --issuer-uri https://token.actions.githubusercontent.com \
  --attribute-mapping "$MAPPING" --attribute-condition "$CONDITION"

# Bound by repository, not subject: jobs in a GitHub Environment drop the ref from `sub`.
gcloud iam service-accounts add-iam-policy-binding "$SA" --project "$PROJECT" --quiet \
  --role roles/iam.workloadIdentityUser --condition None \
  --member "principalSet://iam.googleapis.com/projects/${NUMBER}/locations/global/workloadIdentityPools/${POOL}/attribute.repository_id/${REPO_ID}" \
  >/dev/null

for role in cloudbuild.builds.editor serviceusage.serviceUsageConsumer firebasehosting.admin run.viewer serviceusage.apiKeysViewer; do
  gcloud projects add-iam-policy-binding "$PROJECT" --quiet --condition None \
    --member "serviceAccount:${SA}" --role "roles/${role}" >/dev/null
done

# Source uploads and build logs go to a dedicated bucket so the deployer needs no project Viewer.
gcloud storage buckets describe "$BUCKET" >/dev/null 2>&1 ||
  gcloud storage buckets create "$BUCKET" --project "$PROJECT" --location asia-south1 \
    --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update "$BUCKET" --lifecycle-file "$DIR/bucket-lifecycle.json"
for member in "$SA" "$BUILD_SA"; do
  gcloud storage buckets add-iam-policy-binding "$BUCKET" --quiet \
    --member "serviceAccount:${member}" --role roles/storage.objectAdmin >/dev/null
done
gcloud storage buckets add-iam-policy-binding "$BUCKET" --quiet \
  --member "serviceAccount:${SA}" --role roles/storage.legacyBucketReader >/dev/null

echo "Ready: ${SA} via projects/${NUMBER}/locations/global/workloadIdentityPools/${POOL}/providers/${PROVIDER}"
