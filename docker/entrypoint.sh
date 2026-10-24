#!/bin/sh
set -eu
export PYTHONPATH="/app/src${PYTHONPATH:+:$PYTHONPATH}"
if [ "$#" -eq 0 ]; then set -- web; fi
exec python -m mom_index.nas_runtime "$@"
