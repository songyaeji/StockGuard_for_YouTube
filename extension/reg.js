// 규제어 regex(라벨 근거: 금융위 2024.8.14 금지광고 + 금감원 불법유형) + Stage 0 도메인 게이트.
// modeling.ipynb 2장 REG와 동일 패턴 — 수정 시 양쪽 함께.

const SG_REG = {
  '수익보장': /수익률?\s*보장|원금\s*보장|손실\s*보전/i,
  'VIP':     /VIP\s*(?:방|반|종목|클럽|멤버|회원)|브이아이피/i,
  '리딩방':   /리딩\s*방|주식\s*리딩|무료\s*리딩/i,
  '종목추천': /종목\s*추천|추천\s*종목|추천주/i,
  '자동매매': /자동\s*매매/i,
};

// Stage 0: 주식·경제 채널만 Stage 1 점수로 보냄(학습 모집단 = 주식 검색 채널 → 비경제 채널은 분포 밖).
// '리딩'·'애널리스트'는 동음이의어 오염(독서·타로·데이터분석, preprocessing 4-3)이라 게이트에서 제외.
const SG_GATE = [
  '주식', '증권', '투자', '종목', '코스피', '코스닥', '재테크', '단타',
  '급등주', '테마주', '시황', '차트', '매매', '배당', 'ETF', '선물',
  '옵션', '펀드', '상한가', '수익률',
];

function sgRegHits(text) {
  if (!text) return [];
  return Object.entries(SG_REG)
    .filter(([, pat]) => pat.test(text))
    .map(([name]) => name);
}

function sgIsEconChannel(text) {
  if (!text) return false;
  // 규제어가 직접 잡히면 그 자체가 금융 문맥 → 게이트 통과
  return SG_GATE.some((w) => text.includes(w)) || sgRegHits(text).length > 0;
}
