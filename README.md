# StockGuard for YouTube

불법 주식 리딩방 의심 유튜브 채널을 데이터로 가려내는 분석 프로젝트. 경희대 응용데이터분석 텀프로젝트.

규제 키워드만 보고 막는 게 아니라, 규제 키워드 없이도 채널 운영 패턴(구독↔조회 비율, 채널 나이, 참여율, 외부 연락처 노출 등)만으로 의심 채널을 가려낸다. 데이터 수집부터 EDA, 가설검정·모델링까지 한 흐름으로 묶고, 최종 산출물로 **차단 리스트·의심 리스트** 두 CSV를 낸다.

## 전체 흐름

```
YouTube API 수집        EDA · 전처리           가설검정 · 모델링            산출물
crawl.py            preprocessing.ipynb    modeling.ipynb            data/processed/
   │                       │                      │                       │
youtube_channels.db → data/processed/*.csv → H1/H2/H3 + RF 점수 → 차단리스트.csv · 의심리스트.csv
```

검색어 30개로 채널을 수집(주식 리딩방 타겟 + 정상 경제채널 + 교차)하고, 정제·EDA 후 H1/H2/H3 가설을 검정한다. 거기서 나온 RandomForest 의심 점수와 금융위·금감원 규제어를 결합해 두 리스트로 내보낸다.

## 산출물 — 차단 리스트 / 의심 리스트

`modeling.ipynb` 6장이 `data/processed/`에 두 CSV를 출력한다.

| 리스트 | 조건 | 용도 |
|---|---|---|
| `차단리스트.csv` | 규제어 hit **그리고** 모델 점수 ≥ 차단 운영점(precision≥0.9) | "확실한 것만 막는다". 모델 점수 단독 차단 금지(H1 기각) — 규제어라는 법적 근거 동반 시에만 |
| `의심리스트.csv` | 모델 점수 ≥ 의심 운영점(precision≥0.7) | 규제어 없어도 포함(회피형 후보). 차단이 아니라 수동 검토·신고 우선순위 큐 |

각 행에 `channel_id·title·rf_score·규제어종수·규제어총매칭·매칭규제어·q_group`를 담아, 왜 의심하는지(어떤 규제어가 걸렸는지)를 같이 출력한다. 차단·의심은 분석 기반 **의심 정보**일 뿐 법적 판단이 아니며, 최종 판단·제재는 금융당국(금감원 [fine.fss.or.kr](https://fine.fss.or.kr)) 몫이다.

> 금감원 '사이버불법금융행위제보' 제출용으로 수동 검증까지 거친 리스트는 `report/` 참고.

## 디렉토리

| 경로 | 역할 |
|---|---|
| `crawl.py` | 수집 진입점. `python crawl.py` 한 번으로 전체 파이프라인 |
| `src/` | 수집 모듈 — `collector.py`(YouTube API), `db.py`(SQLite I/O), `pipeline.py`(검색→채널→영상→댓글 순서·쿼터 처리) |
| `config/settings.py` | 검색어 30개, API 키 목록, 수집 파라미터 |
| `label_shorts.py` | 영상별 Shorts 여부 판별(`/shorts/` redirect) → 원본 DB `is_shorts` 컬럼 기록 |
| `notebooks/preprocessing.ipynb` | 정제·무결성 검증·EDA·이상치 처리 |
| `notebooks/modeling.ipynb` | H1 분류 / H2 PCA+군집 / H3 통계검정 → 차단·의심 리스트 출력 |
| `report/` | 금감원 제보용 수동 검증 리스트 |
| `data/` | 원본 DB·가공 CSV (git 제외) |

## 실행

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt

# 1. 데이터 수집 (.env에 YOUTUBE_API_KEY 필요, 쿼터 초과 시 이어받기)
.venv/bin/python crawl.py

# 2. 노트북 (정제 → 모델링 → 차단·의심 리스트 출력)
.venv/bin/jupyter notebook notebooks/
```

`modeling.ipynb`를 끝까지 실행하면 `data/processed/차단리스트.csv`·`의심리스트.csv`가 생성된다.

## 데이터 규모

채널 2,508 · 영상 34,162 · 댓글 423,522. 무결성 검증 완료(중복·orphan·NULL 0). 원본 DB는 읽기 전용, 가공 결과만 `data/processed/`에 따로 저장.

## 분석 원칙

- **라벨 leakage 차단**: 수집 검색어는 약한 라벨 prior일 뿐, 분류기 feature로 쓰지 않음. 규제어도 라벨 근거지 feature 아님.
- **삭제 vs 플래그 구분**: 분포에서 튀어도 가능한 값(리딩방 후보 = contextual outlier)은 삭제하지 않고 플래그. 물리적으로 불가능하거나 무관한 표본(anomaly)만 제거.
- **나이 보정**: 조회·좋아요·댓글 수는 `video_age_days`로 정규화.
- **선택편향 명시**: 모집단은 "30개 주식 검색어로 잡힌 채널"이지 경제 유튜브 전체가 아님.

## 고지

차단·의심 리스트는 데이터 분석 기반 의심 정보일 뿐 법적 판단이 아니다. 최종 판단·제재는 금융당국(금감원 [fine.fss.or.kr](https://fine.fss.or.kr)) 몫.
