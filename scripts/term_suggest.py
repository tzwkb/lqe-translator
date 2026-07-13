#!/usr/bin/env python3
"""TB 近似术语建议（char n-gram TF-IDF 检索）。

精确术语匹配(term_hits)够不着"差一两字"的变体写法——源文 `故园迎新客`、
TB 收 `故园迎新伴`→Companions Make Home，差一个字精确匹配就落空。本模块对每段
源文检索术语表里**写法相近但未精确命中**的官方词条，作为 `term_near` **线索提供给
术语检查模块参考**（仅参考、不自动判错；是否为同一术语由检查任务判断）。

索引在内存建一次（~29k 条 ~1s），按段做"候选 × 滑窗最佳匹配"打分。
CLI 自测：python term_suggest.py --terms terms.json --query 故园迎新客
"""
import argparse
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

NGRAMS = (2, 3)
K_DEFAULT = 5
SIM_THRESHOLD = 0.45
MIN_TB_LEN = 4          # 只对多字名(版本/活动/标题)做近似建议；2-3 字常用词靠精确匹配，否则噪声泛滥


def _ngrams(s):
    g = []
    for n in NGRAMS:
        if len(s) >= n:
            g += [s[i:i + n] for i in range(len(s) - n + 1)]
        elif s:
            g.append(s)                       # 极短词整体作一个 gram
    return Counter(g)


def build_index(sources, targets, min_len=MIN_TB_LEN):
    """对 TB 源文建 char-ngram TF-IDF 索引 + 区分性 ngram 倒排（仅收 len≥min_len 的源）。"""
    keep = [(s, t) for s, t in zip(sources, targets) if len(s) >= min_len]
    sources = [s for s, _ in keep]
    targets = [t for _, t in keep]
    docs = [_ngrams(s) for s in sources]
    df = Counter()
    for d in docs:
        for gram in d:
            df[gram] += 1
    n = max(1, len(sources))
    idf = {gram: math.log(n / (1 + c)) + 1.0 for gram, c in df.items()}
    vecs, norms = [], []
    for d in docs:
        v = {gram: cnt * idf[gram] for gram, cnt in d.items()}
        vecs.append(v)
        norms.append(math.sqrt(sum(x * x for x in v.values())) or 1.0)
    cap = max(50, n // 500)                    # 只让低频(区分性)ngram 进倒排，避免常用字泛滥
    postings = defaultdict(list)
    for i, d in enumerate(docs):
        for gram in d:
            if df[gram] <= cap:
                postings[gram].append(i)
    return {"sources": sources, "targets": targets, "idf": idf, "vecs": vecs,
            "norms": norms, "df": df, "cap": cap, "n": n, "postings": postings}


def suggest(idx, seg_src, k=K_DEFAULT, threshold=SIM_THRESHOLD, exclude=()):
    """返回 [{seg, tb_src, tb_tgt, sim}]：段内与某 TB 词条写法相近(非精确)的候选，
    按 sim 降序、去重、top-k。exclude=已精确命中的 TB 源(不重复建议)。"""
    if not seg_src or not idx["sources"]:
        return []
    qd = _ngrams(seg_src)
    cand = set()                               # 共享区分性 ngram 的 TB 条目才参与打分
    for gram in qd:
        if idx["df"].get(gram, 0) <= idx["cap"]:
            cand.update(idx["postings"].get(gram, ()))
    exset = set(exclude)
    default_idf = math.log(idx["n"]) + 1.0
    scored = []
    for i in cand:
        tb = idx["sources"][i]
        if not tb or tb in exset:
            continue
        vlen = len(tb)
        v, vnorm = idx["vecs"][i], idx["norms"][i]
        best, best_win = 0.0, ""
        for wl in {max(2, vlen - 1), vlen, vlen + 1}:    # 滑窗长度 ≈ TB 词长，避免整段稀释
            for s in range(0, max(1, len(seg_src) - wl + 1)):
                win = seg_src[s:s + wl]
                wd = _ngrams(win)
                num = wnorm_sq = 0.0
                for gram, cnt in wd.items():
                    w = cnt * idx["idf"].get(gram, default_idf)
                    wnorm_sq += w * w
                    if gram in v:
                        num += w * v[gram]
                wnorm = math.sqrt(wnorm_sq) or 1.0
                sim = num / (wnorm * vnorm)
                if sim > best:
                    best, best_win = sim, win
        if best >= threshold:
            scored.append((best, best_win, i))
    scored.sort(reverse=True)
    res, seen = [], set()
    for sim, win, i in scored:
        src = idx["sources"][i]
        if src in seen:
            continue
        seen.add(src)
        res.append({"seg": win, "tb_src": src, "tb_tgt": idx["targets"][i],
                    "sim": round(sim, 3)})
        if len(res) >= k:
            break
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--terms", required=True, help="terms.json (list of {source,target})")
    ap.add_argument("--query", required=True, help="段源文或词")
    ap.add_argument("-k", type=int, default=K_DEFAULT)
    ap.add_argument("--threshold", type=float, default=SIM_THRESHOLD)
    a = ap.parse_args()
    terms = json.loads(Path(a.terms).read_text(encoding="utf-8"))
    pairs = [(str(t["source"]), str(t.get("target", ""))) for t in terms
             if len(str(t.get("source", ""))) >= 2]
    idx = build_index([s for s, _ in pairs], [t for _, t in pairs])
    hits = suggest(idx, a.query, k=a.k, threshold=a.threshold)
    if not hits:
        print("  (无近似候选)")
    for r in hits:
        print(f"  sim={r['sim']}  seg={r['seg']!r}  {r['tb_src']!r} -> {r['tb_tgt']!r}")


if __name__ == "__main__":
    main()
