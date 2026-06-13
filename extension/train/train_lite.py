# 익스텐션용 경량 모델 학습 — 채널 페이지에서 즉시 파싱 가능한 feature만 사용
# 입력: data/processed/{channels_clean, channel_features, videos_clean}.csv
# 출력: extension/model_data.js (forest + threshold + median + 메타)
# 라벨은 modeling.ipynb 2장과 동일 규칙(규제어 시드)로 재구축

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (f1_score, precision_recall_curve, precision_score,
                             recall_score, roc_auc_score)
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parents[2]
P = ROOT / 'data' / 'processed'
OUT = ROOT / 'extension' / 'model_data.js'

chc = pd.read_csv(P / 'channels_clean.csv')
cf = pd.read_csv(P / 'channel_features.csv')
vdc = pd.read_csv(P / 'videos_clean.csv', usecols=['channel_id', 'title', 'description'])

# ---- 시드 라벨: modeling.ipynb 2장과 동일 ----
REG = {
    '수익보장': r'수익률?\s*보장|원금\s*보장|손실\s*보전',
    'VIP'    : r'VIP\s*(?:방|반|종목|클럽|멤버|회원)|브이아이피',
    '리딩방' : r'리딩\s*방|주식\s*리딩|무료\s*리딩',
    '종목추천': r'종목\s*추천|추천\s*종목|추천주',
    '자동매매': r'자동\s*매매',
}
vdc['txt'] = vdc['title'].fillna('') + ' ' + vdc['description'].fillna('')
vtext = vdc.groupby('channel_id')['txt'].apply(' '.join)
text = (chc['description'].fillna('') + ' ' + chc['channel_id'].map(vtext).fillna('')).set_axis(chc['channel_id'])

H = pd.DataFrame({k: text.str.count(p, flags=re.I) for k, p in REG.items()})
H['kinds'] = (H[list(REG)] > 0).sum(axis=1)
H['total'] = H[list(REG)].sum(axis=1)
seed = pd.Series('unlabeled', index=H.index)
seed[H['total'] == 0] = 'normal'
seed[(H['kinds'] >= 2) | (H['total'] >= 5)] = 'suspect'

# ---- 형식 플래그: 배포 시 채널 desc만 읽으므로 학습도 desc 단독으로 재계산(의미 일치) ----
contact_pats = {
    'has_url'     : r'https?://|www\.',
    'has_kakao'   : r'open\.kakao\.com|pf\.kakao\.com|kko\.to|kakao\.com/',
    'has_phone'   : r'01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}',
    'has_telegram': r't\.me/|telegram\.me/|telegram\.org',
    'has_band'    : r'band\.us',
    'has_email'   : r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',
}
desc = chc.set_index('channel_id')['description'].fillna('').astype(str)
flags = pd.DataFrame({f'{k}_desc': desc.str.contains(p, case=False, regex=True).astype(int)
                      for k, p in contact_pats.items()})

# ---- 경량 feature 13개 ----
df = cf.set_index('channel_id').join(flags)
df['log_med_view'] = np.log1p(df['med_view'])
FEATS = ['log_subscriber_count', 'log_video_count', 'log_view_count',
         'channel_age_days', 'is_new_channel', 'is_kr',
         'has_url_desc', 'has_kakao_desc', 'has_phone_desc',
         'has_telegram_desc', 'has_band_desc', 'has_email_desc',
         'log_med_view']
df['seed'] = seed

med = df[FEATS].median(numeric_only=True)
m = df['seed'] != 'unlabeled'
X = df.loc[m, FEATS].fillna(med)
y = (df.loc[m, 'seed'] == 'suspect').astype(int)
X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.25, stratify=y, random_state=42)

rf = RandomForestClassifier(n_estimators=100, max_depth=8,
                            class_weight='balanced', random_state=42).fit(X_tr, y_tr)

score_te = rf.predict_proba(X_te)[:, 1]
pred = (score_te >= 0.5).astype(int)
print(f'lite RF (13 feat)  AUC={roc_auc_score(y_te, score_te):.3f}  '
      f'recall={recall_score(y_te, pred):.3f}  precision={precision_score(y_te, pred):.3f}  '
      f'F1={f1_score(y_te, pred):.3f}   (참고: full 36 feat AUC 0.81)')

prec, rec, thr = precision_recall_curve(y_te, score_te)
ops = {}
for name, pt in [('block', 0.9), ('warn', 0.7)]:
    # prec[i]는 thr[i]에 대응(sklearn 문서). 마지막 점(prec=1,rec=0)은 thr 없음 → prec를 thr 길이로 자름
    pr = prec[:len(thr)]
    reach = pr >= pt
    if reach.any():
        # 목표 precision 달성 점들 중 recall 최대(= threshold 최소) 선택. 노이즈성 첫 교차 회피
        cand = np.flatnonzero(reach)
        i = int(cand[np.argmax(rec[cand])])
    else:
        # 목표 precision 도달 불가 → 달성 가능한 최대 precision 점으로 폴백(전량 차단 사고 방지)
        i = int(np.argmax(pr))
        print(f'  ⚠ precision {pt} 도달불가 — 최대 precision {pr[i]:.3f}로 폴백')
    ops[name] = float(thr[i])
    print(f'precision ≥ {pt}: threshold={ops[name]:.3f}  recall={rec[i]:.3f}  precision={pr[i]:.3f}')

imp = pd.Series(rf.feature_importances_, index=FEATS).sort_values(ascending=False)
print('\nfeature importance:')
print(imp.round(3).to_string())

# ---- forest 직렬화 (JS 평가기용 평탄 배열) ----
trees = []
for est in rf.estimators_:
    t = est.tree_
    val = t.value[:, 0, :]
    prob = val[:, 1] / val.sum(axis=1)
    trees.append({
        'f': t.feature.tolist(),
        't': [round(float(x), 6) for x in t.threshold],
        'l': t.children_left.tolist(),
        'r': t.children_right.tolist(),
        'v': [round(float(x), 6) for x in prob],
    })

# 직렬화 검증: python으로 forest 재평가 → sklearn predict_proba와 일치 확인
def eval_forest(row):
    s = 0.0
    for tr in trees:
        n = 0
        while tr['l'][n] != -1:
            n = tr['l'][n] if row[tr['f'][n]] <= tr['t'][n] else tr['r'][n]
        s += tr['v'][n]
    return s / len(trees)

chk = X_te.head(200).to_numpy()
mine = np.array([eval_forest(r) for r in chk])
diff = np.abs(mine - rf.predict_proba(X_te.head(200))[:, 1]).max()
assert diff < 1e-4, f'직렬화 불일치 max diff={diff}'
print(f'\n직렬화 검증 OK (max diff {diff:.2e})')

model = {
    'features': FEATS,
    'medians': {k: round(float(v), 6) for k, v in med.items()},
    'thresholds': {k: round(v, 3) for k, v in ops.items()},
    'n_trees': len(trees),
    'trees': trees,
}
OUT.write_text('// train_lite.py가 생성. 직접 수정 금지.\n'
               'const STOCKGUARD_MODEL = '
               + json.dumps(model, ensure_ascii=False, separators=(',', ':'))
               + ';\n')
print(f'\n저장: {OUT}  ({OUT.stat().st_size / 1024:.0f} KB, trees={len(trees)})')
