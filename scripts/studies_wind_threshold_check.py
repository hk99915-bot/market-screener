import json
import sys

sys.path.insert(0, '.')
from screener import macroview as mv

ms = json.load(open('reports/macro_series.json'))['series']
dates = [r[0] for r in ms['SPX']]
out = []
for d in dates[260:]:
    sub = {k: [r for r in v if r[0] <= d] for k, v in ms.items()}
    stats = {k: x for k, x in ((k, mv._stats(r)) for k, r in sub.items() if r) if x}
    num = den = 0
    for k in mv.ORDER:
        s = stats.get(k)
        if not s:
            continue
        try:
            _, sc = mv.explain(k, s, stats)
        except Exception:
            continue
        if sc is not None:
            num += mv.W.get(k, 0.5) * sc
            den += mv.W.get(k, 0.5)
    if den:
        out.append((d, num / den))
sc = [x for _, x in out]
dif = sorted(abs(b - a) for a, b in zip(sc, sc[1:]))
sa = sorted(abs(x) for x in sc)


def q(a, p):
    return a[int(p * (len(a) - 1))]


print('n', len(sc), out[0][0], out[-1][0], 'last %.3f' % sc[-1])
print('|d1| median %.3f p75 %.3f p90 %.3f' % (q(dif, .5), q(dif, .75), q(dif, .9)))
print('|s| p10 %.3f p25 %.3f median %.3f' % (q(sa, .1), q(sa, .25), q(sa, .5)))
print('share |s|<0.05 %.0f%%  <0.15 %.0f%%' % (100 * sum(x < 0.05 for x in sa) / len(sa), 100 * sum(x < 0.15 for x in sa) / len(sa)))
flips = sum(1 for a, b in zip(sc, sc[1:]) if (a >= 0.05 and b <= -0.05) or (a <= -0.05 and b >= 0.05))
flips0 = sum(1 for a, b in zip(sc, sc[1:]) if a * b < 0)
print('day-over-day flips across ±0.05 band', flips, ' raw sign flips', flips0)
# label persistence: share of days where label (3-way at 0.05) equals the label 5 days later
lab = [0 if abs(x) < 0.05 else (1 if x > 0 else -1) for x in sc]
print('label same after 5d %.0f%%' % (100 * sum(a == b for a, b in zip(lab, lab[5:])) / (len(lab) - 5)))
y = [r[4] for r in ms['US10Y']]
d5 = sorted(abs(b - a) * 100 for a, b in zip(y, y[5:]))
d1 = sorted(abs(b - a) * 100 for a, b in zip(y, y[1:]))
print('US10Y n', len(y), ms['US10Y'][-1][0], 'last', y[-1])
print('|5d| bp p25 %.1f median %.1f p75 %.1f; |1d| median %.1f p75 %.1f' % (q(d5, .25), q(d5, .5), q(d5, .75), q(d1, .5), q(d1, .75)))
print('share |5d|<2bp %.0f%%  <5bp %.0f%%' % (100 * sum(x < 2 for x in d5) / len(d5), 100 * sum(x < 5 for x in d5) / len(d5)))
