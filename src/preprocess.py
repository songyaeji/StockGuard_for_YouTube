"""
DB에서 데이터를 읽어 전처리 후 CSV로 저장.
전처리 로직은 TODO — EDA 후 방향 확정 예정.
"""
import pandas as pd
from pathlib import Path

from src.db import get_conn
from config.settings import BASE_DIR

OUTPUT_PATH = BASE_DIR / "data" / "processed" / "dataset.csv"


def load_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """DB에서 채널, 영상, 댓글 테이블을 DataFrame으로 로드."""
    with get_conn() as conn:
        df_channels = pd.read_sql("SELECT * FROM channels", conn)
        df_videos   = pd.read_sql("SELECT * FROM videos", conn)
        df_comments = pd.read_sql("SELECT * FROM comments", conn)
    print(f"로드 완료 — 채널 {len(df_channels):,} / 영상 {len(df_videos):,} / 댓글 {len(df_comments):,}")
    return df_channels, df_videos, df_comments


def preprocess(
    df_channels: pd.DataFrame,
    df_videos: pd.DataFrame,
    df_comments: pd.DataFrame,
) -> pd.DataFrame:
    """
    전처리 후 ML 학습용 DataFrame 반환.
    TODO: EDA 결과를 반영해 구체적인 전처리 로직 구현
    """
    # TODO: 피처 선택, 결측치 처리, 인코딩, 스케일링, 레이블링 등
    raise NotImplementedError("전처리 로직 미구현 — EDA 후 채울 것")


def save_csv(df: pd.DataFrame):
    """전처리된 DataFrame을 CSV로 저장."""
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"저장 완료 → {OUTPUT_PATH}  ({len(df):,}행)")


def run():
    """전체 전처리 파이프라인 실행."""
    print("=" * 50)
    print("StockGuard 전처리 시작")
    print("=" * 50)

    df_channels, df_videos, df_comments = load_data()
    df = preprocess(df_channels, df_videos, df_comments)
    save_csv(df)

    print("=" * 50)
    print("전처리 완료")
    print("=" * 50)
