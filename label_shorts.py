#!/usr/bin/env python
"""진짜 Shorts 라벨을 원본 DB videos.is_shorts 컬럼에 기록.

판별 원리(동시성 1, 순차):
- duration>180s → 정책상 Shorts 불가 → 요청 없이 is_shorts=0
- duration<=180s(또는 NULL) → GET youtube.com/shorts/{id}, allow_redirects=False
    - 200          → Shorts        → is_shorts=1
    - 30x → /watch → 일반 영상      → is_shorts=0
    - 404/오류/모호 → 판별 불가      → is_shorts NULL 유지(다음 실행서 재시도)

저장(원본 보존):
- 원본 data/youtube_channels.db는 읽지도 쓰지도 않음(첫 실행 시 1회 복사만).
- 복사본 data/processed/youtube_channels_labeled.db videos 에 is_shorts(INTEGER) 컬럼 추가 후 UPDATE.
- 검수 후 사용자가 복사본을 원본으로 승격할지는 별도 결정(스크립트는 원본 미변경).

resume:
- 복사본의 is_shorts IS NULL 인 행만 처리 → 중단돼도 재실행 시 이어감. 25행마다 commit.
"""
import os, time, random, shutil, sqlite3
import requests

ROOT = os.path.dirname(os.path.abspath(__file__))
SRC  = os.path.join(ROOT, 'data', 'youtube_channels.db')                      # 원본(read-only, 복사용)
DB   = os.path.join(ROOT, 'data', 'processed', 'youtube_channels_labeled.db')  # 작업 복사본
UA     = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
          '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')
HEADERS   = {'User-Agent': UA, 'Accept-Language': 'ko,en;q=0.9'}
DELAY     = 0.3
JITTER    = 0.3
TIMEOUT   = 10
MAX_RETRY = 4
COMMIT_EVERY = 25


def ensure_copy():
    if not os.path.exists(DB):
        os.makedirs(os.path.dirname(DB), exist_ok=True)
        shutil.copy2(SRC, DB)
        print(f'원본 복사본 생성: {DB} (원본 미수정)', flush=True)


def ensure_column(con):
    cols = [r[1] for r in con.execute('PRAGMA table_info(videos)')]
    if 'is_shorts' not in cols:
        con.execute('ALTER TABLE videos ADD COLUMN is_shorts INTEGER')
        con.commit()
        print('videos.is_shorts 컬럼 추가', flush=True)


def get_pending(con):
    return con.execute(
        'SELECT video_id, duration_seconds FROM videos WHERE is_shorts IS NULL'
    ).fetchall()


def label_long(con, pending):
    """duration>180s = Shorts 불가 → 요청 없이 is_shorts=0. 남은(≤180·NULL) 반환."""
    longs = [(v,) for v, d in pending if d is not None and d > 180]
    todo  = [v for v, d in pending if not (d is not None and d > 180)]
    if longs:
        con.executemany('UPDATE videos SET is_shorts=0 WHERE video_id=?', longs)
        con.commit()
        print(f'>180s {len(longs):,}개 is_shorts=0 기록(요청 없음)', flush=True)
    return todo


def classify(vid, session):
    url = f'https://www.youtube.com/shorts/{vid}'
    backoff = 2.0
    for _ in range(MAX_RETRY):
        try:
            resp = session.get(url, allow_redirects=False, timeout=TIMEOUT)
            sc = resp.status_code
            if sc == 200:
                return 1                                   # Shorts
            if sc in (301, 302, 303, 307, 308):
                loc = resp.headers.get('Location', '')
                return 0 if '/watch' in loc else None      # /watch=일반 / 그외=모호
            if sc == 404:
                return None                                # 삭제·비공개 → 판별 불가
            if sc == 429:
                time.sleep(backoff); backoff *= 2; continue
            return None
        except requests.RequestException:
            time.sleep(backoff); backoff *= 2
    return None


def run_requests(con, todo, session):
    t0 = time.time()
    pending_commit = 0
    for i, vid in enumerate(todo, 1):
        val = classify(vid, session)
        if val is not None:                                # 확신(0/1)만 기록, 모호는 NULL 유지
            con.execute('UPDATE videos SET is_shorts=? WHERE video_id=?', (val, vid))
            pending_commit += 1
        if pending_commit >= COMMIT_EVERY:
            con.commit(); pending_commit = 0
        time.sleep(DELAY + random.random() * JITTER)
        if i % 200 == 0:
            el = time.time() - t0
            rate = i / el if el else 0
            eta = (len(todo) - i) / rate / 60 if rate else 0
            print(f'{i:,}/{len(todo):,}  {rate:.1f} req/s  ETA {eta:.0f}분', flush=True)
    con.commit()


def main():
    ensure_copy()
    con = sqlite3.connect(DB)
    try:
        ensure_column(con)
        pending = get_pending(con)
        print(f'is_shorts 미기록 {len(pending):,}개', flush=True)
        todo = label_long(con, pending)
        print(f'redirect 요청 대상(≤180s) {len(todo):,}개', flush=True)
        if not todo:
            print('요청 대상 없음 — 종료', flush=True)
            return
        sess = requests.Session(); sess.headers.update(HEADERS)
        run_requests(con, todo, sess)
        # 최종 분포
        dist = dict(con.execute(
            'SELECT is_shorts, COUNT(*) FROM videos GROUP BY is_shorts').fetchall())
        print(f'완료 — is_shorts 분포: {dist}', flush=True)
    finally:
        con.close()


if __name__ == '__main__':
    main()
