# StockGuard for YouTube

불법 주식 리딩방 의심 유튜브 채널을 탐지·차단하는 크롬 익스텐션. 경희대 응용데이터분석 텀프로젝트.

규제 키워드만 보고 막는 게 아니라, 채널의 행동·구조 패턴(구독↔조회 비율, 채널 나이, 연락처 노출 등)으로 의심 채널을 가려낸다. 데이터 수집부터 EDA, 모델링, 익스텐션까지 한 흐름으로 묶었다.

## 전체 흐름

```
YouTube API 수집        EDA · 전처리           가설검정 · 모델링         크롬 익스텐션
crawl.py            preprocessing.ipynb    modeling.ipynb         extension/
   │                       │                      │                    │
youtube_channels.db → data/processed/*.csv → 경량 모델·운영점 → model_data.js 탑재
```

검색어 30개로 채널을 수집(주식 리딩방 타겟 + 정상 경제채널 + 교차)하고, 정제·EDA 후 H1/H2/H3 가설을 검정한다. 거기서 나온 경량 모델을 익스텐션에 넣어 실제 유튜브 페이지에서 채널을 평가한다.

## 디렉토리

| 경로 | 역할 |
|---|---|
| `crawl.py` | 수집 진입점. `python crawl.py` 한 번으로 전체 파이프라인 |
| `src/` | 수집 모듈 — `collector.py`(YouTube API), `db.py`(SQLite I/O), `pipeline.py`(검색→채널→영상→댓글 순서·쿼터 처리) |
| `config/settings.py` | 검색어 30개, API 키 목록, 수집 파라미터 |
| `label_shorts.py` | 영상별 Shorts 여부 판별(`/shorts/` redirect) → 원본 DB `is_shorts` 컬럼 기록 |
| `notebooks/preprocessing.ipynb` | 정제·무결성 검증·EDA·이상치 처리 |
| `notebooks/modeling.ipynb` | H1 분류 / H2 PCA+군집 / H3 통계검정 |
| `extension/` | 크롬 익스텐션(MV3). 설계·구현은 [`extension/README.md`](extension/README.md) |
| `data/` | 원본 DB·가공 CSV (git 제외) |

## 실행

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt

# 1. 데이터 수집 (.env에 YOUTUBE_API_KEY 필요, 쿼터 초과 시 이어받기)
.venv/bin/python crawl.py

# 2. 노트북 (정제 → 모델링)
.venv/bin/jupyter notebook notebooks/

# 3. 익스텐션 — chrome://extensions → 개발자 모드 → extension/ 로드
```

## 데이터 규모

채널 2,508 · 영상 34,162 · 댓글 423,522. 무결성 검증 완료(중복·orphan·NULL 0). 원본 DB는 읽기 전용, 가공 결과만 `data/processed/`에 따로 저장.

## 분석 원칙

- **라벨 leakage 차단**: 수집 검색어는 약한 라벨 prior일 뿐, 분류기 feature로 쓰지 않음. 규제어도 라벨 근거지 feature 아님.
- **삭제 vs 플래그 구분**: 분포에서 튀어도 가능한 값(리딩방 후보 = contextual outlier)은 삭제하지 않고 플래그. 물리적으로 불가능하거나 무관한 표본(anomaly)만 제거.
- **나이 보정**: 조회·좋아요·댓글 수는 `video_age_days`로 정규화.
- **선택편향 명시**: 모집단은 "30개 주식 검색어로 잡힌 채널"이지 경제 유튜브 전체가 아님.

## 고지

차단·경고는 데이터 분석 기반 의심 정보일 뿐 법적 판단이 아니다. 최종 판단·제재는 금융당국(금감원 [fine.fss.or.kr](https://fine.fss.or.kr)) 몫.
