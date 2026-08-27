# 쿠팡 골드박스 → Threads 자동 게시

실제 골드박스 상품목록 화면을 Playwright로 읽어 상품을 하나 고른 뒤,
상품 정보를 1번 예시와 같은 홍보 카드 이미지로 다시 만들고 Threads에
이미지 게시물로 올리는 봇입니다.

## 동작 흐름

```text
골드박스 상품목록 화면
  → 상품 카드 추출
  → 상품 이미지/상품명/가격/할인율/남은 시간 추출
  → 홍보 카드 이미지 생성
  → IMGBB 업로드
  → 쿠팡파트너스 딥링크 생성
  → Threads 컨테이너 생성 및 완료 상태 확인
  → Threads 발행
  → posted.json 기록 및 커밋
```

상품 선택은 API 목록이 아니라 실제 화면을 기준으로 합니다. 쿠팡파트너스 API는
선택된 상품 URL을 딥링크로 변환할 때만 사용합니다.

## 필요한 GitHub Secrets

저장소의 `Settings → Secrets and variables → Actions`에 등록합니다.

| 이름 | 설명 |
|---|---|
| `COUPANG_ACCESS_KEY` | 쿠팡파트너스 Access Key |
| `COUPANG_SECRET_KEY` | 쿠팡파트너스 Secret Key |
| `THREADS_USER_ID` | Threads 사용자 ID |
| `THREADS_ACCESS_TOKEN` | Threads 장기 Access Token |
| `IMGBB_API_KEY` | IMGBB 업로드 API 키 |
| `BROWSER_PROXY` | 선택사항. Playwright 브라우저용 프록시 URL |

상품목록 페이지의 실제 URL을 별도로 사용하는 경우 Repository Variables에
`GOLDBOX_URL`을 추가할 수 있습니다. 없으면 기본값
`https://www.coupang.com/np/goldbox`를 사용합니다.

`BROWSER_PROXY`는 예를 들어 다음 형식입니다.

```text
http://proxy.example.com:8080
```

프록시 인증이 필요한 경우 해당 프록시 서비스가 제공하는 인증 URL 형식을
사용합니다. 키나 비밀번호를 코드에 넣지 말고 GitHub Secret으로만 관리합니다.

## GitHub Runner

Workflow는 `runs-on: self-hosted`이므로 GitHub Actions Runner가 설치된 PC가
온라인 상태여야 합니다.

Windows Runner에서는 다음이 준비되어 있어야 합니다.

- Python 3.10 이상
- `python` 명령이 PATH에 등록됨
- Git Bash
- Chromium을 설치할 수 있는 권한

Workflow가 실행될 때 의존성과 Playwright Chromium을 설치합니다.

## 자동 실행

현재 `auto-post.yml`은 외부 cron 서비스가 GitHub API로
`workflow_dispatch`를 호출하는 구조입니다. GitHub 자체 schedule은 사용하지 않습니다.

외부 cron 서비스에서는 다음 API를 `POST`로 호출합니다.

```text
https://api.github.com/repos/OWNER/REPOSITORY/actions/workflows/auto-post.yml/dispatches
```

JSON 본문:

```json
{
  "ref": "main"
}
```

헤더:

```text
Accept: application/vnd.github+json
Authorization: Bearer GITHUB_TOKEN
Content-Type: application/json
```

`ref`는 실제 Workflow가 있는 기본 브랜치 이름으로 바꿉니다.

외부 cron 호출 후 GitHub의 `Actions` 탭에 실행 기록이 생기지 않으면
Python 코드가 아니라 외부 cron 또는 GitHub API 권한 문제입니다.

## 수동 테스트

1. GitHub 저장소의 `Actions` 탭으로 이동
2. `Coupang -> Threads 자동 게시` 선택
3. `Run workflow` 실행
4. 로그에서 최종 URL과 상품 링크 수 확인

정상적인 상품목록 페이지라면 상품 링크가 여러 개 발견되어야 합니다.

```text
[디버그] 최종 URL: ...
[스크린샷] 화면 상단에서 상품 링크 20개 발견
[스크린샷] 선택된 상품: ...
[홍보 이미지] 카드 생성 완료: goldbox_item.png
```

`pages.coupang.com` 행사 페이지로 리다이렉트되거나 상품 링크가 5개 미만이면
실행을 실패시키고 `coupang-debug-*` Artifact를 남깁니다.

## 이미지 생성

`product_card_renderer.py`가 상품목록 카드에서 추출한 값을 이용해 홍보 이미지를
새로 만듭니다.

- 왼쪽: 상품 이미지
- 오른쪽: 로켓 내일 표시
- 상품명
- 할인율 배지
- 판매가와 정가
- 남은 시간

따라서 원본 골드박스의 작은 카드 화면을 그대로 게시하지 않고, 큰 홍보 카드로
재구성합니다.

## 게시 기록

`posted.json`에 당일 게시한 상품 키를 기록합니다. 같은 날 동일 상품이 다시
선택되지 않도록 URL의 `itemId`, `vendorItemId` 또는 상품 ID를 사용합니다.

동시에 여러 Workflow가 실행되지 않도록 `concurrency`도 설정되어 있습니다.

## Threads 토큰 자동 갱신

`refresh-token.yml`은 매월 1일 UTC 03:00에 실행됩니다. 수동 실행도 가능합니다.

토큰 갱신 Workflow에는 GitHub Secret을 수정할 수 있는 권한의 `GH_PAT`가 필요합니다.
응답 오류가 발생하면 새 토큰을 저장하지 않고 Workflow를 실패시킵니다.

## 디버그 파일

실패하거나 실행이 끝나면 다음 파일이 GitHub Actions Artifact에 저장될 수 있습니다.

- `debug_full_page.png`
- `debug_page.html`
- `source_card.png`
- `product_source.png`
- `goldbox_item.png`

`debug_full_page.png`에서 상품목록 대신 행사 페이지가 보이면 페이지 리다이렉트,
프록시, 쿠팡의 환경별 응답 차이를 먼저 확인해야 합니다.

## 주의사항

- 상품 선택 화면의 HTML 구조가 바뀌면 추출 선택자를 조정해야 합니다.
- Threads 컨테이너는 이미지 처리가 완료된 뒤 발행하도록 상태를 확인합니다.
- 게시글의 `광고` 주제 태그와 쿠팡파트너스 고지 문구는 별개의 개념일 수 있으므로
  실제 운영 전 관련 정책에 맞는 고지 방식을 확인해야 합니다.
- API 키와 토큰은 소스 코드, 로그, 커밋에 포함하지 않습니다.