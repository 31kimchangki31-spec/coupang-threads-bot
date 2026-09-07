# 쿠팡 골드박스 → 쓰레드 자동 게시 봇

쿠팡파트너스 **골드박스(당일 특가)** Open API로 상품 목록을 받아, 그중 하나를 골라
홍보 카드 이미지 + 캡션으로 만들어 쓰레드(Threads)에 게시합니다.
GitHub Actions로 자동 실행되며 비용은 무료입니다.

## 파이프라인

```
골드박스 API (상품ID + 제휴링크)
      ↓
골드박스 페이지 1회 수집  ← 전체 상품명 / 실제 판매가 / 할인율 / 카드 캡처
      ↓
두 데이터 병합 후 선정  ← picks.txt(수동) 또는 필터+점수(자동)
      ↓
카드 이미지 → 정사각형 JPEG 변환 (Meta 규격)
      ↓
GitHub raw 호스팅 → (실패 시) imgbb
      ↓
캡션 생성  ← Claude API, 실패 시 템플릿
      ↓
쓰레드 게시 → posted.json 기록
```

### 왜 페이지를 읽는가

골드박스 Open API만으로는 정확한 게시글을 만들 수 없습니다.

| 항목 | API | 페이지 |
|---|---|---|
| 상품명 | `펩시 제로슈거 라임향` (잘림) | `펩시 제로슈거 라임향, 210ml, 30개` |
| 가격 | `14,780` (**정가**) | `3,780` (실제 판매가) |
| 할인율 | 없음 | `74%` |
| 정가 | 없음 | `14,780` |

API의 `productPrice`를 판매가로 믿으면 **정가를 특가라고 광고하는 게시글**이 나갑니다.
그래서 페이지를 한 번 열어 24개 카드 전부의 정확한 값을 읽고, 그 데이터로 선정합니다.
페이지 수집이 실패하면 API 값으로 진행하되 로그에 경고를 남깁니다.

## 1. 준비물

- GitHub 계정
- 쿠팡파트너스 Access Key / Secret Key
- Threads User ID / 장기 Access Token (60일)
- Anthropic API 키 (선택) — 없으면 템플릿 캡션 사용
- imgbb API 키 (선택) — GitHub raw 호스팅이 기본이라 없어도 됩니다

## 2. Secrets 등록

저장소 → **Settings → Secrets and variables → Actions → New repository secret**

| Secret 이름 | 필수 | 값 |
|---|---|---|
| `COUPANG_ACCESS_KEY` | ✅ | 쿠팡파트너스 Access Key |
| `COUPANG_SECRET_KEY` | ✅ | 쿠팡파트너스 Secret Key |
| `THREADS_USER_ID` | ✅ | Threads User ID |
| `THREADS_ACCESS_TOKEN` | ✅ | 60일 장기 Access Token |
| `IMGBB_API_KEY` | 선택 | 이미지 호스팅 예비용 (기본은 GitHub raw) |
| `ANTHROPIC_API_KEY` | 선택 | AI 캡션 생성용 |
| `COUPANG_SUB_ID` | 선택 | 채널별 실적 구분용 subId |
| `GH_PAT` | 선택 | 토큰 자동 갱신 워크플로용 (repo + secrets 쓰기 권한) |

## 3. 상품 선정 방식

### 자동 선정 (기본)

`selector_config.json` 으로 조정합니다.

| 항목 | 의미 |
|---|---|
| `min_price` / `max_price` | 가격 범위 (범위 밖은 제외) |
| `rocket_only` | `true`면 로켓배송 상품만 |
| `exclude_keywords` | 이 단어가 들어간 상품 제외 |
| `prefer_keywords` | 이 단어가 들어가면 가점 |
| `prefer_weight` | 가점 크기 (기본 40 = 할인율 40%p 상당) |

점수는 `할인율 + 로켓 5점 + 선호 키워드 가점` 이고, 최고점 상품이 선정됩니다.

### 수동 지정

`picks.txt` 에 상품ID나 상품명 키워드를 한 줄씩 적으면 그것을 먼저 시도합니다.
오늘 골드박스 목록에 없으면 자동 선정으로 넘어갑니다.

