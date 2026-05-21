"""
전체 수집 파이프라인 실행 모듈.
채널 검색 → 채널 상세 → 영상 수집 → 댓글 수집 순서로 진행.
재실행 시 이미 처리된 단계는 자동으로 건너뜁니다.
"""
import time

from googleapiclient.errors import HttpError

from config.settings import (
    SEARCH_QUERIES,
    COMMENT_TARGET_VIDEOS,
    REQUEST_DELAY_SECONDS,
)
from src.db import (
    init_db,
    channel_exists,
    has_videos,
    get_searched_queries,
    insert_channel,
    insert_video,
    insert_comment,
    get_channel_ids,
    get_video_ids_for_channel,
)
from src.collector import (
    build_youtube_client,
    search_channels,
    fetch_channel_details,
    fetch_videos_for_channel,
    fetch_comments_for_video,
    get_uploads_playlist_id,
)


def run():
    """전체 파이프라인 실행."""
    print("=" * 50)
    print("StockGuard 유튜브 데이터 수집 시작")
    print("=" * 50)

    init_db()
    youtube = build_youtube_client()

    # ── STEP 1 & 2: 검색어 순회 → 채널 수집 ──────────────
    print("\n[1단계] 채널 검색 및 상세 정보 수집")

    # 이전 실행에서 이미 검색된 쿼리는 건너뜀 (쿼터 절약)
    already_searched = get_searched_queries()
    remaining_queries = [q for q in SEARCH_QUERIES if q not in already_searched]

    if not remaining_queries:
        print("  → 모든 검색어 수집 완료 (건너뜀)")
    else:
        print(f"  → 남은 검색어 {len(remaining_queries)}개 / 전체 {len(SEARCH_QUERIES)}개")
        all_known_ids: set[str] = set(get_channel_ids())

        quota_exceeded = False
        for query in remaining_queries:
            print(f"\n검색어: '{query}'")
            try:
                found_ids = search_channels(youtube, query)
            except HttpError as e:
                if e.status_code == 403:
                    # 쿼터 초과 - 검색 단계 중단하고 영상 수집으로 넘어감
                    print(f"\n  [!] API 쿼터 초과 — 검색 중단, 영상 수집으로 이동")
                    quota_exceeded = True
                    break
                raise

            # 이미 DB에 있는 채널 제외
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
            time.sleep(REQUEST_DELAY_SECONDS)

    # ── STEP 3: 저장된 채널 → 영상 수집 ────────────────────
    print("\n[2단계] 채널별 영상 수집")
    channel_ids = get_channel_ids()
    pending = [cid for cid in channel_ids if not has_videos(cid)]
    print(f"총 {len(channel_ids)}개 채널 중 {len(pending)}개 미수집")

    for idx, channel_id in enumerate(pending, 1):
        print(f"  [{idx}/{len(pending)}] {channel_id}", end=" ", flush=True)

        uploads_id = get_uploads_playlist_id(youtube, channel_id)
        if not uploads_id:
            print("→ 재생목록 없음, 스킵")
            continue

        videos = fetch_videos_for_channel(youtube, channel_id, uploads_id)
        for v in videos:
            insert_video(v)
        print(f"→ 영상 {len(videos)}개 저장")
        time.sleep(REQUEST_DELAY_SECONDS)

    # ── STEP 4: 채널당 상위 영상 → 댓글 수집 ────────────────
    print("\n[3단계] 영상별 댓글 수집")

    # 댓글이 하나도 없는 채널만 대상으로 함
    from src.db import get_conn
    with get_conn() as conn:
        done_channels = {r["channel_id"] for r in conn.execute(
            "SELECT DISTINCT channel_id FROM comments"
        ).fetchall()}

    comment_targets = [cid for cid in channel_ids if cid not in done_channels]
    print(f"총 {len(channel_ids)}개 채널 중 {len(comment_targets)}개 미수집")

    for idx, channel_id in enumerate(comment_targets, 1):
        video_ids = get_video_ids_for_channel(channel_id, COMMENT_TARGET_VIDEOS)
        if not video_ids:
            continue

        print(f"  [{idx}/{len(comment_targets)}] {channel_id} → {len(video_ids)}개 영상")
        quota_hit = False
        for video_id in video_ids:
            try:
                comments = fetch_comments_for_video(youtube, video_id, channel_id)
            except Exception:
                print("\n  [!] API 쿼터 초과 — 댓글 수집 중단 (내일 재실행 시 이어받기)")
                quota_hit = True
                break
            for c in comments:
                insert_comment(c)
            print(f"    {video_id} → 댓글 {len(comments)}개")
            time.sleep(REQUEST_DELAY_SECONDS)
        if quota_hit:
            break

    print("\n" + "=" * 50)
    print("수집 완료!")
    print("=" * 50)
