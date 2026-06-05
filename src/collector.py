"""
YouTube Data API v3 호출 및 데이터 파싱 함수 모음.
각 단계(채널검색 → 채널상세 → 영상 → 댓글)를 독립 함수로 분리.
"""
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import googleapiclient.discovery
from googleapiclient.errors import HttpError


class QuotaExceeded(Exception):
    """YouTube API 일일 쿼터 초과 시 발생."""
    pass


def _check_quota(e: HttpError):
    """HttpError가 쿼터 초과인 경우 QuotaExceeded로 변환."""
    if e.status_code == 403 and "quotaExceeded" in str(e):
        raise QuotaExceeded("YouTube API 일일 쿼터 초과") from e

from config.settings import (
    YOUTUBE_API_KEY,
    RAW_DIR,
    MAX_CHANNELS_PER_QUERY,
    MAX_SEARCH_PAGES,
    VIDEOS_PER_CHANNEL,
    COMMENT_TARGET_VIDEOS,
    COMMENTS_PER_VIDEO,
    REQUEST_DELAY_SECONDS,
)


def _now() -> str:
    """현재 UTC 시각을 ISO 8601 문자열로 반환."""
    return datetime.now(timezone.utc).isoformat()


def _save_raw(subdir: str, filename: str, data: dict):
    """API 원본 응답을 JSON 파일로 백업."""
    path = RAW_DIR / subdir
    path.mkdir(parents=True, exist_ok=True)
    with open(path / filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _parse_duration(iso_duration: str) -> int:
    """
    ISO 8601 duration 문자열을 초 단위 정수로 변환.
    예: 'PT15M33S' → 933
    """
    pattern = r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?"
    match = re.match(pattern, iso_duration)
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def build_youtube_client(api_key: str = None):
    """YouTube API 클라이언트 객체 생성. api_key 미지정 시 기본 키 사용."""
    return googleapiclient.discovery.build(
        "youtube", "v3", developerKey=api_key or YOUTUBE_API_KEY
    )


# ─────────────────────────────────────────────
# STEP 1: 검색어로 채널 ID 수집
# ─────────────────────────────────────────────

def search_channels(youtube, query: str) -> list[str]:
    """
    검색어 하나로 채널 ID 목록을 수집.
    - type=channel : 채널만 반환 (영상/재생목록 제외)
    - regionCode=KR : 한국 지역 기준
    - relevanceLanguage=ko : 한국어 우선
    - maxResults=50 : 페이지당 최대 결과 수
    - order=relevance : 관련성 높은 순 정렬
    MAX_SEARCH_PAGES 페이지까지 반복 수집.
    """
    channel_ids = []
    page_token = None

    for page in range(MAX_SEARCH_PAGES):
        params = {
            "part": "snippet",
            "q": query,
            "type": "channel",
            "regionCode": "KR",
            "relevanceLanguage": "ko",
            "maxResults": MAX_CHANNELS_PER_QUERY,
            "order": "relevance",
        }
        if page_token:
            params["pageToken"] = page_token

        try:
            response = youtube.search().list(**params).execute()
        except HttpError as e:
            _check_quota(e)
            print(f"  [검색 오류] '{query}' page{page+1}: {e.reason}")
            break

        # API 원본 백업 (검색어_page번호.json)
        safe_query = re.sub(r"[^\w가-힣]", "_", query)
        _save_raw("search", f"{safe_query}_page{page + 1}.json", response)

        for item in response.get("items", []):
            cid = item["id"].get("channelId")
            if cid:
                channel_ids.append(cid)

        # 다음 페이지가 없으면 종료
        page_token = response.get("nextPageToken")
        if not page_token:
            break

        time.sleep(REQUEST_DELAY_SECONDS)

    print(f"  [검색] '{query}' → {len(channel_ids)}개 채널 ID 수집")
    return channel_ids


# ─────────────────────────────────────────────
# STEP 2: 채널 ID → 채널 상세 정보
# ─────────────────────────────────────────────

def fetch_channel_details(youtube, channel_ids: list[str], search_query: str) -> list[dict]:
    """
    채널 ID 목록으로 상세 정보를 가져옴.
    channels.list는 한 번에 최대 50개 ID를 처리 가능 → 50개씩 배치 처리.
    part=snippet,statistics,brandingSettings 로 필요한 필드를 한 번에 요청.
    """
    results = []
    # 50개씩 나눠서 배치 요청
    for batch_idx, i in enumerate(range(0, len(channel_ids), 50)):
        batch = channel_ids[i:i + 50]

        response = youtube.channels().list(
            part="snippet,statistics,brandingSettings",
            id=",".join(batch),
            maxResults=50,
        ).execute()

        _save_raw("channels", f"batch_{batch_idx + 1:03d}.json", response)

        for item in response.get("items", []):
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            branding = item.get("brandingSettings", {}).get("channel", {})

            results.append({
                "channel_id": item["id"],
                "title": snippet.get("title", ""),
                "description": snippet.get("description", ""),
                "custom_url": snippet.get("customUrl", ""),
                "country": snippet.get("country", ""),
                "language": branding.get("defaultLanguage", ""),
                "subscriber_count": int(stats.get("subscriberCount", 0)),
                "video_count": int(stats.get("videoCount", 0)),
                "view_count": int(stats.get("viewCount", 0)),
                "published_at": snippet.get("publishedAt", ""),
                "thumbnail_url": snippet.get("thumbnails", {}).get("default", {}).get("url", ""),
                "search_query": search_query,    # 어떤 검색어로 수집됐는지 기록
                "collected_at": _now(),
                "tags": branding.get("keywords", "").split(),  # 공백 구분 키워드
            })

        time.sleep(REQUEST_DELAY_SECONDS)

    return results


# ─────────────────────────────────────────────
# STEP 3: 채널 → 최신 영상 수집
# ─────────────────────────────────────────────

def fetch_videos_for_channel(youtube, channel_id: str, uploads_playlist_id: str) -> list[dict]:
    """
    채널의 업로드 재생목록(uploads playlist)에서 최신 영상을 수집.
    playlistItems.list → video_id 목록 획득 후
    videos.list로 통계/상세 정보를 한 번에 조회.
    """
    # ① 업로드 재생목록에서 video_id 수집
    video_ids = []
    page_token = None

    while len(video_ids) < VIDEOS_PER_CHANNEL:
        try:
            playlist_response = youtube.playlistItems().list(
                part="snippet",
                playlistId=uploads_playlist_id,
                maxResults=min(50, VIDEOS_PER_CHANNEL - len(video_ids)),
                pageToken=page_token,
            ).execute()
        except HttpError as e:
            _check_quota(e)
            # 채널 삭제/비공개 등으로 재생목록을 찾을 수 없는 경우 스킵
            print(f"    [영상 스킵] playlist={uploads_playlist_id} : {e.reason}")
            return []

        for item in playlist_response.get("items", []):
            vid = item["snippet"]["resourceId"].get("videoId")
            if vid:
                video_ids.append(vid)

        page_token = playlist_response.get("nextPageToken")
        if not page_token:
            break
        time.sleep(REQUEST_DELAY_SECONDS)

    if not video_ids:
        return []

    # ② video_id 목록으로 상세 정보 한 번에 조회 (50개씩 배치)
    results = []
    for batch_idx, i in enumerate(range(0, len(video_ids), 50)):
        batch = video_ids[i:i + 50]

        response = youtube.videos().list(
            part="snippet,statistics,contentDetails",
            id=",".join(batch),
        ).execute()

        _save_raw("videos", f"{channel_id}_batch{batch_idx + 1:03d}.json", response)

        for item in response.get("items", []):
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            content = item.get("contentDetails", {})

            results.append({
                "video_id": item["id"],
                "channel_id": channel_id,
                "title": snippet.get("title", ""),
                "description": snippet.get("description", ""),
                "published_at": snippet.get("publishedAt", ""),
                "view_count": int(stats.get("viewCount", 0)),
                "like_count": int(stats.get("likeCount", 0)),
                "comment_count": int(stats.get("commentCount", 0)),
                # ISO 8601 duration을 초 단위로 변환해서 저장 (집계 쿼리 편의)
                "duration_seconds": _parse_duration(content.get("duration", "PT0S")),
                "thumbnail_url": snippet.get("thumbnails", {}).get("default", {}).get("url", ""),
                "collected_at": _now(),
                "tags": snippet.get("tags", []),
                "comments_disabled": 0,
            })

        time.sleep(REQUEST_DELAY_SECONDS)

    return results


def get_uploads_playlist_id(youtube, channel_id: str) -> str | None:
    """
    채널의 업로드 재생목록 ID를 조회.
    채널 ID의 첫 글자 'U'를 'UU'로 바꾸면 uploads playlist ID가 됨.
    (공식 문서 권장 방식: channels.list part=contentDetails)
    """
    response = youtube.channels().list(
        part="contentDetails",
        id=channel_id,
    ).execute()
    items = response.get("items", [])
    if not items:
        return None
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


# ─────────────────────────────────────────────
# STEP 4: 영상 → 댓글 수집
# ─────────────────────────────────────────────

def _comment_row(comment: dict, video_id: str, channel_id: str, parent_id: str | None) -> dict:
    """commentThreads/comments API의 댓글 객체를 DB 저장용 dict로 변환."""
    snip = comment["snippet"]
    return {
        "comment_id": comment["id"],
        "video_id": video_id,
        "channel_id": channel_id,
        "parent_id": parent_id,
        "author": snip.get("authorDisplayName", ""),
        "text": snip.get("textDisplay", ""),
        "like_count": int(snip.get("likeCount", 0)),
        "published_at": snip.get("publishedAt", ""),
        "collected_at": _now(),
    }


def _fetch_all_replies(youtube, parent_comment_id: str, video_id: str, channel_id: str) -> list[dict]:
    """
    최상위 댓글 하나의 모든 대댓글(답글)을 comments.list로 페이지네이션 수집.
    답글이 6개 이상이라 commentThreads inline(최대 5개)으로 부족할 때만 호출.
    """
    replies = []
    page_token = None
    while True:
        response = youtube.comments().list(
            part="snippet",
            parentId=parent_comment_id,
            maxResults=100,
            textFormat="plainText",
            pageToken=page_token,
        ).execute()
        for item in response.get("items", []):
            replies.append(_comment_row(item, video_id, channel_id, parent_comment_id))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
        time.sleep(REQUEST_DELAY_SECONDS)
    return replies


def fetch_comments_for_video(youtube, video_id: str, channel_id: str) -> tuple[list[dict], bool]:
    """
    영상의 전체 댓글(최상위 + 대댓글)을 수집.
    - commentThreads.list를 nextPageToken으로 끝까지 페이지네이션 (상한 없음)
    - order=relevance : 좋아요/참여도 높은 댓글 우선
    - 각 thread의 totalReplyCount > inline 답글 수일 때만 comments.list로 나머지 답글 조회
    댓글 비활성화 영상은 예외 처리 후 건너뜀.
    반환값: (댓글 목록[최상위+답글], 댓글_비활성화_여부)
    """
    results = []
    disabled = False
    page_token = None
    page_idx = 0
    try:
        while True:
            response = youtube.commentThreads().list(
                part="snippet,replies",
                videoId=video_id,
                maxResults=100,         # 페이지당 최대 (API max)
                order="relevance",      # 관련성 높은(좋아요 많은) 댓글 우선
                textFormat="plainText", # HTML 태그 없이 순수 텍스트로 수집
                pageToken=page_token,
            ).execute()

            page_idx += 1
            _save_raw("comments", f"{video_id}_page{page_idx:03d}.json", response)

            for item in response.get("items", []):
                top = item["snippet"]["topLevelComment"]
                top_id = top["id"]
                results.append(_comment_row(top, video_id, channel_id, None))

                reply_count = int(item["snippet"].get("totalReplyCount", 0))
                if reply_count == 0:
                    continue

                inline = item.get("replies", {}).get("comments", [])
                if reply_count <= len(inline):
                    # inline(최대 5개)로 답글 전부 포함됨 → 추가 호출 불필요
                    for r in inline:
                        results.append(_comment_row(r, video_id, channel_id, top_id))
                else:
                    # 답글 6개 이상 → 전체 답글 별도 조회
                    results.extend(
                        _fetch_all_replies(youtube, top_id, video_id, channel_id)
                    )

            page_token = response.get("nextPageToken")
            if not page_token:
                break
            time.sleep(REQUEST_DELAY_SECONDS)

    except HttpError as e:
        _check_quota(e)
        if "disabled" in str(e).lower() or "commentsDisabled" in str(e):
            disabled = True
        print(f"    [댓글 스킵] video_id={video_id} : {e.reason}")
    except Exception as e:
        print(f"    [댓글 스킵] video_id={video_id} : {e}")

    return results, disabled
