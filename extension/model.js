// RandomForest 평가기 — model_data.js(STOCKGUARD_MODEL)의 직렬화 forest를 순회.
// 결측 feature는 학습 데이터 중앙값으로 대치(train_lite.py와 동일 규칙).

function sgScore(featObj) {
  const M = STOCKGUARD_MODEL;
  const x = M.features.map((f) => {
    const v = featObj[f];
    return (v === null || v === undefined || Number.isNaN(v)) ? M.medians[f] : v;
  });
  let sum = 0;
  for (const tr of M.trees) {
    let n = 0;
    while (tr.l[n] !== -1) {
      n = x[tr.f[n]] <= tr.t[n] ? tr.l[n] : tr.r[n];
    }
    sum += tr.v[n];
  }
  return sum / M.n_trees;
}
