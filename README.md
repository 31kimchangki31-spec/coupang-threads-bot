# 쿠팡 골드박스 → 쓰레드 자동 게시 봇

쿠팡파트너스 **골드박스(당일 특가)** Open API로 상품 목록을 받아, 그중 하나를 골라
홍보 카드 이미지 + 캡션으로 만들어 쓰레드(Threads)에 게시합니다.
GitHub Actions로 자동 실행되며 비용은 무료입니다.

## 파이프라인

```
골드박스 API (상품 목록)
      ↓
상품 선정  ← picks.txt(수동 지정) 또는 필터+점수(자동)
      ↓
딥링크 발급 (파트너스 추적 링크)
      ↓
할인율/정가 보강  ← 선택 단계, 실패해도 계속 진행
      ↓
카드 이미지 렌더링 → imgbb 업로드
      ↓
캡션 생성  ← Claude API, 실패 시 템플릿으로 폴백
      ↓
쓰레드 게시 → posted.json 기록
```

## 1. 준비물

- GitHub 계정
- 쿠팡파트너스 Access Key / Secret Key
- Threads User ID / 장기 Access Token (60일)
- imgbb API 키 (무료, https://api.imgbb.com) — 없으면 원본 상품 이미지로 게시
- Anthropic API 키 (선택) — 없으면 템플릿 캡션 사용

## 2. Secrets 등록

저장소 → **Settings → Secrets and variables → Actions → New repository secret**

| Secret 이름 | 필수 | 값 |
|---|---|---|
| `COUPANG_ACCESS_KEY` | ✅ | 쿠팡파트너스 Access Key |
| `COUPANG_SECRET_KEY` | ✅ | 쿠팡파트너스 Secret Key |
| `THREADS_USER_ID` | ✅ | Threads User ID |
| `THREADS_ACCESS_TOKEN` | ✅ | 60일 장기 Access Token |
| `IMGBB_API_KEY` | 권장 | 카드 이미지 호스팅용 |
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

- **공시 문구와 CTA는 코드에서 강제로 붙습니다** (`caption_generator.py`의 `DISCLOSURE`, `CTA`).
  AI가 무엇을 생성하든 이 두 줄은 항상 포함됩니다. 삭제하지 마세요.
- 카드 이미지는 쿠팡 화면을 캡처하지 않고, 파트너스 API가 제공하는 공식 상품 이미지에
  직접 레이아웃을 그려서 만듭니다. 할인율 보강 단계만 페이지에서 숫자를 읽어오며,
  실패해도 배지 없이 정상 게시됩니다.
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
| `[이미지] 카드 생성/업로드 실패` | playwright/imgbb 문제 | `IMGBB_API_KEY`, chromium 설치 |
| `[Threads 컨테이너 생성 실패]` | 게시 실패 | 토큰 만료 여부, 이미지 URL 공개 접근 가능 여부 |

캡션 모델은 `claude-opus-5` → `claude-sonnet-5` → 템플릿 순으로 폴백합니다.
`CAPTION_MODEL` 환경변수로 첫 모델을 바꿀 수 있습니다.
