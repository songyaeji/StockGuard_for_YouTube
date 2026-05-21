import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent.parent

DB_PATH = BASE_DIR / "data" / "youtube_channels.db"
RAW_DIR = BASE_DIR / "data" / "raw_responses"

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")

SEARCH_QUERIES = [
    # A. 불법 리딩방 채널 타겟
    "주식리딩방", "주식종목추천", "급등주", "수익률보장",
    "오늘의추천주", "무료리딩", "단타매매", "주식자동매매",
    "주식투자방법", "테마주", "주식대박", "VIP종목",

    # B. 정상 경제·주식 채널 타겟
    "주식투자", "주식시장", "경제전망", "기업분석",
    "코스피", "코스닥", "주식시황", "재테크",
    "주식공부", "애널리스트", "ETF투자", "미국주식",

    # C. 교차 수집 (양쪽 포괄)
    "주식유튜브", "주식방송", "증권사리포트",
    "개인투자자", "주식초보", "주식차트",
]

MAX_CHANNELS_PER_QUERY = 50   # search.list maxResults (API max: 50)
MAX_SEARCH_PAGES = 2          # pages per query → up to 100 channels/query
VIDEOS_PER_CHANNEL = 20       # recent videos per channel
COMMENT_TARGET_VIDEOS = 3     # videos per channel to collect comments on
COMMENTS_PER_VIDEO = 20       # top-level comments per video

REQUEST_DELAY_SECONDS = 0.5   # polite delay between API calls
