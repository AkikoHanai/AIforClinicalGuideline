"""フォレストプロット(SVG, 白地黒線・印刷向け)

entries: [{"label": "Smith et al. 2013", "measure": "MD", "point": -0.73, "lo": -1.2, "hi": -0.3, "weight": None}]
比(RR/OR/HR)は対数軸、差(MD/SMD)は線形軸。統合値(pooled)を渡せば菱形で描く。
"""
import math

RATIO = {"RR", "OR", "HR", "IRR"}


def _fmt(x):
    return f"{x:.2f}" if isinstance(x, (int, float)) else "—"


def forest_svg(entries, measure, pooled=None, title="", width=720):
    rows = [e for e in entries if e.get("point") is not None]
    if not rows:
        return ""
    log = measure.upper() in RATIO
    tr = (lambda v: math.log(v) if v > 0 else None) if log else (lambda v: v)
    vals = []
    for e in rows + ([pooled] if pooled else []):
        for k in ("point", "lo", "hi"):
            v = e.get(k)
            if v is not None and (not log or v > 0):
                vals.append(tr(v))
    null = 0.0
    lo_ax, hi_ax = min(vals + [null]), max(vals + [null])
    pad = (hi_ax - lo_ax) * 0.1 or 1
    lo_ax, hi_ax = lo_ax - pad, hi_ax + pad
    left, right = 250, width - 160
    row_h, top = 26, 40
    def x(v):
        return left + (tr(v) - lo_ax) / (hi_ax - lo_ax) * (right - left)
    n = len(rows) + (1 if pooled else 0)
    h = top + n * row_h + 50
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{h}" '
           f'viewBox="0 0 {width} {h}" font-family="sans-serif" font-size="12" '
           f'style="background:#fff;max-width:100%;height:auto">']
    if title:
        out.append(f'<text x="8" y="16" font-weight="bold">{title}</text>')
    out.append(f'<text x="8" y="{top - 8}" font-weight="bold">研究</text>')
    out.append(f'<text x="{right + 10}" y="{top - 8}" font-weight="bold">{measure} [95%CI]</text>')
    # 無効線
    y_bottom = top + n * row_h
    out.append(f'<line x1="{x(1 if log else 0):.1f}" y1="{top - 4}" x2="{x(1 if log else 0):.1f}" '
               f'y2="{y_bottom}" stroke="#000" stroke-dasharray="3,3"/>')
    for i, e in enumerate(rows):
        y = top + i * row_h + row_h / 2
        out.append(f'<text x="8" y="{y + 4}">{e.get("label", "")}</text>')
        p, lo, hi = e["point"], e.get("lo"), e.get("hi")
        if log and p <= 0:
            continue
        if lo is not None and hi is not None and (not log or (lo > 0 and hi > 0)):
            out.append(f'<line x1="{x(lo):.1f}" y1="{y}" x2="{x(hi):.1f}" y2="{y}" stroke="#000"/>')
        s = 5
        out.append(f'<rect x="{x(p) - s:.1f}" y="{y - s}" width="{2*s}" height="{2*s}" fill="#000"/>')
        out.append(f'<text x="{right + 10}" y="{y + 4}">{_fmt(p)} [{_fmt(lo)}, {_fmt(hi)}]</text>')
    if pooled and pooled.get("point") is not None:
        y = top + len(rows) * row_h + row_h / 2
        p, lo, hi = pooled["point"], pooled.get("lo", p), pooled.get("hi", p)
        out.append(f'<text x="8" y="{y + 4}" font-weight="bold">{pooled.get("label", "統合")}</text>')
        out.append(f'<polygon points="{x(lo):.1f},{y} {x(p):.1f},{y-7} {x(hi):.1f},{y} {x(p):.1f},{y+7}" '
                   f'fill="none" stroke="#000" stroke-width="1.5"/>')
        out.append(f'<text x="{right + 10}" y="{y + 4}" font-weight="bold">{_fmt(p)} [{_fmt(lo)}, {_fmt(hi)}]</text>')
    # 軸
    out.append(f'<line x1="{left}" y1="{y_bottom + 6}" x2="{right}" y2="{y_bottom + 6}" stroke="#000"/>')
    ticks = [0.1, 0.2, 0.5, 1, 2, 5, 10] if log else None
    if not ticks:
        span = hi_ax - lo_ax
        step = 10 ** math.floor(math.log10(span / 4)) if span > 0 else 1
        if span / step > 8:
            step *= 2
        k0 = math.ceil(lo_ax / step)
        ticks = [k * step for k in range(k0, int(math.floor(hi_ax / step)) + 1)]
    for t in ticks:
        tv = tr(t)
        if tv is None or tv < lo_ax or tv > hi_ax:
            continue
        xx = x(t)
        out.append(f'<line x1="{xx:.1f}" y1="{y_bottom + 6}" x2="{xx:.1f}" y2="{y_bottom + 11}" stroke="#000"/>')
        out.append(f'<text x="{xx:.1f}" y="{y_bottom + 24}" text-anchor="middle">{t:g}</text>')
    out.append(f'<text x="{left}" y="{y_bottom + 40}" font-size="11">← 介入が有利（低いほど良い指標）</text>')
    out.append(f'<text x="{right}" y="{y_bottom + 40}" font-size="11" text-anchor="end">対照が有利 →</text>')
    out.append("</svg>")
    return "\n".join(out)


def pool_fixed(entries, measure):
    """逆分散法(固定効果)の簡易統合。95%CIからSEを推定。参考値であり委員の確認が前提"""
    log = measure.upper() in RATIO
    num = den = 0.0
    for e in entries:
        p, lo, hi = e.get("point"), e.get("lo"), e.get("hi")
        if None in (p, lo, hi) or (log and min(p, lo, hi) <= 0):
            continue
        if log:
            p, lo, hi = math.log(p), math.log(lo), math.log(hi)
        se = (hi - lo) / 3.92
        if se <= 0:
            continue
        w = 1 / se ** 2
        num += w * p
        den += w
    if den == 0:
        return None
    m, se = num / den, math.sqrt(1 / den)
    lo, hi = m - 1.96 * se, m + 1.96 * se
    if log:
        m, lo, hi = math.exp(m), math.exp(lo), math.exp(hi)
    return {"label": "統合（固定効果・参考値）", "point": m, "lo": lo, "hi": hi}
