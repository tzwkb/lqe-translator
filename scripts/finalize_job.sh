#!/bin/bash
# finalize_job.sh <jobname> <nchunks> [single|iterate]
# 多模块一键收尾：validate-checks → merge-checks → reconcile → merge → calc → write/apply → export
#   single  = 单轮：FAIL 也只出报告（不 apply-fixes 迭代）
#   iterate = 显式启用：FAIL 走 apply-fixes（自动迭代）
# 幂等：仅当 N 个基础 chunk 齐了才跑。PYTHON 可覆盖（venv/CI 用），默认 python3。
SK="$(cd "$(dirname "$0")/.." && pwd)"   # skill 根（脚本位置锚定，与 HOME/CWD 无关）
JOB_ARG="$1"
if [ -d "$JOB_ARG" ] && [ -f "$JOB_ARG/state.json" ]; then
  JOB="$(cd "$JOB_ARG" && pwd)"
else
  JOB="$SK/jobs/$JOB_ARG"
fi
N="$2"; MODE="${3:-single}"; CH="$JOB/chunks"
case "$N" in
  ''|*[!0-9]*) echo "INVALID CHUNK COUNT: $N" >&2; exit 2 ;;
  0) echo "INVALID CHUNK COUNT: $N" >&2; exit 2 ;;
esac
case "$MODE" in
  single|iterate) ;;
  *) echo "INVALID MODE: $MODE (expected single or iterate)" >&2; exit 2 ;;
esac
ENABLED_MODULES=$(PYTHONPATH="$SK/scripts${PYTHONPATH:+:$PYTHONPATH}" ${PYTHON:-python3} - "$JOB/state.json" <<'PY'
import json
import sys

from lqe_engine import get_check_scope

with open(sys.argv[1], encoding="utf-8") as f:
    state = json.load(f)
print(", ".join(get_check_scope(state)["enabled_modules"]))
PY
)
echo "FINALIZING $1 MODE=$MODE; enabled modules: $ENABLED_MODULES"

if [ ! -d "$CH" ]; then echo "INCOMPLETE $1: chunks 0/$N"; exit 0; fi
have=$(find "$CH" -maxdepth 1 -type f -name 'chunk_*.json' | ${PYTHON:-python3} -c \
  'import re,sys; print(sum(bool(re.fullmatch(r"chunk_\d+\.json", line.rsplit("/",1)[-1].strip())) for line in sys.stdin))')
if [ "$have" -lt "$N" ]; then echo "INCOMPLETE $1: chunks $have/$N"; exit 0; fi
if [ -f "$JOB/.finalized" ]; then echo "ALREADY-FINALIZED $1"; exit 0; fi

# 1) 检查四个必需模块的结构和 id 覆盖
if ! ${PYTHON:-python3} "$SK/scripts/lqe_chunk.py" validate-checks --job "$JOB"; then
  echo "VALIDATE-CHECKS FAIL $1; not finalizing"; exit 4; fi
# 2) 合并模块检查结果
if ! ${PYTHON:-python3} "$SK/scripts/lqe_chunk.py" merge-checks --job "$JOB"; then
  echo "MERGE-CHECKS FAIL $1; not finalizing"; exit 3; fi
# 3) 确认准确性问题来自准确性检查模块
if ! ${PYTHON:-python3} "$SK/scripts/lqe_chunk.py" reconcile --job "$JOB"; then
  echo "RECONCILE FAIL $1; not finalizing"; exit 4
fi
# 4) 将重复段的检查结果复制到组内各段并写入 errors.json（任一 id 未覆盖则非零退出）
if ! ${PYTHON:-python3} "$SK/scripts/lqe_chunk.py" merge --state "$JOB/state.json" \
     --errors "$JOB/errors_precheck.json" --outdir "$CH" --out "$JOB/errors.json"; then
  echo "MERGE-INCOMPLETE $1 (some ids uncovered; see above); not finalizing"; exit 3
fi
# 5) 计分
if ! RES=$(${PYTHON:-python3} "$SK/scripts/lqe_calc.py" --state "$JOB/state.json" --errors "$JOB/errors.json" --json); then
  echo "CALC FAIL $1; not finalizing"; exit 5
fi
echo "  calc: $RES"
if ! SCORE=$(printf '%s' "$RES" | ${PYTHON:-python3} -c "import json,sys;print(json.load(sys.stdin)['score'])"); then
  echo "CALC RESULT FAIL $1; not finalizing"; exit 5
