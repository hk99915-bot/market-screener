"""PB 금 헤지 재현(rounds/2026-10-27/pb_gold_hedge_check.md)에 5·20일 창 추가. 겹치는 창 + 비겹침 창 둘 다."""
import json

import pandas as pd

S = json.load(open('reports/macro_series.json'))['series']


def cl(k):
    df = pd.DataFrame(S[k]).iloc[:, :5]
    df.columns = ['d', 'o', 'h', 'l', 'c']
    return df.set_index(pd.to_datetime(df['d']))['c'].astype(float)


spx, gold, krw, ks = cl('SPX'), cl('GOLD'), cl('USDKRW'), cl('KOSPI')
px = pd.concat({'spx': spx, 'gold': gold, 'krw': krw, 'ks': ks}, axis=1).ffill().dropna()
px = px[px.index >= '2024-09-27']
px['gk'] = px.gold * px.krw
print('range', px.index.min().date(), px.index.max().date(), 'n', len(px))
for n in (1, 5, 20):
    r = px.pct_change(n).dropna()
    for idx, gcol in (('ks', 'gk'), ('spx', 'gk'), ('spx', 'gold')):
        for mode in ('overlap', 'nonoverlap'):
            rr = r if mode == 'overlap' else r.iloc[::n]
            w = rr[rr[idx] <= rr[idx].quantile(.05)]
            print(f'{n:>2}d {mode:<10} {idx} worst5% n={len(w):>3} idx {w[idx].mean()*100:+.1f}%  {gcol} {w[gcol].mean()*100:+.2f}%  up {100*(w[gcol]>0).mean():.0f}%  corr(all) {rr[idx].corr(rr[gcol]):+.2f}')
