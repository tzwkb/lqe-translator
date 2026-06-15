#!/bin/bash
# finalize_job.sh <jobname> <nchunks>
# Idempotent: only finalizes when all chunk out.json exist AND coverage is complete.
SK="$(cd "$(dirname "$0")/.." && pwd)"   # skill 根（脚本位置锚定，与 HOME/CWD 无关）
JOB="$SK/jobs/$1"; N="$2"
have=$(ls "$JOB"/chunks/*.out.json 2>/dev/null | wc -l | tr -d ' ')
if [ "$have" -lt "$N" ]; then echo "INCOMPLETE $1: $have/$N out.json"; exit 0; fi
if [ -f "$JOB/.finalized" ]; then echo "ALREADY-FINALIZED $1"; exit 0; fi
# merge (exits non-zero if any state id uncovered)
if ! python3 "$SK/scripts/lqe_chunk.py" merge --state "$JOB/state.json" \
     --errors "$JOB/errors_precheck.json" --outdir "$JOB/chunks" --out "$JOB/errors.json"; then
  echo "MERGE-INCOMPLETE $1 (some ids uncovered; see above) — not finalizing"; exit 3
fi
RES=$(python3 "$SK/scripts/lqe_calc.py" --state "$JOB/state.json" --errors "$JOB/errors.json" --threshold 98 --json)
echo "  calc: $RES"
SCORE=$(printf '%s' "$RES" | python3 -c "import json,sys;print(json.load(sys.stdin)['score'])")
STATUS=$(printf '%s' "$RES" | python3 -c "import json,sys;print(json.load(sys.stdin)['status'])")
if [ "$STATUS" = "PASS" ]; then
  python3 "$SK/scripts/lqe_io.py" write --state "$JOB/state.json" --errors "$JOB/errors.json" --score "$SCORE" --threshold 98
else
  python3 "$SK/scripts/lqe_io.py" apply-fixes --state "$JOB/state.json" --errors "$JOB/errors.json" --score "$SCORE" --threshold 98
fi
python3 "$SK/scripts/lqe_io.py" export --state "$JOB/state.json"
touch "$JOB/.finalized"
echo "FINALIZED $1 SCORE=$SCORE STATUS=$STATUS"
ls -1 "$JOB"/*.xlsx 2>/dev/null | sed "s|$HOME|~|"