# 쿠팡파트너스 → 쓰레드 자동 게시 봇

쿠팡 **골드박스(당일 특가)** 상품을 자동으로 조회해서, 상품명·가격·이미지·파트너스 딥링크를
스크린샷과 같은 형식(상품명 → 가격 → 링크, 상품 이미지 첨부)으로 쓰레드(Threads)에 자동 게시합니다.
GitHub Actions로 매일 자동 실행되며 비용은 무료입니다.

- "광고" 표시는 쓰레드가 `link.coupang.com` 같은 알려진 제휴 링크 도메인을 자동 인식해서 붙여주는 것으로
  보여요. 별도 설정 없이 딥링크만 포함하면 자동으로 붙을 가능성이 높습니다 (게시 후 꼭 눈으로 확인해보세요).
- 사람 게시글을 퍼와서 재가공하는 방식은 저작권·플랫폼 정책 리스크가 커서 넣지 않았어요. 대신 쿠팡의
  공식 골드박스/베스트 API로 검증된 인기·특가 상품만 사용합니다.
- `products.txt`로 직접 상품을 지정하고 싶으면 예전 방식(`main.py`의 `load_products` 사용)으로 되돌릴
  수도 있어요, 필요하면 말씀해주세요.

## 1. 준비물
- GitHub 계정 (무료)
- 쿠팡파트너스 Access Key / Secret Key
- Threads User ID / 장기 Access Token(60일)

## 2. GitHub 저장소 만들기
1. github.com에서 새 저장소(Private 추천)를 만듭니다.
2. 이 폴더(`coupang-threads-bot`) 안의 모든 파일을 그대로 업로드합니다.

## 3. Secrets 등록 (제일 중요! 키를 코드에 직접 쓰지 않습니다)
저장소 → **Settings → Secrets and variables → Actions → New repository secret** 에서 아래 4개를 등록하세요.

| Secret 이름 | 값 |
|---|---|
| `COUPANG_ACCESS_KEY` | 쿠팡파트너스 Access Key |
| `COUPANG_SECRET_KEY` | 쿠팡파트너스 Secret Key |
| `THREADS_USER_ID` | 발급받은 Threads User ID |
| `THREADS_ACCESS_TOKEN` | 60일짜리 장기 Access Token |

토큰 자동 갱신 워크플로우까지 쓰려면 추가로:

| Secret 이름 | 값 |
|---|---|
| `GH_PAT` | Settings → Developer settings → Personal access tokens 에서 발급 (repo, secrets 쓰기 권한) |

(AI로 캡션을 생성하고 싶다면 `ANTHROPIC_API_KEY`도 추가하고, `auto-post.yml`의 해당 줄 주석을 해제하세요.)

## 4. 상품 목록 수정
`products.txt`를 열어 실제 홍보하고 싶은 쿠팡 상품명과 URL로 바꿔주세요.
한 줄에 하나씩, `상품명 | 상품URL` 형식입니다.

## 5. 실행 확인
- 저장소 상단 **Actions** 탭 → `Coupang -> Threads 자동 게시` → **Run workflow** 버튼으로 수동 테스트 가능
- 정상 동작하면 매일 한국시간 오전 9시에 자동으로 하나씩 게시됩니다.
- 게시된 상품은 `posted.json`에 자동 기록되어 중복 게시되지 않습니다.

## 6. 게시 주기/개수 바꾸기
`.github/workflows/auto-post.yml`의 `cron` 값을 수정하면 됩니다.
예: 하루 2번 → `"0 0,6 * * *"`

## 7. 주의사항
- 쿠팡파트너스 정책상 게시물에 수수료 고지 문구가 자동으로 포함됩니다(caption_generator.py 참고). 임의로 삭제하지 마세요.
- Threads 장기 토큰은 60일마다 만료됩니다. `refresh-token.yml`을 함께 등록해두면 매달 자동 갱신됩니다.
- 채팅에서 주고받은 API 키는 이미 노출된 것으로 간주하고, 설정이 끝나면 쿠팡Wing에서 한 번 재발급받는 걸 권장합니다.
