#!/bin/sh
# Notarize and staple the packed app. Credentials stay in the keychain: NOTARY_PROFILE names a
# profile made with `xcrun notarytool store-credentials`; nothing secret is read or printed here.
# Usage: NOTARY_PROFILE=<profile> npm run notarize [-- "path/to/FA Foundry.app"]
set -eu
APP="${1:-release/mac-arm64/FA Foundry.app}"
PROFILE="${NOTARY_PROFILE:?set NOTARY_PROFILE to a notarytool keychain profile}"
WORK="$(mktemp -d)"
ZIP="$WORK/FA-Foundry-notarize.zip"

codesign --verify --deep --strict --verbose=2 "$APP"
ditto -c -k --keepParent "$APP" "$ZIP"
xcrun notarytool submit "$ZIP" --keychain-profile "$PROFILE" --wait --output-format json > "$WORK/submit.json"
cat "$WORK/submit.json"
if ! grep -q '"status":"Accepted"' "$WORK/submit.json"; then
  ID="$(sed -n 's/.*"id":"\([^"]*\)".*/\1/p' "$WORK/submit.json")"
  echo "notarization was not accepted; log follows" >&2
  [ -n "$ID" ] && xcrun notarytool log "$ID" --keychain-profile "$PROFILE" >&2
  exit 1
fi
xcrun stapler staple "$APP"
xcrun stapler validate "$APP"
spctl --assess --type execute --verbose=2 "$APP"
