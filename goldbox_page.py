# -*- coding: utf-8 -*-
"""
골드박스 페이지를 한 번만 열어서 모든 카드의 정확한 정보를 수집하고,
각 카드를 개별 이미지로 캡처하는 모듈.

왜 필요한가:
  골드박스 Open API의 productPrice는 쿠폰 적용 전 '정가'를 주는 경우가 있고
  (예: 정가 14,780원 / 실제 3,780원), 상품명도 짧게 잘려서 온다.
  할인율은 아예 오지 않는다. 정확한 숫자와 전체 상품명은 페이지에만 있다.

수집 항목 (productId 기준):
  full_name, sale_price, original_price, discount_rate,
  remaining_time, coupon_required, card_image
"""
import math
import os
import re

GOLDBOX_URL = "https://www.coupang.com/np/goldbox"
HOME_URL = "https://www.coupang.com/"
CARD_DIR = "cards"

# Akamai Bot Manager 는 IP 가 아니라 브라우저 지문으로 차단한다.
# 번들 Chromium + headless 조합은 탐지되므로 아래 세 가지를 기본값으로 둔다.
#   1) PC에 설치된 실제 크롬 사용      (BROWSER_CHANNEL, 기본 chrome)
#   2) headless 끄기                   (HEADLESS=1 로 켤 수 있음)
#   3) 프로필 디렉터리 유지 -> 쿠키 축적 (BROWSER_PROFILE_DIR)
BROWSER_CHANNEL = os.environ.get("BROWSER_CHANNEL", "chrome")
HEADLESS = os.environ.get("HEADLESS", "0") == "1"
PROFILE_DIR = os.environ.get("BROWSER_PROFILE_DIR", ".browser-profile")

# 창 크기. 쿠팡은 반응형이라 폭이 좁으면 카드 배치와 구조가 바뀐다.
# --start-maximized 는 실제 창 크기와 렌더링 크기를 어긋나게 만들어 쓰지 않는다.
WINDOW_WIDTH = int(os.environ.get("WINDOW_WIDTH", "1680"))
WINDOW_HEIGHT = int(os.environ.get("WINDOW_HEIGHT", "1200"))

LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-features=IsolateOrigins,site-per-process",
    f"--window-size={WINDOW_WIDTH},{WINDOW_HEIGHT}",
    "--window-position=0,0",
    "--force-device-scale-factor=1",
    "--hide-scrollbars",
]
# 크롬 상단의 "자동화된 소프트웨어" 표시와 관련 플래그를 제거한다
IGNORE_ARGS = ["--enable-automation", "--disable-extensions"]

STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['ko-KR', 'ko', 'en-US']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
window.chrome = window.chrome || {runtime: {}};
const origQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (p) => (
  p.name === 'notifications'
    ? Promise.resolve({state: Notification.permission})
    : origQuery(p)
);
"""

PRICE_PATTERN = re.compile(r"([\d,]{3,})\s*원")
PERCENT_ONLY_PATTERN = re.compile(r"^(\d{1,2})\s*%$")
TIMER_PATTERN = re.compile(r"(\d{1,2}:\d{2}:\d{2})\s*남음")

# 조건부 가격이라 '판매가'로 쓰면 안 되는 줄
CONDITIONAL_LINE = re.compile(r"가입\s*쿠폰가|WOW|와우|첫구매|신규")
# 가격이 아닌 숫자가 섞인 줄
NOISE_LINE = re.compile(r"판매됨|배송|도착|남음|리뷰")
# 단위당 가격, 리뷰 수 등은 괄호 안에 있으므로 통째로 제거한다
PAREN_PATTERN = re.compile(r"\([^)]*\)")
# 상품명 줄에서 배제할 패턴
NOT_A_NAME = re.compile(
    r"원|%|로켓|남음|판매|쿠폰|무료|배송|도착|혜택|반품|설치|적용|\(\d"
)
# 상품명 앞에 붙는 배지성 단어. 반복 제거한다.
BADGE_PREFIX = re.compile(
    r"^(사은품|증정|쿠폰|단독특가|특가|기획세트|한정수량|신상품|베스트|"
    r"오늘출발|당일발송|무료배송|R\.?LUX|WOW|와우)\s*[|·:]?\s*",
    re.IGNORECASE,
)
# 브랜드 배지만 있는 줄 (상품명이 아님)
BRAND_ONLY = re.compile(r"^(R\.?LUX|WOW|와우|LUX|BEST|NEW)$", re.IGNORECASE)
HANGUL = re.compile(r"[가-힣]")


def _parse_card(text: str) -> dict:
    """카드 전체 텍스트에서 상품명, 가격, 할인율, 남은시간을 뽑는다."""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    result = {
        "full_name": None,
        "sale_price": None,
        "original_price": None,
        "discount_rate": None,
        "remaining_time": None,
        "coupon_required": False,
    }

    prices = []           # (금액, 쿠폰조건여부)
    name_candidates = []  # 상품명 후보
    for line in lines:
        timer = TIMER_PATTERN.search(line)
        if timer and not result["remaining_time"]:
            result["remaining_time"] = timer.group(1)
            continue

        percent = PERCENT_ONLY_PATTERN.match(line)
        if percent and result["discount_rate"] is None:
            result["discount_rate"] = float(percent.group(1))
            continue

        # 상품명 후보 수집. 첫 줄을 그냥 쓰면 브랜드 배지("R.LUX", "Sulwhasoo")를
        # 상품명으로 잡는 문제가 생기므로, 후보를 모아 뒤에서 가장 적합한 것을 고른다.
        if not NOT_A_NAME.search(line):
            candidate = line
            # "사은품 설화수 윤조..." 처럼 앞에 붙는 배지 단어를 반복 제거
            while True:
                stripped_candidate = BADGE_PREFIX.sub("", candidate).strip()
                if stripped_candidate == candidate:
                    break
                candidate = stripped_candidate
            if candidate and not BRAND_ONLY.match(candidate) and len(candidate) >= 4:
                name_candidates.append(candidate)
            continue

        # 가격 수집. 조건부 가격 줄과 노이즈 줄은 제외
        if CONDITIONAL_LINE.search(line) or NOISE_LINE.search(line):
            continue
        # 괄호 안 단위당 가격/리뷰수를 걷어내고 첫 번째 금액만 본다
        cleaned = PAREN_PATTERN.sub(" ", line)
        match = PRICE_PATTERN.search(cleaned)
        if match:
            try:
                amount = int(match.group(1).replace(",", ""))
            except ValueError:
                continue
            if amount > 0:
                prices.append((amount, "쿠폰" in cleaned))

    # 상품명 선택: 한글이 들어간 후보를 우선하고, 그중 가장 긴 것을 쓴다.
    # (브랜드명은 보통 영문 짧은 줄, 실제 상품명은 한글 긴 줄이다)
    if name_candidates:
        hangul_first = [c for c in name_candidates if HANGUL.search(c)]
        pool = hangul_first or name_candidates
        result["full_name"] = max(pool, key=len)

    if prices:
        amounts = [p[0] for p in prices]
        result["sale_price"] = min(amounts)
        if len(amounts) > 1 and max(amounts) > min(amounts):
            result["original_price"] = max(amounts)
        # 최저가 줄에 '쿠폰'이 있으면 쿠폰 적용 조건부 가격
        for amount, is_coupon in prices:
            if amount == result["sale_price"] and is_coupon:
                result["coupon_required"] = True

    # 할인율 배지를 못 읽었으면 두 가격으로 계산
    if (
        result["discount_rate"] is None
        and result["sale_price"]
        and result["original_price"]
    ):
        sale, original = result["sale_price"], result["original_price"]
        result["discount_rate"] = float(
            math.floor((original - sale) / original * 100)
        )

    return result


def scrape_all(max_cards: int = 60) -> dict:
    """
    골드박스 페이지를 한 번 열어 모든 카드를 파싱하고 개별 캡처한다.
    반환: {productId(str): {수집 항목...}}
    실패하면 빈 dict.
    """
    if os.environ.get("SCRAPE_GOLDBOX", "1") == "0":
        print("[페이지] SCRAPE_GOLDBOX=0, 페이지 수집 건너뜀")
        return {}

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[페이지] playwright 미설치, 페이지 수집 건너뜀")
        return {}

    os.makedirs(CARD_DIR, exist_ok=True)
    collected = {}

    proxy = os.environ.get("BROWSER_PROXY")

    context_options = {
        "user_data_dir": os.path.abspath(PROFILE_DIR),
        "headless": HEADLESS,
        "args": LAUNCH_ARGS,
        "ignore_default_args": IGNORE_ARGS,
        "viewport": {"width": WINDOW_WIDTH, "height": WINDOW_HEIGHT},
        "device_scale_factor": 2,
        "locale": "ko-KR",
        "timezone_id": "Asia/Seoul",
        "no_viewport": False,
    }
    if proxy:
        context_options["proxy"] = {"server": proxy}
        print("[페이지] 프록시 사용")

    print(
        f"[페이지] 브라우저: channel={BROWSER_CHANNEL or 'chromium(번들)'} "
        f"headless={HEADLESS} 창={WINDOW_WIDTH}x{WINDOW_HEIGHT}"
    )

    try:
        with sync_playwright() as p:
            # 실제 크롬을 먼저 시도하고, 없으면 번들 Chromium 으로 물러난다.
            context = None
            for channel in (BROWSER_CHANNEL, None):
                opts = dict(context_options)
                if channel:
                    opts["channel"] = channel
                try:
                    context = p.chromium.launch_persistent_context(**opts)
                    if not channel:
                        print("[페이지] 실제 크롬을 못 찾아 번들 Chromium 사용")
                    break
                except Exception as exc:
                    print(f"[페이지] channel={channel or 'chromium'} 실행 실패: {exc}")
            if context is None:
                raise RuntimeError("브라우저를 실행할 수 없습니다")

            context.add_init_script(STEALTH_SCRIPT)
            page = context.pages[0] if context.pages else context.new_page()
            try:
                # 골드박스로 직행하면 차단되기 쉽다. 홈을 먼저 거쳐 쿠키를 받는다.
                print("[페이지] 쿠팡 홈 경유")
                page.goto(HOME_URL, timeout=60000, wait_until="domcontentloaded")
                page.wait_for_timeout(3500)
                page.mouse.wheel(0, 600)
                page.wait_for_timeout(1200)

                page.goto(GOLDBOX_URL, timeout=60000, wait_until="domcontentloaded")
                page.wait_for_timeout(5000)

                # 차단 페이지면 한 번 더 시도한다 (쿠키가 쌓인 뒤 통과하는 경우가 있음)
                if "Access Denied" in page.title():
                    print("[페이지] 차단 감지, 15초 후 재시도")
                    page.wait_for_timeout(15000)
                    page.goto(HOME_URL, timeout=60000, wait_until="domcontentloaded")
                    page.wait_for_timeout(3000)
                    page.goto(GOLDBOX_URL, timeout=60000, wait_until="domcontentloaded")
                    page.wait_for_timeout(5000)
                # 천천히 끝까지 내려 지연 로딩을 모두 발동시킨다
                for _ in range(14):
                    page.mouse.wheel(0, 1200)
                    page.wait_for_timeout(900)
                page.wait_for_timeout(2000)
                # 다시 위로 올린 뒤, 이미지 디코딩이 끝날 시간을 준다
                page.mouse.wheel(0, -30000)
                page.wait_for_timeout(2500)

                # 상품 링크를 기준으로 카드를 찾는다.
                # 클래스명은 배포마다 바뀌지만 /vp/products/ 링크 구조는 안정적이다.
                links = page.query_selector_all("a[href*='/vp/products/']")
                print(f"[페이지] 상품 링크 {len(links)}개 발견")

                if not links:
                    # 링크가 0개면 차단인지 렌더 실패인지 구분해서 알려준다
                    title = page.title()
                    body_head = re.sub(r"\s+", " ", page.inner_text("body"))[:200]
                    print(f"[페이지] 진단 - 제목: {title!r}")
                    print(f"[페이지] 진단 - URL: {page.url}")
                    print(f"[페이지] 진단 - 본문 앞부분: {body_head!r}")
                    blocked = any(
                        w in (title + body_head)
                        for w in ("Access Denied", "차단", "비정상", "Forbidden",
                                  "잠시 후", "Error", "봇")
                    )
                    if blocked or not body_head.strip():
                        print(
                            "[페이지] 쿠팡(Akamai)이 접근을 차단했습니다.\n"
                            "         IP보다 브라우저 지문 때문일 가능성이 큽니다. 확인 순서:\n"
                            "         1) 실제 크롬 설치 여부 - 로그의 channel 값 확인\n"
                            "         2) headless 여부 - HEADLESS=0 이어야 하고,\n"
                            "            러너가 서비스가 아니라 콘솔(로그인 세션)로 떠 있어야 합니다\n"
                            "         3) 프로필 재사용 여부 - .browser-profile 폴더가 유지되는지\n"
                            "         4) 위가 다 맞는데도 막히면 BROWSER_PROXY 설정"
                        )
                    try:
                        page.screenshot(path="debug_goldbox.png", full_page=False)
                        print("[페이지] 진단 스크린샷 저장: debug_goldbox.png")
                    except Exception:
                        pass

                seen = set()
                for link in links[: max_cards * 3]:
                    if len(collected) >= max_cards:
                        break
                    try:
                        href = link.get_attribute("href") or ""
                        id_match = re.search(r"/vp/products/(\d+)", href)
                        if not id_match:
                            continue
                        product_id = id_match.group(1)
                        if product_id in seen:
                            continue
                        seen.add(product_id)

                        card = link.evaluate_handle(
                            "el => el.closest('li') || el.parentElement"
                        ).as_element()
                        if card is None:
                            continue

                        text = card.inner_text()
                        if not text or len(text.strip()) < 10:
                            continue

                        parsed = _parse_card(text)
                        if not parsed["sale_price"]:
                            continue

                        image_path = os.path.join(CARD_DIR, f"{product_id}.png")
                        try:
                            card.scroll_into_view_if_needed(timeout=5000)

                            # 지연 로딩된 상품 이미지가 다 뜨기를 기다린다.
                            # 안 기다리면 카드 높이가 덜 자란 상태로 잘려서 찍힌다.
                            try:
                                card.evaluate(
                                    """el => Promise.all(
                                        [...el.querySelectorAll('img')].map(img =>
                                          img.complete
                                            ? null
                                            : new Promise(res => {
                                                img.addEventListener('load', res, {once:true});
                                                img.addEventListener('error', res, {once:true});
                                                setTimeout(res, 3000);
                                              })
                                        )
                                    )"""
                                )
                            except Exception:
                                pass
                            page.wait_for_timeout(600)

                            # 카드가 제대로 자랐는지 확인. 너무 작으면 잘린 것으로 본다.
                            box = card.bounding_box()
                            if not box or box["width"] < 200 or box["height"] < 150:
                                print(
                                    f"[페이지] {product_id}: 카드 크기 이상"
                                    f"({box and int(box['width'])}x"
                                    f"{box and int(box['height'])}), 캡처 생략"
                                )
                                parsed["card_image"] = None
                            else:
                                card.screenshot(path=image_path)
                                parsed["card_image"] = image_path
                        except Exception as exc:
                            print(f"[페이지] {product_id}: 캡처 실패 {exc}")
                            parsed["card_image"] = None

                        collected[product_id] = parsed
                    except Exception:
                        continue
            finally:
                context.close()
    except Exception as exc:
        print(f"[페이지] 수집 실패, API 데이터만 사용: {exc}")
        return {}

    print(f"[페이지] 카드 {len(collected)}개 수집 완료")
    return collected


def merge(api_item: dict, page_data: dict) -> dict:
    """API 항목에 페이지에서 읽은 정확한 값을 덮어쓴다. 페이지 값이 우선."""
    found = page_data.get(api_item["id"])
    if not found:
        return api_item

    merged = dict(api_item)

    # 페이지에서 읽은 상품명이 API 이름보다 나을 때만 교체한다.
    # 파싱이 어긋나 브랜드명만 잡히는 경우를 대비한 안전장치.
    page_name = (found.get("full_name") or "").strip()
    api_name = (api_item.get("name") or "").strip()
    if page_name:
        better = (
            len(page_name) >= len(api_name)          # 더 길면 전체 이름일 가능성
            or api_name in page_name                 # API 이름을 포함하면 확장형
            or (HANGUL.search(page_name) and not HANGUL.search(api_name))
        )
        if better:
            merged["name"] = page_name
        else:
            print(
                f"[페이지] {api_item['id']}: 파싱된 이름이 부실해 API 이름 유지 "
                f"({page_name!r} < {api_name!r})"
            )
    if found.get("sale_price"):
        merged["price"] = found["sale_price"]
    if found.get("original_price"):
        merged["original_price"] = found["original_price"]
    if found.get("discount_rate"):
        merged["discount_rate"] = found["discount_rate"]
    merged["remaining_time"] = found.get("remaining_time")
    merged["coupon_required"] = found.get("coupon_required", False)
    merged["card_image"] = found.get("card_image")
    merged["from_page"] = True
    return merged
