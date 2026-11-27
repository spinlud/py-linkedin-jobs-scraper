#!/bin/zsh
# Every stack in every mode, one browser at a time
cd "${0:A:h}"
for stack in selenium patchright sb-uc sb-cdp pydoll zendriver; do
  for mode in headless-raw headless-masked headed; do
    echo "== $stack $mode $(date +%T)"
    .venv/bin/python rung.py $stack $mode results/$stack/$mode > results/$stack-$mode.log 2>&1 || echo "exit $?"
    pkill -f "user-data-dir=.*rung-" 2>/dev/null
  done
done
echo done
