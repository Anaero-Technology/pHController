#!/usr/bin/env bash
# Block until the Pi has real internet connectivity, then exit 0.
# Used as ExecStartPre so the API/UI only starts serving once online.
set -u

hosts=(1.1.1.1 8.8.8.8)
echo "wait-online: checking internet connectivity..."
while true; do
  for h in "${hosts[@]}"; do
    if ping -c1 -W2 "$h" >/dev/null 2>&1; then
      echo "wait-online: internet is up ($h reachable)"
      exit 0
    fi
  done
  echo "wait-online: no connectivity yet, retrying in 3s..."
  sleep 3
done
