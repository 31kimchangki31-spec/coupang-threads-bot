# -*- coding: utf-8 -*-
"""
쿠팡 골드박스 페이지에서 특정 상품 카드를 실제 브라우저로 열어
화면 그대로 스크린샷으로 캡처하는 모듈.
"""
import re
import math
from playwright.sync_api import sync_playwright

GOLDBOX_URL = "https://www.coupang.com/np/goldbox"

DISCOUNT_WITH_LABEL_PATTERN = re.compile(r"(\d+)\s*%\s*할인")
BARE_PERCENT_PATTERN = re.compile(r"^(\d+)\s*%$")
TWO_PRICE_PATTERN = re.compile(r"([\d,]+)\s*원[^0-9]{0,10}?([\d,]+)\s*원")
SKIP_LINE_PATTERN = re.compile(r"원|%|로켓|남음|배송|판매|쿠폰|무료")
HANGUL_PATTERN = re.compile(r"[가-힣]")


def _normalize_text(text: str) -> str:
    """공백 및 특수문자를 제거하여 비교용 텍스트로 정규화"""
    return re.sub(r"[^\w\d가-힣]", "", text)


def _compute_discount_from_prices(text: str):
    m = TWO_PRICE_PATTERN.search(text)
    if not m:
        return None
    try:
        price_a = int(m.group(1).replace(",", ""))
        price_b = int(m.group(2).replace(",", ""))
    except ValueError:
        return None
    sale, original = min(price_a, price_b), max(price_a, price_b)
    if original <= sale or original <= 0:
        return None
    return math.floor((original - sale) / original * 100)


def _parse_card_text(text: str, fallback_name: str):
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    full_name = fallback_name
    discount_rate = None

    for line in lines:
        if discount_rate is None:
            m = DISCOUNT_WITH_LABEL_PATTERN.search(line) or BARE_PERCENT_PATTERN.match(line)
            if m:
                discount_rate = float(m.group(1))
                continue
        if (
            not SKIP_LINE_PATTERN.search(line)
            and len(line) > 3
            and HANGUL_PATTERN.search(line)
        ):
            full_name = line
            break

    if discount_rate is None:
        computed = _compute_discount_from_prices(text)
        if computed is not None:
            discount_rate = float(computed)

    return full_name, discount_rate


def find_and_capture_first_match(candidates_to_try: list, output_path: str):
    """
    candidates_to_try = [(price, name, candidate_dict), ...]
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            channel="chromium",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-sandbox",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=2,
            locale="ko-KR",
            timezone_id="Asia/Seoul",
        )
        page = context.new_page()
        page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        try:
            print(f"[스크린샷] 골드박스 페이지 접속 시도: {GOLDBOX_URL}")
            page.goto(GOLDBOX_URL, timeout=60000)
            page.wait_for_timeout(4000)

            print(f"[디버그] 페이지 제목: {page.title()}")
            print(f"[디버그] 최종 URL: {page.url}")

            # 페이지 스크롤 처리
            page.mouse.wheel(0, 1000)
            page.wait_for_timeout(2000)

            prev_count = -1
            stable_rounds = 0
            for _ in range(20):
                page.mouse.wheel(0, 1500)
                page.wait_for_timeout(700)
                current_count = len(page.query_selector_all("a[href*='/vp/products/']"))
                if current_count == prev_count:
                    stable_rounds += 1
                    if stable_rounds >= 2:
                        break
                else:
                    stable_rounds = 0
                prev_count = current_count

            # 상품 카드 셀렉터 탐색 개선
            cards = page.query_selector_all(
                "li.baby-product, .instant-n-item, div[class*='ProductItem'], [class*='ProductCard']"
            )
            
            # 특정 셀렉터로 수집이 실패한 경우 fallback 처리
            if not cards or len(cards) < 5:
                links = page.query_selector_all("a[href*='/vp/products/']")
                cards = []
                for link in links:
                    try:
                        # 억지로 최상위 div를 잡지 않도록 'li' 또는 특정 클래스를 지닌 컨테이너 위주로 탐색
                        parent = link.evaluate_handle(
                            """el => {
                                let p = el.parentElement;
                                while (p && p.tagName !== 'BODY') {
                                    if (p.tagName === 'LI' || p.className.includes('item') || p.className.includes('card') || p.className.includes('product')) {
                                        return p;
                                    }
                                    p = p.parentElement;
                                }
                                return el;
                            }"""
                        ).as_element()
                        if parent and parent not in cards:
                            cards.append(parent)
                    except Exception:
                        continue

            print(f"[스크린샷] 화면에서 카드 {len(cards)}개 탐색됨")

            # 카드별 텍스트 및 속성(href) 사전 캐싱
            card_info_list = []
            for card in cards:
                try:
                    text = card.inner_text()
                    # 카드 내부 링크 UR/상품 ID 추출
                    link_elem = card.query_selector("a[href*='/vp/products/']")
                    href = link_elem.get_attribute("href") if link_elem else ""
                    card_info_list.append((card, text, href))
                except Exception:
                    continue

            for price, name, candidate in candidates_to_try:
                price_str = f"{int(price):,}"
                # 특수문자 및 불필요 키워드 제거한 검색용 키워드 생성
                clean_name = re.sub(r"\[.*?\]|\(.*?\)", "", name).strip()
                name_fragment = clean_name[:6] if clean_name else name[:6]
                
                norm_name_fragment = _normalize_text(name_fragment)
                print(f"[스크린샷] 매칭 시도: {price_str}원 / '{name_fragment}'")

                # URL 내 product_id 파싱 시도 (candidate 내 URL이 있는 경우)
                target_url = candidate.get("url", "") if isinstance(candidate, dict) else ""
                target_pid = ""
                if "/vp/products/" in target_url:
                    match_pid = re.search(r"/products/(\d+)", target_url)
                    if match_pid:
                        target_pid = match_pid.group(1)

                for card, text, href in card_info_list:
                    norm_text = _normalize_text(text)
                    
                    # 1순위: URL 상품 ID 기반 매칭
                    pid_matched = target_pid and target_pid in href
                    # 2순위: 가격 + 상품명 키워드 매칭
                    text_matched = (price_str in text) and (norm_name_fragment in norm_text)

                    if pid_matched or text_matched:
                        card.screenshot(path=output_path)
                        full_name, discount_rate = _parse_card_text(text, name)
                        print(f"[스크린샷] 매칭 성공: {full_name} / 할인율: {discount_rate}")
                        return candidate, full_name, discount_rate

            print("[스크린샷] 시도한 후보 중 화면과 일치하는 카드를 하나도 찾지 못함")
            return None, None, None

        except Exception as e:
            print(f"[스크린샷] 실패: {e}")
            return None, None, None
        finally:
            browser.close()


def capture_goldbox_card_screenshot(target_price: int, target_name: str, output_path: str):
    matched, full_name, discount_rate = find_and_capture_first_match(
        [(target_price, target_name, None)], output_path
    )
    return matched is not None, full_name or target_name, discount_rate
