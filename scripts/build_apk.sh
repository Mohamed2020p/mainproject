#!/usr/bin/env bash
#
# build_apk.sh - build the IL2CPP Dumper Studio Android APK.
#
# Requires: JDK 17+, Android SDK (platform 34 + build-tools), and either the
# Gradle wrapper or a local Gradle 8.x.  This sandbox has none of those, which is
# why the exact commands to get them are also written in ../installl.txt.
#
# Developed by Mohamed Annati.
set -euo pipefail

cd "$(dirname "$0")/../android"

if [ ! -f gradlew ]; then
  echo "[*] No Gradle wrapper yet - generating it (needs 'gradle' on PATH)."
  if command -v gradle >/dev/null 2>&1; then
    gradle wrapper --gradle-version 8.7
  else
    echo "[!] 'gradle' not found."
    echo "    Install Gradle 8.x first, or open ./android in Android Studio and"
    echo "    let it sync.  See ../installl.txt for the full recipe."
    exit 1
  fi
fi

# Make sure the Android SDK is discoverable.
if [ -z "${ANDROID_HOME:-}" ] && [ -d "$HOME/Android/Sdk" ]; then
  export ANDROID_HOME="$HOME/Android/Sdk"
fi
if [ -n "${ANDROID_HOME:-}" ]; then
  echo "sdk.dir=$ANDROID_HOME" > local.properties
fi

echo "[*] Building release APK..."
./gradlew assembleRelease

APK="app/build/outputs/apk/release/app-release-unsigned.apk"
if [ -f "$APK" ]; then
  OUT="../build/app-release-unsigned.apk"
  mkdir -p ../build
  cp "$APK" "$OUT"
  echo "[+] APK written to $OUT"
else
  echo "[!] APK not produced."
  exit 1
fi
