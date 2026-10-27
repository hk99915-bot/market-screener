import json
import pandas as pd
d=json.load(open('/home/user/market-screener/reports/macro_series.json'))
S=d['series']
def cl(k):
    rows=S[k]; df=pd.DataFrame(rows)
    df.columns=['d','o','h','l','c','v'][:df.shape[1]]
    return df.set_index(pd.to_datetime(df['d']))['c'].astype(float)
spx,gold,y,krw,ks=cl('SPX'),cl('GOLD'),cl('US10Y'),cl('USDKRW'),cl('KOSPI')
df=pd.concat({'spx':spx.pct_change(),'gold':gold.pct_change(),'y':y.diff()*100 if y.max()<20 else y.diff(),'krw':krw.pct_change()},axis=1).dropna()
df=df[(df.index>='2024-09-01')]
print('n',len(df), df.index.min().date(), df.index.max().date())
q=df.spx.quantile(.05); w=df[df.spx<=q]
print('SPX worst5%:',len(w),'spx',round(w.spx.mean()*100,2),'gold',round(w.gold.mean()*100,2),'up%',round((w.gold>0).mean()*100))
gk=(1+df.gold)*(1+df.krw)-1
print('  gold in KRW',round(gk[w.index].mean()*100,2),'up%',round((gk[w.index]>0).mean()*100))
qy=df.y.quantile(.95); wy=df[df.y>=qy]
print('US10Y top5%:',len(wy),'dy',round(wy.y.mean(),1),'gold',round(wy.gold.mean()*100,2),'up%',round((wy.gold>0).mean()*100),'spx',round(wy.spx.mean()*100,2))
k=pd.concat({'ks':ks.pct_change(),'gold':gold.pct_change(),'krw':krw.pct_change()},axis=1).dropna(); k=k[k.index>='2024-09-01']
qk=k.ks.quantile(.05); wk=k[k.ks<=qk]; gk2=(1+wk.gold)*(1+wk.krw)-1
print('KOSPI worst5%:',len(wk),'kospi',round(wk.ks.mean()*100,2),'gold$',round(wk.gold.mean()*100,2),'goldKRW',round(gk2.mean()*100,2),'up%',round((gk2>0).mean()*100))
for dt in ['2026-10-22','2026-10-23']:
    if pd.Timestamp(dt) in df.index: r=df.loc[dt]; print(dt,'spx',round(r.spx*100,2),'gold',round(r.gold*100,2))
print('gold last',gold.iloc[-1], gold.index[-1].date())