fi
if ! STATUS=$(printf '%s' "$RES" | ${PYTHON:-python3} -c "import json,sys;print(json.load(sys.stdin)['status'])"); then
  echo "CALC RESULT FAIL $1; not finalizing"; exit 5
fi
# 6) PASS 才完成；FAIL single 留待审阅；FAIL iterate 应用已验证修改后等待复检
if [ "$STATUS" = "PASS" ]; then
  if ! ${PYTHON:-python3} "$SK/scripts/lqe_io.py" write --state "$JOB/state.json" --errors "$JOB/errors.json" --score "$SCORE"; then
    echo "WRITE FAIL $1; not finalizing"; exit 6
  fi
  if ! ${PYTHON:-python3} "$SK/scripts/lqe_io.py" export --state "$JOB/state.json" --errors "$JOB/errors.json"; then
    echo "EXPORT FAIL $1; not finalizing"; exit 7
  fi
  if ! rm -f "$JOB/.iteration_pending"; then
    echo "MARKER CLEANUP FAIL $1; not finalizing" >&2; exit 8
  fi
  if ! touch "$JOB/.finalized"; then
    echo "FINALIZED MARKER FAIL $1; not finalizing" >&2; exit 8
  fi
  echo "FINALIZED $1 SCORE=$SCORE STATUS=$STATUS MODE=$MODE"
elif [ "$MODE" = "single" ]; then
  if ! ${PYTHON:-python3} "$SK/scripts/lqe_io.py" write --state "$JOB/state.json" --errors "$JOB/errors.json" --score "$SCORE"; then
    echo "WRITE FAIL $1; not finalizing"; exit 6
  fi
  if ! ${PYTHON:-python3} "$SK/scripts/lqe_io.py" export --state "$JOB/state.json" --errors "$JOB/errors.json"; then
    echo "EXPORT FAIL $1; not finalizing"; exit 7
  fi
  if ! rm -f "$JOB/.iteration_pending"; then
    echo "MARKER CLEANUP FAIL $1" >&2; exit 8
  fi
  echo "REVIEW-REQUIRED $1 SCORE=$SCORE STATUS=$STATUS MODE=$MODE"
else
  if ! APPLY_RESULT=$(${PYTHON:-python3} "$SK/scripts/lqe_io.py" apply-fixes --state "$JOB/state.json" --errors "$JOB/errors.json" --score "$SCORE"); then
    echo "APPLY-FIXES FAIL $1; not finalizing"; exit 6
  fi
  printf '%s\n' "$APPLY_RESULT"
  if ! APPLIED_COUNT=$(printf '%s\n' "$APPLY_RESULT" | ${PYTHON:-python3} -c 'import json,sys; lines=[line for line in sys.stdin.read().splitlines() if line.strip()]; print(json.loads(lines[-1])["applied_count"])'); then
    echo "APPLY-FIXES RESULT FAIL $1; not finalizing" >&2; exit 6
  fi
  case "$APPLIED_COUNT" in
    ''|*[!0-9]*) echo "APPLY-FIXES RESULT FAIL $1; invalid applied_count" >&2; exit 6 ;;
  esac
  if [ "$APPLIED_COUNT" -gt 0 ]; then
    if ! ${PYTHON:-python3} "$SK/scripts/lqe_io.py" export --state "$JOB/state.json"; then
      echo "EXPORT FAIL $1; not finalizing"; exit 7
    fi
    if ! touch "$JOB/.iteration_pending"; then
      echo "PENDING MARKER FAIL $1" >&2; exit 8
    fi
    echo "PENDING-RECHECK $1 SCORE=$SCORE STATUS=$STATUS MODE=$MODE APPLIED=$APPLIED_COUNT"
  else
    if ! ${PYTHON:-python3} "$SK/scripts/lqe_io.py" write --state "$JOB/state.json" --errors "$JOB/errors.json" --score "$SCORE"; then
      echo "WRITE FAIL $1; not finalizing"; exit 6
    fi
    if ! ${PYTHON:-python3} "$SK/scripts/lqe_io.py" export --state "$JOB/state.json" --errors "$JOB/errors.json"; then
      echo "EXPORT FAIL $1; not finalizing"; exit 7
    fi
    if ! rm -f "$JOB/.iteration_pending"; then
      echo "MARKER CLEANUP FAIL $1" >&2; exit 8
    fi
    echo "REVIEW-REQUIRED $1 SCORE=$SCORE STATUS=$STATUS MODE=$MODE APPLIED=0"
  fi
fi
ls -1 "$JOB"/*.xlsx 2>/dev/null | sed "s|$HOME|~|"
