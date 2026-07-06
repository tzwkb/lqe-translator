#!/bin/bash
# finalize_job.sh <jobname> <nchunks> [single|iterate]
# 多-lens 一键收尾：merge-lenses → validate-lenses → reconcile → merge → calc → report → export
#   single  = 单轮：FAIL 也只出报告（不 apply-fixes 迭代）
#   iterate = 默认：FAIL 走 apply-fixes（自动迭代）
# 幂等：仅当 N 个 T 脊柱(chunk_NN.T.json)齐了才跑。
SK="$(cd "$(dirname "$0")/.." && pwd)"   # skill 根（脚本位置锚定，与 HOME/CWD 无关）
JOB="$SK/jobs/$1"; N="$2"; MODE="${3:-iterate}"; CH="$JOB/chunks"
THRESH=$(python3 - "$JOB/state.json" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as f:
        print(json.load(f).get("threshold", 98))
except Exception:
    print(98)
PY
)

have=$(ls "$CH"/chunk_*.T.json 2>/dev/null | wc -l | tr -d ' ')
if [ "$have" -lt "$N" ]; then echo "INCOMPLETE $1: T spines $have/$N"; exit 0; fi
if [ -f "$JOB/.finalized" ]; then echo "ALREADY-FINALIZED $1"; exit 0; fi

# 1) lens 合并（T 脊柱 union A/G/R）
if ! python3 "$SK/scripts/lqe_chunk.py" merge-lenses --outdir "$CH"; then
  echo "MERGE-LENSES FAIL $1"; exit 3; fi
# 2) 结构守门（缺 id/坏类别/脊柱不全→非零退出，防静默丢数据）
if ! python3 "$SK/scripts/lqe_chunk.py" validate-lenses --outdir "$CH"; then
  echo "VALIDATE-LENSES FAIL $1 — not finalizing"; exit 4; fi
# 3) 归属权威化（A_OWNED 仅留 A 确认项 + 存档 reconcile_dropped.json）
python3 "$SK/scripts/lqe_chunk.py" reconcile --outdir "$CH"
# 4) 广播去重组 → errors.json（任一 id 未覆盖则非零退出）
if ! python3 "$SK/scripts/lqe_chunk.py" merge --state "$JOB/state.json" \
     --errors "$JOB/errors_precheck.json" --outdir "$CH" --out "$JOB/errors.json"; then
  echo "MERGE-INCOMPLETE $1 (some ids uncovered; see above) — not finalizing"; exit 3
fi
# 5) 计分
RES=$(python3 "$SK/scripts/lqe_calc.py" --state "$JOB/state.json" --errors "$JOB/errors.json" --threshold "$THRESH" --json)
echo "  calc: $RES"
SCORE=$(printf '%s' "$RES" | python3 -c "import json,sys;print(json.load(sys.stdin)['score'])")
STATUS=$(printf '%s' "$RES" | python3 -c "import json,sys;print(json.load(sys.stdin)['status'])")
# 6) 报告：PASS 或单轮→write；否则 apply-fixes 迭代
if [ "$STATUS" = "PASS" ] || [ "$MODE" = "single" ]; then
  python3 "$SK/scripts/lqe_io.py" write --state "$JOB/state.json" --errors "$JOB/errors.json" --score "$SCORE" --threshold "$THRESH"
else
  python3 "$SK/scripts/lqe_io.py" apply-fixes --state "$JOB/state.json" --errors "$JOB/errors.json" --score "$SCORE" --threshold "$THRESH"
fi
# 7) 导出建议修正稿（--errors 让单轮 state.corrected 为空时也能填建议）
python3 "$SK/scripts/lqe_io.py" export --state "$JOB/state.json" --errors "$JOB/errors.json"
touch "$JOB/.finalized"
echo "FINALIZED $1 SCORE=$SCORE STATUS=$STATUS MODE=$MODE"
ls -1 "$JOB"/*.xlsx 2>/dev/null | sed "s|$HOME|~|"
