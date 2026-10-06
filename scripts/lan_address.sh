#!/usr/bin/env bash
# Print the address a phone on the same network should use for the backend, plus
# the exact commands to start the API and to point the app at it.
#
# Nothing here is Android- or Wi-Fi-specific magic: it reports the machine's own
# LAN IPv4 addresses and the URLs built from them.
set -euo pipefail

port="${1:-8000}"

addresses="$(
  { ip -4 -o addr show scope global 2>/dev/null | awk '{split($4, a, "/"); print a[1], $2}'; } || true
)"
if [ -z "$addresses" ]; then
  echo "No global IPv4 address found on this machine." >&2
  echo "Connect it to the same network as the phone (Wi-Fi or the phone's hotspot), then re-run." >&2
  exit 1
fi

echo "Backend port: $port"
echo
printf '%-16s %-12s %s\n' "LAN IP" "INTERFACE" "ADDRESS FOR THE APP"
while read -r ip iface; do
  printf '%-16s %-12s %s\n' "$ip" "$iface" "http://$ip:$port"
done <<< "$addresses"

primary="$(echo "$addresses" | awk 'NR==1 {print $1}')"
cat <<HELP

1) Start the API so the network can reach it (loopback-only is not enough):
   cd backend && ../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port $port

2) On a debug build no rebuild is needed — open the app, tap the server address
   on the sign-in screen, enter http://$primary:$port, tap "Test connection".

   To bake the address into a build instead:
   cd mobile/flutter_app && flutter build apk --debug --dart-define=API_BASE_URL=http://$primary:$port

3) If the phone still gets "No answer" (probing /health):
   - allow inbound TCP $port through this machine's firewall;
   - make sure the phone is on the same Wi-Fi, not a guest network, with AP/client
     isolation off;
   - disconnect any VPN on the phone.

See docs/mobile_release.md section 4 for the full checklist.
HELP
