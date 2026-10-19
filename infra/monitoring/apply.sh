#!/usr/bin/env bash
# Create or update the Hawanama Cloud Monitoring setup from the JSON files in this folder.
# Idempotent: every object is matched by displayName and patched if it exists.
# Usage: infra/monitoring/apply.sh   (needs gcloud auth with monitoring.editor on hawanama-2)
set -euo pipefail
PROJECT="${PROJECT:-hawanama-2}"
DIR="$(cd "$(dirname "$0")" && pwd)"
API="https://monitoring.googleapis.com/v3/projects/${PROJECT}"
TOKEN="$(gcloud auth print-access-token)"

call() {  # method url [body-file]
  if [[ $# -ge 3 ]]; then
    curl -sS -X "$1" -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" --data-binary @"$3" "$2"
  else
    curl -sS -X "$1" -H "Authorization: Bearer ${TOKEN}" "$2"
  fi
}

find_name() {  # collection-url list-key displayName -> resource name or empty
  call GET "$1?pageSize=200" | python3 -c '
import json, sys
key, want = sys.argv[1], sys.argv[2]
d = json.load(sys.stdin)
if "error" in d:
    sys.exit("API error: " + json.dumps(d["error"]))
print(next((x["name"] for x in d.get(key, []) if x.get("displayName") == want), ""))' "$2" "$3"
}

display() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["displayName"])' "$1"; }

upsert() {  # collection list-key file -> resource name
  local coll="$1" key="$2" file="$3" name
  name="$(find_name "${API}/${coll}" "$key" "$(display "$file")")"
  local out
  if [[ -n "$name" ]]; then
    out="$(call PATCH "https://monitoring.googleapis.com/v3/${name}" "$file")"
  else
    out="$(call POST "${API}/${coll}" "$file")"
  fi
  python3 -c '
import json, sys
d = json.loads(sys.argv[1])
if "error" in d:
    sys.exit("API error: " + json.dumps(d["error"]))
print(d["name"])' "$out"
}

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

channel="$(upsert notificationChannels notificationChannels "$DIR/channel-email.json")"
echo "channel: $channel"
check="$(upsert uptimeCheckConfigs uptimeCheckConfigs "$DIR/uptime-health-freshness.json")"
check_id="${check##*/}"
echo "uptime check: $check_id"

for f in policy-health-freshness.json policy-scheduler-failures.json policy-fire-ingest-failed.json; do
  sed -e "s#__CHANNEL__#${channel}#g" -e "s#__CHECK_ID__#${check_id}#g" "$DIR/$f" > "$tmp/$f"
  echo "policy: $(upsert alertPolicies alertPolicies "$tmp/$f")  ($(display "$DIR/$f"))"
done