```
8241234567
무드등
```

## 4. 테스트 실행

게시하지 않고 결과만 확인하려면 **Actions → Coupang -> Threads 자동 게시 → Run workflow**
에서 `dry_run` 을 체크하세요. 로컬에서는:

```bash
pip install -r requirements.txt
python -m playwright install chromium

export COUPANG_ACCESS_KEY=...
export COUPANG_SECRET_KEY=...
export DRY_RUN=1
python main.py
```

선정된 상품, 딥링크, 생성된 캡션이 콘솔에 출력되고 카드 이미지는
`composed_card.png` 로 저장됩니다.

## 5. 게시 주기

`.github/workflows/auto-post.yml` 의 `cron` 을 수정합니다.
기본값은 KST 09시 / 13시 / 20시 (`"5 0,4,11 * * *"`, UTC 기준)입니다.

`posted.json` 은 **당일** 게시 기록만 유지합니다. 골드박스는 매일 갱신되므로
날짜가 바뀌면 자동으로 초기화됩니다.

## 6. 주의사항

- **경제적 이해관계 표시 문구는 본문 첫 줄에 자동으로 붙습니다**
  (`caption_generator.py` 의 `DISCLOSURE`). 2024-12-01 시행 개정 심사지침이
  표시 문구를 게시물 끝부분에 두는 방식을 더 이상 적절하다고 보지 않아,
  첫 줄로 올리고 문장을 짧게 줄였습니다.
- 주제 태그(`POST_TOPIC_TAG`, 기본 `광고`)는 **표시 문구의 대체물이 아닙니다.**
  Threads의 `topic_tag` 는 사용자가 직접 입력하는 '주제'일 뿐이고, Meta가 검증해서
  붙이는 유료광고 표시가 아닙니다. 해시태그와 같은 성격이라 규제상 의미가 없습니다.
  또한 쿠팡 파트너스 약관 자체가 고지 문구를 요구하므로, 문구를 빼면 법적 위험과는
  별개로 파트너스 자격 정지 사유가 됩니다.
- 고정 CTA는 기본값이 빈 문자열이라 출력되지 않습니다. 쓰려면 `CTA` 에 값을 넣으세요.
- 카드 이미지는 골드박스 페이지에서 **해당 상품 카드 하나만** 잘라 캡처합니다.
  캡처에 실패하면 `product_card_renderer.py` 가 상품 이미지로 카드를 직접 그립니다.
- **쿠폰 조건부 가격 주의**: 골드박스 가격 중 상당수는 쿠폰 적용가입니다. 스크린샷의
  펩시는 3,780원이 "쿠폰할인" 가격이고, 820원은 "WOW 가입 쿠폰가"로 신규 가입자 한정입니다.
  이런 가격을 조건 없이 광고하면 표시광고 문제가 될 수 있어, 파서가 조건부 가격을 감지하면
  캡션에 "쿠폰 적용 시 가격" 문구를 자동으로 붙입니다. `WOW/가입 쿠폰가` 는 판매가로
  아예 쓰지 않습니다.
- Threads 장기 토큰은 60일마다 만료됩니다. `refresh-token.yml` 을 등록해두면 매월 자동 갱신됩니다.
- 채팅으로 주고받은 API 키는 노출된 것으로 간주하고 쿠팡Wing에서 재발급받는 것을 권장합니다.

## 7. 문제가 생기면

Actions 로그에 단계별 태그가 찍힙니다. 태그로 원인을 좁히세요.

