// StockGuard content script
// 흐름: 채널 식별 → 채널/영상탭 HTML fetch → feature 파싱 → Stage 0 게이트 →
//       규제어 + 모델 점수 → 차단/경고/통과 (modeling.ipynb 7장 3층 규칙)
// 차단 = 규제어 hit AND 점수 ≥ thresholds.block (모델 단독 차단 금지 — H1 기각 근거)
// 경고 = 점수 ≥ thresholds.warn

(() => {
  'use strict';

  const cache = new Map();          // channelKey → 판정 결과 (탭 세션 동안 유지)
  const sessionAllow = new Set();   // '그래도 보기' 누른 채널
  let currentBanner = null;

  // ---------- 파싱 유틸 ----------

  // "1.42만" / "1,234" / "3.5천" / "1.2억" → 숫자
  function parseKoNum(numStr, unit) {
    const n = parseFloat(numStr.replace(/,/g, ''));
    if (Number.isNaN(n)) return null;
    const mult = { '천': 1e3, '만': 1e4, '억': 1e8 }[unit] || 1;
    return n * mult;
  }

  function jsonUnescape(s) {
    try { return JSON.parse('"' + s + '"'); } catch { return s; }
  }

  function median(arr) {
    if (!arr.length) return null;
    const a = [...arr].sort((x, y) => x - y);
    const mid = a.length >> 1;
    return a.length % 2 ? a[mid] : (a[mid - 1] + a[mid]) / 2;
  }

  const log1p = (v) => (v === null ? null : Math.log1p(v));

  // 채널 루트 HTML에서 메타 추출. YouTube 내부 구조(ytInitialData 문자열) 의존 → 깨지면 null(중앙값 대치)
  function parseChannelHtml(html) {
    const out = { title: '', description: '', subs: null, videos: null,
                  totalViews: null, joined: null, country: null };

    let m = html.match(/"channelMetadataRenderer":\{"title":"((?:[^"\\]|\\.)*)","description":"((?:[^"\\]|\\.)*)"/);
    if (m) { out.title = jsonUnescape(m[1]); out.description = jsonUnescape(m[2]); }

    m = html.match(/구독자 ([\d.,]+)(천|만|억)?명/);
    if (m) out.subs = parseKoNum(m[1], m[2]);

    m = html.match(/동영상 ([\d.,]+)(천|만|억)?개/);
    if (m) out.videos = parseKoNum(m[1], m[2]);

    m = html.match(/조회수 ([\d,]+)회/);                      // 정보 탭 데이터가 실릴 때만 존재
    if (m) out.totalViews = parseKoNum(m[1]);

    m = html.match(/(\d{4})\. ?(\d{1,2})\. ?(\d{1,2})\.?[^"]{0,8}가입/);
    if (m) out.joined = new Date(+m[1], +m[2] - 1, +m[3]);

    m = html.match(/"country":\{"simpleText":"([^"]+)"\}/);
    if (m) out.country = m[1];

    return out;
  }

  // 영상 탭 HTML에서 영상별 조회수 + 제목 추출
  function parseVideosHtml(html) {
    const views = [];
    for (const m of html.matchAll(/조회수 ([\d.,]+)(천|만|억)?회/g)) {
      const v = parseKoNum(m[1], m[2]);
      if (v !== null) views.push(v);
    }
    const titles = [];
    for (const m of html.matchAll(/"title":\{"runs":\[\{"text":"((?:[^"\\]|\\.)*)"\}\]/g)) {
      titles.push(jsonUnescape(m[1]));
      if (titles.length >= 60) break;
    }
    return { medView: median(views.slice(0, 40)), titlesText: titles.join(' ') };
  }

  // ---------- 채널 식별 ----------

  function channelPathFromUrl() {
    const m = location.pathname.match(/^\/(@[^/]+|channel\/UC[\w-]{22}|c\/[^/]+|user\/[^/]+)/);
    return m ? '/' + m[1] : null;
  }

  function channelPathFromWatch() {
    const a = document.querySelector('ytd-video-owner-renderer a[href], #owner #channel-name a[href]');
    if (!a) return null;
    const m = a.getAttribute('href').match(/^\/(@[^/]+|channel\/UC[\w-]{22})/);
    return m ? '/' + m[1] : null;
  }

  // ---------- 판정 ----------

  async function assessChannel(chPath) {
    if (cache.has(chPath)) return cache.get(chPath);

    const base = 'https://www.youtube.com' + chPath;
    const [chHtml, vidHtml] = await Promise.all([
      fetch(base, { credentials: 'same-origin' }).then((r) => r.text()),
      fetch(base + '/videos', { credentials: 'same-origin' }).then((r) => r.text()).catch(() => ''),
    ]);

    const ch = parseChannelHtml(chHtml);
    const vids = parseVideosHtml(vidHtml);
    const fullText = ch.title + ' ' + ch.description + ' ' + vids.titlesText;

    // Stage 0: 주식·경제 채널 아니면 판단하지 않음(분포 밖 → 오탐 방지)
    if (!sgIsEconChannel(fullText)) {
      const out = { tier: 'pass', reason: '비경제 채널(게이트 통과)' };
      cache.set(chPath, out);
      return out;
    }

    const ageDays = ch.joined ? (Date.now() - ch.joined.getTime()) / 864e5 : null;
    const desc = ch.description || '';
    const feats = {
      log_subscriber_count: log1p(ch.subs),
      log_video_count: log1p(ch.videos),
      log_view_count: log1p(ch.totalViews),
      channel_age_days: ageDays,
      is_new_channel: ageDays === null ? null : (ageDays < 365 ? 1 : 0),
      is_kr: ch.country === null ? null : (/대한민국|South Korea|^KR$/.test(ch.country) ? 1 : 0),
      has_url_desc: /https?:\/\/|www\./i.test(desc) ? 1 : 0,
      has_kakao_desc: /open\.kakao\.com|pf\.kakao\.com|kko\.to|kakao\.com\//i.test(desc) ? 1 : 0,
      has_phone_desc: /01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}/.test(desc) ? 1 : 0,
      has_telegram_desc: /t\.me\/|telegram\.me\/|telegram\.org/i.test(desc) ? 1 : 0,
      has_band_desc: /band\.us/i.test(desc) ? 1 : 0,
      has_email_desc: /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/.test(desc) ? 1 : 0,
      log_med_view: log1p(vids.medView),
    };

    const hits = sgRegHits(fullText);
    const score = sgScore(feats);
    const T = STOCKGUARD_MODEL.thresholds;

    let tier = 'pass';
    if (hits.length > 0 && score >= T.block) tier = 'block';
    else if (score >= T.warn) tier = 'warn';

    const out = { tier, score, hits, title: ch.title };
    cache.set(chPath, out);
    return out;
  }

  // ---------- UI ----------

  function removeBanner() {
    if (currentBanner) { currentBanner.remove(); currentBanner = null; }
    document.documentElement.classList.remove('sg-blocked');
  }

  function renderResult(chPath, res) {
    removeBanner();
    if (res.tier === 'pass') return;

    const el = document.createElement('div');
    el.className = 'sg-banner ' + (res.tier === 'block' ? 'sg-block' : 'sg-warn');

    const reason = res.hits.length
      ? `규제어 감지: ${res.hits.join(', ')} (금융위 금지광고·금감원 불법유형)`
      : '행동·구조 패턴 의심 점수';
    const scoreTxt = `의심 점수 ${res.score.toFixed(2)}`;

    el.innerHTML = `
      <div class="sg-head">${res.tier === 'block' ? '🚫 리딩방 의심 채널 차단' : '⚠️ 리딩방 의심 채널 경고'}</div>
      <div class="sg-body">
        <b>${res.title || chPath}</b> — ${reason} · ${scoreTxt}<br>
        이 표시는 데이터 분석 기반 <b>의심 정보</b>이며 법적 판단이 아닙니다.
        피해가 의심되면 <a href="https://fine.fss.or.kr" target="_blank" rel="noopener">금감원 불법금융신고센터</a>로 신고하세요.
      </div>
      <div class="sg-actions">
        <button class="sg-btn sg-once">그래도 보기</button>
        <button class="sg-btn sg-always">이 채널 항상 허용</button>
      </div>`;

    el.querySelector('.sg-once').addEventListener('click', () => {
      sessionAllow.add(chPath);
      removeBanner();
    });
    el.querySelector('.sg-always').addEventListener('click', () => {
      chrome.storage.local.get({ whitelist: [] }, (d) => {
        if (!d.whitelist.includes(chPath)) d.whitelist.push(chPath);
        chrome.storage.local.set({ whitelist: d.whitelist });
      });
      sessionAllow.add(chPath);
      removeBanner();
    });

    document.body.appendChild(el);
    currentBanner = el;
    if (res.tier === 'block') document.documentElement.classList.add('sg-blocked');
  }

  // ---------- 메인 ----------

  let lastKey = '';

  async function run() {
    const chPath = channelPathFromUrl() || (location.pathname === '/watch' ? channelPathFromWatch() : null);
    const key = location.href + '|' + (chPath || '');
    if (key === lastKey) return;
    lastKey = key;

    removeBanner();
    if (!chPath || sessionAllow.has(chPath)) return;

    const { enabled, whitelist } = await new Promise((res) =>
      chrome.storage.local.get({ enabled: true, whitelist: [] }, res));
    if (!enabled || whitelist.includes(chPath)) return;

    try {
      const res = await assessChannel(chPath);
      // 비동기 동안 다른 페이지로 이동했으면 그리지 않음
      if (lastKey === key) renderResult(chPath, res);
    } catch (e) {
      // 파싱 실패 = 판단 보류(오탐 방지). 콘솔만.
      console.debug('[StockGuard]', e);
    }
  }

  document.addEventListener('yt-navigate-finish', () => setTimeout(run, 400));
  setInterval(run, 2000);   // SPA 내비게이션 이벤트 누락 대비
  run();
})();
