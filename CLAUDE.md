# StockGuard for YouTube

불법 주식 리딩방 의심 유튜브 채널 탐지 데이터 분석 프로젝트 (익스텐션 폐기 → 차단·의심 리스트 CSV 산출).
경희대 응용데이터분석(응데분) TermProject1. 수집·EDA·모델링 완료 → modeling.ipynb 6장이 차단리스트/의심리스트 출력.

## 환경
- Python 가상환경: **`.venv/bin/python`** (시스템 python 금지)
- 패키지 설치: `.venv/bin/pip install -q <pkg>`
- 플랫폼: WSL2 (Linux). Windows 파일 = `/mnt/c/...` 접근
- 노트북 실행검증: `.venv/bin/jupyter nbconvert --to notebook --execute --inplace <nb> --ExecutePreprocessor.timeout=300`

## 데이터 (절대 규칙)
- **원본 `data/youtube_channels.db` 보존.** 가공결과 = `data/processed/` 별도파일만. 원본 수정/삭제 금지.
- 파생 라벨 `is_shorts`(0/1, `label_shorts.py`가 `/shorts/` redirect로 판별)는 수집 시점에 `youtube_channels.db` videos 테이블에 컬럼으로 이미 기록됨. 노트북은 원본 db를 그대로 읽어 `is_shorts` 사용(별도 labeled 복사본 없음). 원본 구조·행은 보존(읽기 전용 사용).
- `data/` = gitignore. 커밋 금지.
- 규모: 채널 2,508 / 영상 34,162 / 댓글 423,522. 무결성 검증 완료(중복·orphan·NULL 0).
- 가공산출: `data/processed/{channels_clean, videos_clean, comments_clean, channel_features}.csv`

## 코드 규약
- 주석·markdown = **한국어, 본인 말투**(TermProject 요건). 자동생성 티 나는 영어 주석 금지.
- 노트북 **에러 없이 실행** 필수(채점 요건). 큰 변경 후 nbconvert 실행검증.
- 분모 0 가드 필수(like_rate, comment_rate, QCD 등 비율계산).
- matplotlib boxplot = `tick_labels=`(3.9+ deprecation).

## 분석 방법론 (확정 원칙 — 위반 금지)
- **라벨 leakage 금지**: `query_group`, `search_query` = 수집키워드 = 약한 라벨 prior. **분류기 입력 feature 쓰면 순환(leakage)**. 학습 X 제외, 평가·prior만.
- **타깃 신호 = contextual outlier (anomaly 아님)**: 강의 정의 — outlier = 분포(global)/맥락(contextual)에서 튀지만 가능한 값, anomaly = outlier 아닌 비정상값(물리불가·무관표본). 리딩방 후보(구독↔조회 규칙선 이탈) = **contextual outlier** → 삭제 X, 플래그(Retention, 4-2). 정상분포 가정 극단치 제거 = 타깃 삭제 금지. anomaly(유령·비주식·like_rate>1)만 강의대로 Deletion/Imputation(4-3).
- **regex ≠ ML**: 금융위 규제키워드 = 라벨 근거지 feature 아님. feature=label이면 regex 재학습. 규제어 = 임베딩(의미), URL/연락처 = 형식정규식.
- **나이보정**: raw view/like/comment = `video_age_days = collected_at − published_at` 정규화(파생 시간 attribute).
- **선택편향 명시**: 모집단 = "30개 주식키워드 검색 채널", 경제유튜브 전체 아님. 결론에 일반화 한계 caveat.

## 가설 (3개 × 3방법, 사전 판정기준)
- H1 지도학습 분류: "리딩방 = 규제키워드 없이도 행동·구조 패턴 판별가능". 판정=holdout recall/F1.
- H2 비지도 PCA+군집: "작전성 채널 별도 군집 분리". 판정=시드라벨 일치도(ARI/purity).
- H3 통계검정 t-test/ANOVA: "의심군 참여율/시황민감도 ≠ 정상군". 유의수준 0.05 + 효과크기.
- **가설 먼저, 모델 나중**. 기각도 정당한 결과("정확도 아닌 insight").

## Git
- 커밋·푸시 = 명시 요청 시만. main이면 브랜치 먼저.
- API 키(.env), GitHub PAT 커밋 금지.

## 참고자료 (근거 인용용)
- 검색어 30개 설계근거 + KCMI/금융위/금감원 출처: memory `search-query-design`
- 모델링 상세설계: memory `modeling-design`