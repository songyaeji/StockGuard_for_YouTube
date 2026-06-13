# 익스텐션 follow-up (보류된 아키텍처급 작업)

다중 리뷰(보안·플랫폼·성능·모델·감사)에서 나온 항목 중, 동작 로드테스트가 필요하거나 구조변경을 동반해 별도 PR로 분리한 4건. 우선순위 순.

## 1. 로케일 의존 스크래핑 → `ytInitialData` 숫자필드 파싱 (정확도, 높음)
`content.js`의 메타 추출이 한국어 표시문자열(`구독자`/`동영상`/`조회수`/`가입`) regex에 묶여 있음. 영어 등 비-KR UI에서는 전부 미스 → 모든 feature가 median 대치되어 빈 프로필로 점수가 남(오탐/미탐).
- 할 일: 표시문자열 대신 `ytInitialData`의 `subscriberCountText`/숫자 `subscriberCount`, `videosCountText`, `viewCountText` 등 로케일 독립 필드 파싱. 키 순서 비의존(title/description 독립 매칭).
- 영향 파일: `content.js` (parseChannelHtml, parseVideosHtml)

## 2. 340KB 모델 전 페이지 주입 → SW 이전 or lazy-import (성능, 높음)
`model_data.js`(332KB)가 `content_scripts`라 채널 아닌 home/search/watch/shorts 포함 **모든** youtube 페이지에서 파싱·heap 상주.
- 옵션 A: 모델 + `sgScore`를 background service worker로 옮기고 content는 feature만 `chrome.runtime.sendMessage`로 전달, 점수 회신. 파싱 SW 1회.
- 옵션 B: `model_data.js`/`model.js`를 content_scripts에서 빼고 `web_accessible_resources`로, Stage-0 게이트 통과 후에만 `import(chrome.runtime.getURL(...))` 동적로드. ESM export 필요.
- 영향: `manifest.json`, `content.js`, `model.js`, `model_data.js`(export 형태)

## 3. Shorts 소유자 해석 + DOM 셀렉터 재시도 (커버리지, 중)
`/shorts/VIDEOID`는 chPath 해석 안 됨(watch 아님) → 평가 누락. watch 소유자 셀렉터(`ytd-video-owner-renderer`)는 데스크톱·하이드레이션 전 단발 query라 미스 시 그 내비 동안 영구 null.
- 할 일: `/shorts/` 분기 추가(소유자 DOM 해석), 소유자 anchor 짧은 폴링/재시도.
- 영향: `content.js` (channelPathFromWatch, run)

## 4. whitelist `@handle` vs `UCID` 정규화 (정확도, 중)
whitelist/cache 키가 chPath(`/@handle` 또는 `/channel/UC...`)라, 같은 채널을 다른 경로형태로 접근하면 화이트리스트가 안 맞음.
- 할 일: 채널 HTML의 `externalId`(UC...) 파싱해 정규 채널ID로 key 통일. 팝업 표시도 핸들 보존하되 매칭은 ID로.
- 영향: `content.js`, `popup.js`(표시)

---
생성 근거: 5개 전문 리뷰 서브에이전트 합의. 적용된 수정 10건은 이 커밋에 포함, 위 4건은 구조변경·로드테스트 필요로 분리.
