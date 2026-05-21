"""
SQLite DB 초기화 및 CRUD 함수 모음.
모든 데이터는 이 파일을 통해서만 DB에 접근합니다.
"""
import sqlite3
from config.settings import DB_PATH


def get_conn() -> sqlite3.Connection:
    """DB 연결 객체를 반환. data/ 폴더가 없으면 자동 생성."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row   # 결과를 딕셔너리처럼 접근 가능하게
    conn.execute("PRAGMA foreign_keys = ON")  # 외래키 제약 활성화
    return conn


def init_db():
    """5개 테이블을 생성합니다 (이미 있으면 건너뜀)."""
    conn = get_conn()
    with conn:
        conn.executescript("""
            -- ① 채널 기본 정보
            CREATE TABLE IF NOT EXISTS channels (
                channel_id       TEXT PRIMARY KEY,
                title            TEXT NOT NULL,
                description      TEXT,
                custom_url       TEXT,          -- @핸들 형태의 커스텀 URL
                country          TEXT,
                language         TEXT,
                subscriber_count INTEGER,
                video_count      INTEGER,
                view_count       INTEGER,
                published_at     TEXT,          -- 채널 개설일 (ISO 8601)
                thumbnail_url    TEXT,
                search_query     TEXT,          -- 어떤 검색어로 수집되었는지 추적용
                collected_at     TEXT NOT NULL  -- 수집 시각 (반복 수집 시 변화 추적)
            );

            -- ② 채널 태그 (1채널 : N태그 분리)
            CREATE TABLE IF NOT EXISTS channel_tags (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT NOT NULL REFERENCES channels(channel_id),
                tag        TEXT NOT NULL
            );
            -- 특정 태그를 가진 채널을 빠르게 조회하기 위한 인덱스
            CREATE INDEX IF NOT EXISTS idx_channel_tags_tag
                ON channel_tags(tag);

            -- ③ 영상 기본 정보
            CREATE TABLE IF NOT EXISTS videos (
                video_id         TEXT PRIMARY KEY,
                channel_id       TEXT NOT NULL REFERENCES channels(channel_id),
                title            TEXT NOT NULL,
                description      TEXT,
                published_at     TEXT,
                view_count       INTEGER,
                like_count       INTEGER,
                comment_count    INTEGER,
                duration_seconds INTEGER,  -- API 원본(PT15M33S)을 초 단위로 변환해 저장
                thumbnail_url    TEXT,
                collected_at     TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_videos_channel
                ON videos(channel_id);

            -- ④ 영상 태그 (1영상 : N태그 분리)
            CREATE TABLE IF NOT EXISTS video_tags (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                video_id TEXT NOT NULL REFERENCES videos(video_id),
                tag      TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_video_tags_tag
                ON video_tags(tag);

            -- ⑤ 댓글 (채널당 상위 3개 영상 × 20개)
            CREATE TABLE IF NOT EXISTS comments (
                comment_id   TEXT PRIMARY KEY,
                video_id     TEXT NOT NULL REFERENCES videos(video_id),
                channel_id   TEXT NOT NULL REFERENCES channels(channel_id),
                author       TEXT,
                text         TEXT,
                like_count   INTEGER,
                published_at TEXT,
                collected_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_comments_video
                ON comments(video_id);
            CREATE INDEX IF NOT EXISTS idx_comments_channel
                ON comments(channel_id);
        """)
    conn.close()
    print(f"[DB] 초기화 완료: {DB_PATH}")


def get_searched_queries() -> set[str]:
    """이미 검색이 완료된 검색어 목록 반환 (재실행 시 중복 검색 방지)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT search_query FROM channels WHERE search_query IS NOT NULL"
        ).fetchall()
    return {r["search_query"] for r in rows}


def channel_exists(channel_id: str) -> bool:
    """이미 수집된 채널인지 확인 (중복 수집 방지)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM channels WHERE channel_id = ?", (channel_id,)
        ).fetchone()
    return row is not None


def insert_channel(data: dict):
    """채널 정보와 태그를 DB에 저장. 이미 있으면 덮어씀(REPLACE)."""
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO channels
                (channel_id, title, description, custom_url, country, language,
                 subscriber_count, video_count, view_count, published_at,
                 thumbnail_url, search_query, collected_at)
            VALUES
                (:channel_id, :title, :description, :custom_url, :country, :language,
                 :subscriber_count, :video_count, :view_count, :published_at,
                 :thumbnail_url, :search_query, :collected_at)
        """, data)
        # 태그는 별도 테이블에 저장 (기존 태그 삭제 후 재삽입)
        if data.get("tags"):
            conn.execute(
                "DELETE FROM channel_tags WHERE channel_id = ?", (data["channel_id"],)
            )
            conn.executemany(
                "INSERT INTO channel_tags (channel_id, tag) VALUES (?, ?)",
                [(data["channel_id"], t) for t in data["tags"]],
            )


def insert_video(data: dict):
    """영상 정보와 태그를 DB에 저장. 이미 있으면 덮어씀."""
    with get_conn() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO videos
                (video_id, channel_id, title, description, published_at,
                 view_count, like_count, comment_count, duration_seconds,
                 thumbnail_url, collected_at)
            VALUES
                (:video_id, :channel_id, :title, :description, :published_at,
                 :view_count, :like_count, :comment_count, :duration_seconds,
                 :thumbnail_url, :collected_at)
        """, data)
        if data.get("tags"):
            conn.execute(
                "DELETE FROM video_tags WHERE video_id = ?", (data["video_id"],)
            )
            conn.executemany(
                "INSERT INTO video_tags (video_id, tag) VALUES (?, ?)",
                [(data["video_id"], t) for t in data["tags"]],
            )


def insert_comment(data: dict):
    """댓글을 DB에 저장. 이미 있으면 건너뜀(IGNORE)."""
    with get_conn() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO comments
                (comment_id, video_id, channel_id, author, text,
                 like_count, published_at, collected_at)
            VALUES
                (:comment_id, :video_id, :channel_id, :author, :text,
                 :like_count, :published_at, :collected_at)
        """, data)


def has_videos(channel_id: str) -> bool:
    """이미 영상이 수집된 채널인지 확인 (재실행 시 중복 수집 방지)."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM videos WHERE channel_id = ? LIMIT 1", (channel_id,)
        ).fetchone()
    return row is not None


def get_channel_ids() -> list[str]:
    """저장된 모든 채널 ID 목록 반환."""
    with get_conn() as conn:
        rows = conn.execute("SELECT channel_id FROM channels").fetchall()
    return [r["channel_id"] for r in rows]


def get_video_ids_for_channel(channel_id: str, limit: int) -> list[str]:
    """특정 채널의 영상 ID를 조회수 높은 순으로 반환 (댓글 수집 대상 선정용)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT video_id FROM videos WHERE channel_id = ? "
            "ORDER BY view_count DESC LIMIT ?",
            (channel_id, limit),
        ).fetchall()
    return [r["video_id"] for r in rows]
