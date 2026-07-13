#!/usr/bin/env python3
"""多 sheet 任务顶层汇总：把已 finalize 的各子 job 合成跨 sheet 交付物。

产出（父 job 目录）：
  <label>_corrected.xlsx  保留原始 workbook 的 sheet/公式/样式/合并单元格，
                          仅将程序生成的非空 corrected 写回原译文列。
  <label>_LQE报告.xlsx     汇总 sheet（各子表分数 + 按词数加权总分）+ 各子表 LQE Results 明细。

子 job 发现：父 job 目录下含 state.json 的直接子目录即一个 sheet 子 job。
段→行映射：优先使用 segment.row_index；旧 state 缺该字段时才回退 segment.id。

用法：
  python scripts/aggregate_sheets.py --job LQE测试用 [--sheets 剧情,功能,社媒] [--threshold 98]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import openpyxl
from openpyxl.styles import Font

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lqe_engine import read_json, _SKILL_ROOT  # noqa: E402
from lqe_corrections import CheckFormatError, verify_results  # noqa: E402

THRESH_DEFAULT = 98


def _label(p: Path) -> str:
    """父/子 job 标签：jobs/ 下子路径用 _ 连接（与 lqe_io._job_label 同口径）。"""
    parts = p.resolve().parts
    if "jobs" in parts:
        sub = parts[parts.index("jobs") + 1:]
        if sub:
            return "_".join(sub)
    return p.resolve().name


def _target_idx(state) -> int:
    tc = state["target_col"]
    try:
        return int(tc)
    except (ValueError, TypeError):
        headers = state.get("headers", [])
        return headers.index(tc) if tc in headers else 1


def _calc(sj: Path, thresh: int):
    out = subprocess.check_output([
        sys.executable, str(_SKILL_ROOT / "scripts/lqe_calc.py"),
        "--state", str(sj / "state.json"), "--errors", str(sj / "errors.json"),
        "--threshold", str(thresh), "--json",
    ])
    return json.loads(out)


def _discover(job_dir: Path):
    return sorted([d for d in job_dir.iterdir()
                   if d.is_dir() and (d / "state.json").exists()],
                  key=lambda d: d.name)


def _validated_results(sj: Path, state: dict) -> tuple[list[dict], dict[int, dict]]:
    segments = state.get("segments", [])
    try:
        results = verify_results(
            segments,
            read_json(sj / "errors.json"),
            f"{sj.name}/errors.json",
        )
    except CheckFormatError as exc:
        sys.exit(f"[aggregate] {exc}")
    return results, {segment["id"]: segment for segment in segments}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True,
                    help="父 job：jobs/ 下子路径（如 LQE测试用）或绝对路径")
    ap.add_argument("--sheets", default=None,
                    help="逗号分隔的子 job 目录名，指定顺序/子集；缺省=按名发现全部")
    ap.add_argument("--threshold", type=int, default=THRESH_DEFAULT)
    a = ap.parse_args()

    job_dir = Path(a.job)
    if not job_dir.is_absolute():
        job_dir = _SKILL_ROOT / "jobs" / a.job
    if not job_dir.is_dir():
        sys.exit(f"[aggregate] job dir not found: {job_dir}")

    if a.sheets:
        subs = [job_dir / s.strip() for s in a.sheets.split(",")]
        for s in subs:
            if not (s / "state.json").exists():
                sys.exit(f"[aggregate] sub-job missing state.json: {s}")
    else:
        subs = _discover(job_dir)
    if not subs:
        sys.exit(f"[aggregate] no sub-jobs (state.json) under {job_dir}")

    label = _label(job_dir)

    # ── 1) 校验 corrected 权威归属，再从原工作簿原位写入建议译文──────────
    summary = []
    tot_L = tot_wc = tot_err = tot_crit = tot_seg = tot_fix = 0
    validated = []

    for sj in subs:
        state = read_json(sj / "state.json")
        results, seg_by_id = _validated_results(sj, state)
        tidx = _target_idx(state)
        seg_rows = {sid: int(seg.get("row_index", sid)) for sid, seg in seg_by_id.items()}
        corr = {
            seg_rows[e["id"]]: e["corrected"]
            for e in results
            if e["corrected"] is not None
        }
        res = _calc(sj, a.threshold)
        tot_L += res["npt"] * res["wordcount"] / 1000.0
        tot_wc += res["wordcount"]
        tot_err += res["errors"]
        tot_crit += res["critical"]
        nseg = len(state["segments"])
        tot_seg += nseg

        src_path = state.get("input_path")
        if not src_path or not Path(src_path).exists():
            src_path = sj / "src.xlsx"   # 回退：read 记录的源不可达时，用子 job 内副本
        validated.append((sj, state, Path(src_path), tidx, corr, res, nseg))

    source_paths = {item[2].resolve() for item in validated}
    if len(source_paths) != 1:
        sys.exit(f"[aggregate] sub-jobs must share one source workbook: {sorted(map(str, source_paths))}")
    cwb = openpyxl.load_workbook(next(iter(source_paths)), data_only=False)
    for sj, state, _src_path, tidx, corr, res, nseg in validated:
        sheet_name = state.get("sheet_name") or sj.name
        if sheet_name in cwb.sheetnames:
            ws = cwb[sheet_name]
        elif len(subs) == 1:
            ws = cwb.active
        else:
            cwb.close()
            sys.exit(f"[aggregate] source workbook missing sheet: {sheet_name}")
        delivery_replacements = 0
        for row_index, corrected in corr.items():
            cell = ws.cell(row=row_index + 2, column=tidx + 1)
            if cell.value != corrected:
                delivery_replacements += 1
            cell.value = corrected
        tot_fix += delivery_replacements
        summary.append([sj.name, nseg, res["wordcount"], res["errors"],
                        res["critical"], res["score"], res["status"], delivery_replacements])

    corr_out = job_dir / f"{label}_corrected.xlsx"
    cwb.save(corr_out)

    # ── 2) 汇总报告（汇总 sheet + 各子表 LQE Results）────────────────────
    overall = max((1 - tot_L / tot_wc) * 100, 0) if tot_wc else 0.0
    s0 = read_json(subs[0] / "state.json")
    rep = openpyxl.Workbook()
    ws = rep.active
    ws.title = "汇总"
    ws.append([f"LQE 质检汇总报告 · {label}"])
    ws.append([f"阈值 {a.threshold}  语言对 {s0.get('language_pair', '')}  项目 {s0.get('project', '')}"])
    ws.append([])
    ws.append(["子表", "段数", "词数", "错误数", "Critical", "SCORE", "STATUS", "建议修改数"])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
    for r in summary:
        ws.append(r)
    ws.append(["合计", tot_seg, tot_wc, tot_err, tot_crit, round(overall, 2),
               "PASS" if overall >= a.threshold else "FAIL", tot_fix])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
    ws.append([])
    ws.append(["注：总分=按词数加权 (1-ΣL/Σwordcount)×100；各子表词数首轮锁定。"])

    for sj in subs:
        lqe = sj / f"{_label(sj)}_lqe.xlsx"
        if not lqe.exists():
            continue
        wb = openpyxl.load_workbook(lqe)
        if "LQE Results" in wb.sheetnames:
            sw = wb["LQE Results"]
            ws2 = rep.create_sheet(f"{sj.name} Results")
            for row in sw.iter_rows(values_only=True):
                ws2.append(list(row))
        wb.close()

    rep_out = job_dir / f"{label}_LQE报告.xlsx"
    rep.save(rep_out)

    print(f"[aggregate] {len(subs)} sheets: {', '.join(s.name for s in subs)}")
    print(f"[aggregate] corrected -> {corr_out}")
    print(f"[aggregate] report    -> {rep_out}")
    print(f"[aggregate] overall {overall:.2f} ({'PASS' if overall >= a.threshold else 'FAIL'}) "
          f"segs={tot_seg} wc={tot_wc} errors={tot_err} critical={tot_crit} fixes={tot_fix}")
    for r in summary:
        print(f"  {r[0]}: {r[5]} {r[6]} (segs {r[1]}, wc {r[2]}, err {r[3]}, crit {r[4]}, fix {r[7]})")


if __name__ == "__main__":
    main()