| 로그 태그 | 의미 | 확인할 것 |
|---|---|---|
| `[오류] 골드박스 조회 실패` | API 인증/경로 문제 | Access/Secret Key, 파트너스 API 사용 권한 |
| `[선정] 필터 통과 0개` | 필터가 너무 좁음 | `selector_config.json` 가격 범위 |
| `[캡션] {모델} 실패` | Claude API 문제 | `ANTHROPIC_API_KEY`, 크레딧 잔액 |
| `[캡션] AI 실패, 템플릿으로 대체` | 폴백 작동 (게시는 정상) | 위 항목과 동일 |
| `[페이지] 상품 링크 0개 발견` | 쿠팡이 접근 차단 | 아래 "페이지 수집이 안 될 때" 참고 |
| `경고: 페이지 데이터 없음` | API 값으로 게시됨 | 가격이 정가일 수 있으니 확인 |
| `[이미지] git push 실패` | GitHub 호스팅 실패 | 워크플로 `contents: write` 권한 |
| `[Threads 컨테이너 생성 실패]` | 게시 실패 | 아래 "이미지가 안 올라갈 때" 참고 |

### 페이지 수집이 안 될 때

로그에 `[페이지] 상품 링크 0개 발견` 이 찍히고 진단 정보가 따라 나옵니다.
쿠팡은 데이터센터 IP를 차단하는 경우가 많아, GitHub의 공용 러너에서는
골드박스 페이지 접근이 막힐 수 있습니다. 선택지는 셋입니다.

1. **self-hosted 러너** (권장) — 집 PC나 상시 켜둘 수 있는 기기를 러너로 등록하면
   가정용 IP로 접근하므로 차단되지 않습니다. `auto-post.yml` 의 `runs-on` 을
   `self-hosted` 로 바꾸고, 저장소 Settings → Actions → Runners 에서 러너를 추가하세요.
   이 경우 `python -m playwright install --with-deps chromium` 을 러너에 한 번
   실행해두어야 합니다.
2. **프록시** — 한국 가정용 IP 프록시를 `BROWSER_PROXY` 시크릿에 넣으면
   (`http://user:pass@host:port` 형식) 공용 러너에서도 접근할 수 있습니다. 유료입니다.
3. **API 값으로 게시** — 페이지 없이 진행합니다. 다만 가격이 정가로 표시되고
   상품명이 잘리므로 권장하지 않습니다. `REQUIRE_PAGE_DATA=1` 로 두면 이런 경우
   게시를 건너뛰어 잘못된 가격이 올라가는 것을 막습니다.

`debug_goldbox.png` 가 Actions 아티팩트로 올라가니, 쿠팡이 어떤 화면을 돌려줬는지
직접 확인할 수 있습니다.

### 이미지가 안 올라갈 때

`error_subcode: 2207052` (Media download has failed)는 Meta가 이미지를 **가져가지
못했다**는 뜻입니다. 세 가지 원인이 있습니다.

1. **호스팅 접근 불가** — Meta는 자체 크롤러로 내려받습니다. 브라우저에서 열리는 것만으로는
   부족하고, imgbb처럼 크롤러가 막히는 호스팅은 실패합니다. 그래서 기본값을 GitHub raw로
   두었습니다.
2. **가로세로 비율 초과** — 허용 범위는 4:5 ~ 1.91:1 입니다. 쿠팡 카드를 잘라내면 대체로
   2:1이 넘어서 그대로 올리면 거부됩니다. `image_prep.py` 가 흰 여백을 넣어 1:1로 맞춥니다.
3. **형식** — PNG는 거부되는 사례가 잦아 JPEG로 변환합니다.

이미지 게시가 실패하면 텍스트 전용으로 자동 재시도하므로, 게시 자체가 실패해 워크플로가
죽는 일은 없습니다.

캡션 모델은 `claude-opus-5` → `claude-sonnet-5` → 템플릿 순으로 폴백합니다.
`CAPTION_MODEL` 환경변수로 첫 모델을 바꿀 수 있습니다.

## 8. 환경변수 / Variables

Secrets 외에 저장소 **Settings → Secrets and variables → Actions → Variables** 에서
아래 값을 조정할 수 있습니다.

| 이름 | 기본값 | 의미 |
|---|---|---|
| `POST_TOPIC_TAG` | `광고` | 게시물 주제 태그. 빈 값이면 태그 없음 |
| `REQUIRE_PAGE_DATA` | `0` | `1` 이면 페이지 수집 실패 시 게시하지 않음 |
| `BROWSER_PROXY` (Secret) | 없음 | 페이지 수집용 프록시 주소 |
