"""
전체 수집 파이프라인 실행 모듈.
채널 검색 → 채널 상세 → 영상 수집 → 댓글 수집 순서로 진행.
재실행 시 이미 처리된 단계는 자동으로 건너뜁니다.
쿼터 초과 시 현재까지 저장된 데이터를 유지하고 프로세스를 종료합니다.
"""
import sys
import time

from config.settings import (
    SEARCH_QUERIES,
    REQUEST_DELAY_SECONDS,
    YOUTUBE_API_KEYS,
)
from src.db import (
    init_db,
    channel_exists,
    is_videos_fetched,
    mark_videos_fetched,
    get_searched_queries,
    insert_channel,
    insert_video,
    insert_comment,
    mark_comments_disabled,
    mark_comments_fetched,
    get_channel_ids,
    get_video_ids_for_channel,
    get_conn,
)
from src.collector import (
    QuotaExceeded,
    build_youtube_client,
    search_channels,
    fetch_channel_details,
    fetch_videos_for_channel,
    fetch_comments_for_video,
    get_uploads_playlist_id,
)


def _print_summary():
    """현재까지 수집된 데이터 현황 출력."""
    with get_conn() as conn:
        channels = conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0]
        videos   = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
        comments = conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
    print(f"\n  채널 {channels:,}개 | 영상 {videos:,}개 | 댓글 {comments:,}개 저장됨")


def _quota_exit():
    """쿼터 초과 안내 후 종료."""
    print("\n" + "!" * 50)
    print("YouTube API 일일 쿼터 초과 (모든 키 소진)")
    print("수집된 데이터는 모두 저장되었습니다.")
    _print_summary()
    print("내일 오후 4시(KST) 쿼터 리셋 후 재실행하면 이어서 수집됩니다.")
    print("!" * 50)
    sys.exit(0)


class KeyRotator:
    """쿼터 초과 시 다음 API 키로 교체. 전 키 소진 시 종료."""

    def __init__(self):
        self.keys = YOUTUBE_API_KEYS or [None]
        self.idx = 0
        self.youtube = build_youtube_client(self.keys[0])
        print(f"  → API 키 {len(self.keys)}개 로드됨 (키 1 사용 중)")

    def rotate(self) -> bool:
        """다음 키로 교체. 성공 시 True, 더 없으면 False."""
        self.idx += 1
        if self.idx >= len(self.keys):
            return False
        self.youtube = build_youtube_client(self.keys[self.idx])
        print(f"\n  !! 쿼터 초과 → API 키 {self.idx + 1}로 교체")
        return True


def run():
    """전체 파이프라인 실행."""
    print("=" * 50)
    print("StockGuard 유튜브 데이터 수집 시작")
    print("=" * 50)

    init_db()
    youtube = build_youtube_client()

    # ── STEP 1 & 2: 검색어 순회 → 채널 수집 ──────────────
    print("\n[1단계] 채널 검색 및 상세 정보 수집")

    already_searched = get_searched_queries()
    remaining_queries = [q for q in SEARCH_QUERIES if q not in already_searched]

    if not remaining_queries:
        print("  → 모든 검색어 수집 완료 (건너뜀)")
    else:
        print(f"  → 남은 검색어 {len(remaining_queries)}개 / 전체 {len(SEARCH_QUERIES)}개")
        all_known_ids: set[str] = set(get_channel_ids())

        for query in remaining_queries:
            print(f"\n검색어: '{query}'")
            try:
                found_ids = search_channels(youtube, query)
                new_ids = [cid for cid in found_ids if cid not in all_known_ids]
                all_known_ids.update(new_ids)

                if not new_ids:
                    print("  → 새 채널 없음, 건너뜀")
                    continue

                channels = fetch_channel_details(youtube, new_ids, search_query=query)
                saved = 0
                for ch in channels:
                    if not channel_exists(ch["channel_id"]):
                        insert_channel(ch)
                        saved += 1
                print(f"  → {saved}개 채널 저장 완료")

            except QuotaExceeded:
                _quota_exit()

            time.sleep(REQUEST_DELAY_SECONDS)

    # ── STEP 3: 저장된 채널 → 영상 수집 ────────────────────
    print("\n[2단계] 채널별 영상 수집")
    channel_ids = get_channel_ids()
    pending = [cid for cid in channel_ids if not is_videos_fetched(cid)]
    print(f"총 {len(channel_ids)}개 채널 중 {len(pending)}개 미수집")

    for idx, channel_id in enumerate(pending, 1):
        print(f"  [{idx}/{len(pending)}] {channel_id}", end=" ", flush=True)
        try:
            uploads_id = get_uploads_playlist_id(youtube, channel_id)
            if not uploads_id:
                print("→ 재생목록 없음, 스킵")
                mark_videos_fetched(channel_id)
                continue
            videos = fetch_videos_for_channel(youtube, channel_id, uploads_id)
            for v in videos:
                insert_video(v)
            mark_videos_fetched(channel_id)
            print(f"→ 영상 {len(videos)}개 저장")

        except QuotaExceeded:
            print()
            _quota_exit()

        time.sleep(REQUEST_DELAY_SECONDS)

    # ── STEP 4: 전체 영상 → 댓글 수집 (video 단위 skip) ─────
    print("\n[3단계] 영상별 댓글 수집")

    with get_conn() as conn:
        pending_videos = conn.execute("""
            SELECT v.video_id, v.channel_id
            FROM videos v
            WHERE v.comments_disabled = 0
              AND v.comments_fetched = 0
            ORDER BY v.channel_id
        """).fetchall()

    pending_videos = [(r["video_id"], r["channel_id"]) for r in pending_videos]
    print(f"미수집 영상 {len(pending_videos):,}개")

    rotator = KeyRotator()

    for idx, (video_id, channel_id) in enumerate(pending_videos, 1):
        print(f"  [{idx:,}/{len(pending_videos):,}] {video_id}", end=" ", flush=True)
        # 쿼터 초과 시 다음 키로 교체 후 같은 영상 재시도
        while True:
            try:
                comments, disabled = fetch_comments_for_video(
                    rotator.youtube, video_id, channel_id
                )
                for c in comments:
                    insert_comment(c)
                if disabled:
                    mark_comments_disabled(video_id)
                else:
                    mark_comments_fetched(video_id)
                print(f"→ 댓글 {len(comments)}개{' [disabled]' if disabled else ''}")
                time.sleep(REQUEST_DELAY_SECONDS)
                break

            except QuotaExceeded:
                if not rotator.rotate():
                    _quota_exit()

    print("\n" + "=" * 50)
    print("수집 완료!")
    _print_summary()
    print("=" * 50)
