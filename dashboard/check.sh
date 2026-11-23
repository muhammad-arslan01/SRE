#!/usr/bin/env bash
for p in /styles.css /app.jsx /vendor/react.production.min.js /vendor/react-dom.production.min.js /vendor/babel.min.js /api/data /; do
  code=$(curl -s -m 8 -o /dev/null -w '%{http_code}' "http://localhost:8787$p")
  echo "$code  $p"
done
