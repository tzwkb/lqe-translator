#!/bin/bash
# finalize_job.sh <jobname> <nchunks> [single|iterate]
# 多模块一键收尾：validate-checks → merge-checks → reconcile → merge → calc → write/apply → export
#   single  = 单轮：FAIL 也只出报告（不 apply-fixes 迭代）
#   iterate = 显式启用：FAIL 走 apply-fixes（自动迭代）
# 幂等：仅当 N 个基础 chunk 齐了才跑。
SK="$(cd "$(dirname "$0")/.." && pwd)"   # skill 根（脚本位置锚定，与 HOME/CWD 无关）
JOB_ARG="$1"
if [ -d "$JOB_ARG" ] && [ -f "$JOB_ARG/state.json" ]; then
  JOB="$(cd "$JOB_ARG" && pwd)"
else
  JOB="$SK/jobs/$JOB_ARG"
fi
N="$2"; MODE="${3:-single}"; CH="$JOB/chunks"
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
ENABLED_MODULES=$(PYTHONPATH="$SK/scripts${PYTHONPATH:+:$PYTHONPATH}" python3 - "$JOB/state.json" <<'PY'
import json
import sys

from lqe_engine import get_check_scope

with open(sys.argv[1], encoding="utf-8") as f:
    state = json.load(f)
print(", ".join(get_check_scope(state)["enabled_modules"]))
PY
)
echo "FINALIZING $1 MODE=$MODE; enabled modules: $ENABLED_MODULES"

have=$(find "$CH" -maxdepth 1 -type f -name 'chunk_[0-9][0-9].json' | wc -l | tr -d ' ')
if [ "$have" -lt "$N" ]; then echo "INCOMPLETE $1: chunks $have/$N"; exit 0; fi
if [ -f "$JOB/.finalized" ]; then echo "ALREADY-FINALIZED $1"; exit 0; fi

# 1) 检查四个必需模块的结构和 id 覆盖
if ! python3 "$SK/scripts/lqe_chunk.py" validate-checks --job "$JOB"; then
  echo "VALIDATE-CHECKS FAIL $1; not finalizing"; exit 4; fi
# 2) 合并模块检查结果
if ! python3 "$SK/scripts/lqe_chunk.py" merge-checks --job "$JOB"; then
  echo "MERGE-CHECKS FAIL $1; not finalizing"; exit 3; fi
# 3) 确认准确性问题来自准确性检查模块
if ! python3 "$SK/scripts/lqe_chunk.py" reconcile --job "$JOB"; then
  echo "RECONCILE FAIL $1; not finalizing"; exit 4
fi
# 4) 将重复段的检查结果复制到组内各段并写入 errors.json（任一 id 未覆盖则非零退出）
if ! python3 "$SK/scripts/lqe_chunk.py" merge --state "$JOB/state.json" \
     --errors "$JOB/errors_precheck.json" --outdir "$CH" --out "$JOB/errors.json"; then
  echo "MERGE-INCOMPLETE $1 (some ids uncovered; see above); not finalizing"; exit 3
fi
# 5) 计分
if ! RES=$(python3 "$SK/scripts/lqe_calc.py" --state "$JOB/state.json" --errors "$JOB/errors.json" --threshold "$THRESH" --json); then
  echo "CALC FAIL $1; not finalizing"; exit 5
fi
echo "  calc: $RES"
if ! SCORE=$(printf '%s' "$RES" | python3 -c "import json,sys;print(json.load(sys.stdin)['score'])"); then
  echo "CALC RESULT FAIL $1; not finalizing"; exit 5
fi
if ! STATUS=$(printf '%s' "$RES" | python3 -c "import json,sys;print(json.load(sys.stdin)['status'])"); then
  echo "CALC RESULT FAIL $1; not finalizing"; exit 5
fi
# 6) 报告：PASS 或单轮→write；否则 apply-fixes 迭代
if [ "$STATUS" = "PASS" ] || [ "$MODE" = "single" ]; then
  if ! python3 "$SK/scripts/lqe_io.py" write --state "$JOB/state.json" --errors "$JOB/errors.json" --score "$SCORE" --threshold "$THRESH"; then
    echo "WRITE FAIL $1; not finalizing"; exit 6
  fi
else
  if ! python3 "$SK/scripts/lqe_io.py" apply-fixes --state "$JOB/state.json" --errors "$JOB/errors.json" --score "$SCORE" --threshold "$THRESH"; then
    echo "APPLY-FIXES FAIL $1; not finalizing"; exit 6
  fi
fi
# 7) 导出建议译文（--errors 可补充单轮任务中程序生成的建议译文）
if ! python3 "$SK/scripts/lqe_io.py" export --state "$JOB/state.json" --errors "$JOB/errors.json"; then
  echo "EXPORT FAIL $1; not finalizing"; exit 7
fi
touch "$JOB/.finalized"
echo "FINALIZED $1 SCORE=$SCORE STATUS=$STATUS MODE=$MODE"
ls -1 "$JOB"/*.xlsx 2>/dev/null | sed "s|$HOME|~|"
