#!/usr/bin/env bash
set -euo pipefail

# Single DRY build/test/package script for Garmin Connect IQ (Fenix 7 + Store .iq).
# Usage:
#   ./garmin-app/scripts/build.sh [device]          # Build sideload .prg (default: fenix7)
#   ./garmin-app/scripts/build.sh --test [device]   # Build & run (:test) unit tests
#   ./garmin-app/scripts/build.sh --package         # Export signed .iq for Connect IQ Store

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
OUT_DIR="${APP_DIR}/bin"
mkdir -p "${OUT_DIR}"

MODE="prg"
DEVICE="fenix7"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --package) MODE="iq"; shift ;;
        --test) MODE="test"; shift ;;
        -h|--help)
            sed -n '3,8p' "$0"
            exit 0
            ;;
        *) DEVICE="$1"; shift ;;
    esac
done

find_sdk_bin() {
    if [[ -n "${CIQ_SDK_HOME:-}" && -x "${CIQ_SDK_HOME}/bin/monkeyc" ]]; then
        echo "${CIQ_SDK_HOME}/bin"
        return 0
    fi
    if command -v monkeyc >/dev/null 2>&1; then
        dirname "$(command -v monkeyc)"
        return 0
    fi
    local latest
    latest="$(ls -d "${HOME}/.Garmin/ConnectIQ/Sdks"/connectiq-sdk-* 2>/dev/null | sort -V | tail -n 1 || true)"
    if [[ -n "${latest}" && -x "${latest}/bin/monkeyc" ]]; then
        echo "${latest}/bin"
        return 0
    fi
    return 1
}

SDK_BIN="$(find_sdk_bin || true)"
if [[ -z "${SDK_BIN}" ]]; then
    cat >&2 <<'EOF'
Error: Garmin Connect IQ SDK (monkeyc) not found.
Install it with connect-iq-sdk-manager-cli (or Garmin SDK Manager), log in with your Garmin Developer account,
and download the Fenix 7 device profile:

  go install github.com/lindell/connect-iq-sdk-manager-cli@latest
  connect-iq-sdk-manager-cli agreement accept
  connect-iq-sdk-manager-cli login
  connect-iq-sdk-manager-cli sdk set latest
  connect-iq-sdk-manager-cli device download --manifest=garmin-app/manifest.xml
  export CIQ_SDK_HOME="$(connect-iq-sdk-manager-cli sdk current-path)"
EOF
    exit 1
fi

DEV_KEY="${GARMIN_DEV_KEY:-${OUT_DIR}/dev_key.der}"
if [[ ! -f "${DEV_KEY}" ]]; then
    if [[ "${MODE}" == "iq" ]]; then
        echo "Error: GARMIN_DEV_KEY must point to your permanent 4096-bit RSA DER key for Store .iq exports." >&2
        exit 1
    fi
    echo "Generating ephemeral 4096-bit RSA DER key for local build at ${DEV_KEY}..."
    openssl genrsa -out "${OUT_DIR}/dev_key.pem" 4096 >/dev/null 2>&1
    openssl pkcs8 -topk8 -inform PEM -outform DER -in "${OUT_DIR}/dev_key.pem" -out "${DEV_KEY}" -nocrypt
    rm -f "${OUT_DIR}/dev_key.pem"
fi

MONKEYC="${SDK_BIN}/monkeyc"
JUNGLE="${APP_DIR}/monkey.jungle"

case "${MODE}" in
    prg)
        OUT_FILE="${OUT_DIR}/ma-remote-${DEVICE}.prg"
        echo "Compiling ${OUT_FILE} (strict typecheck -l 3, -w, -O 2)..."
        "${MONKEYC}" -d "${DEVICE}" -f "${JUNGLE}" -o "${OUT_FILE}" -y "${DEV_KEY}" -l 3 -O 2 -w
        echo "Built: ${OUT_FILE}"
        echo "Sideload by copying ${OUT_FILE} to GARMIN/APPS/ on your watch over USB."
        ;;
    test)
        OUT_FILE="${OUT_DIR}/ma-remote-${DEVICE}-test.prg"
        echo "Compiling test binary ${OUT_FILE}..."
        "${MONKEYC}" -d "${DEVICE}" -f "${JUNGLE}" -o "${OUT_FILE}" -y "${DEV_KEY}" -l 3 -t -w
        echo "Running Run No Evil (:test) suite (ensure Connect IQ simulator is running)..."
        "${SDK_BIN}/monkeydo" "${OUT_FILE}" "${DEVICE}" -t
        ;;
    iq)
        OUT_FILE="${OUT_DIR}/ma-remote.iq"
        echo "Exporting Connect IQ Store package ${OUT_FILE}..."
        "${MONKEYC}" -e -f "${JUNGLE}" -o "${OUT_FILE}" -y "${DEV_KEY}" -l 3 -O 2 -w
        echo "Exported: ${OUT_FILE}"
        ;;
esac
