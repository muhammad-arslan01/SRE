#!/usr/bin/env bash
# Downloads the vendored React/Babel libraries so the dashboard works offline.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
V="$HERE/web/vendor"
mkdir -p "$V"
echo "Vendoring into: $V"
curl -sL -o "$V/react.production.min.js"     https://unpkg.com/react@18/umd/react.production.min.js
curl -sL -o "$V/react-dom.production.min.js" https://unpkg.com/react-dom@18/umd/react-dom.production.min.js
curl -sL -o "$V/babel.min.js"                https://unpkg.com/@babel/standalone@7/babel.min.js
echo "Done:"
ls -la "$V"
