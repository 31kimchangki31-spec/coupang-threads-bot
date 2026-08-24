# -*- coding: utf-8 -*-
"""
Playwright를 사용하여 골드박스 페이지에서 대상 상품 카드를 찾고 스크린샷을 캡처하는 모듈.
(Akamai 봇 차단 우회 + 골드박스 프로모션 페이지 맞춤형 유연한 텍스트/키워드/가격 매칭)
"""
import re
import time
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright


def _clean_keywords(name: str) -> list:
    """상품명에서 [로켓프레시] 등 대괄호 태그를 제거하고 의미 있는 핵심 키워드를 추출한다."""
    cleaned_name = re.sub(r"\[[^\]]+\]", " ", name)
    cleaned = re.sub(r"[^\w\s]", " ", cleaned_name)
    tokens = [t.strip() for t in cleaned.split() if len(t.strip()) > 1]
    return tokens


def _deep_extract_ids(candidate_tuple: tuple) -> list:
    """상품 정보 및 URL 쿼리스트링에서 고유 ID(itemId, vendorItemId, pageKey, productId)를 추출한다."""
    price, name, cand = candidate_tuple
    raw_url = cand.get("productUrl", "")
    parsed = urlparse(raw_url)
    params = parse_qs(parsed.query)

    ids = []
    for key in ["itemId", "vendorItemId", "pageKey", "productId"]:
        val = params.get(key, [None])[0]
        if val:
            ids.append(str(val))

    path_match = re.search(r"/products/(\d+)", parsed.path)
    if path_match:
        pid = path_match.group(1)
        if pid not in ids:
            ids.append(pid)

    return ids


def apply_stealth_scripts(page):
    """쿠팡 Akamai 봇 감지 우회를 위한 스텔스 스크립트 주입"""
    page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        window.chrome = {
            runtime: {},
            loadTimes: function() {},
            csi: function() {},
            app: {}
        };
        Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
        Object.defineProperty(navigator, 'languages', { get: () => ['ko-KR', 'ko', 'en-US', 'en'] });
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
            Promise.resolve({ state: Notification.permission }) :
            originalQuery(parameters)
        );
    """)


def find_and_capture_first_match(ready_candidates: list, screenshot_path: str):
    """
    ready_candidates: [(price, name, candidate_dict), ...]
    골드박스 페이지에 접속하여 정확한 상품 카드를 찾아 스크린샷을 저장한다.
    """
    target_goldbox_url = "https://pages.coupang.com/p/121237?sourceType=oms_goldbox"
    main_url = "https://www.coupang.com/"

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-infobars",
                "--disable-dev-shm-usage",
                "--disable-browser-react-native-networking",
                "--window-size=1280,1024",
            ],
        )

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 1024},
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            extra_http_headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            },
        )

        page = context.new_page()
        apply_stealth_scripts(page)

        # Step 1: 쿠팡 메인 접속으로 세션 쿠키 수집
        print(f"[스크린샷] 세션 확보용 쿠팡 메인 접속: {main_url}")
        try:
            page.goto(main_url, wait_until="domcontentloaded", timeout=20000)
            time.sleep(2)
        except Exception as e:
            print(f"[스크린샷] 메인 접속 경고 (계속 진행): {e}")

        # Step 2: 골드박스 이벤트 페이지 접속
        print(f"[스크린샷] 골드박스 페이지 접속 시도: {target_goldbox_url}")
        try:
            page.goto(target_goldbox_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)
        except Exception as e:
            print(f"[스크린샷] 골드박스 접속 실패: {e}")
            browser.close()
            return None, None, None

        print(f"[디버그] 페이지 제목: {page.title()}")
        print(f"[디버그] 최종 URL: {page.url}")

        if "Access Denied" in page.title():
            print("[에러] Access Denied 발생 - 새로고침 재시도")
            time.sleep(2)
            page.reload(wait_until="domcontentloaded")
            time.sleep(3)
            if "Access Denied" in page.title():
                print("[에러] 봇 차단 우회 실패.")
                browser.close()
                return None, None, None

        # 가상 스크롤 로딩
        for _ in range(12):
            page.mouse.wheel(0, 1000)
            time.sleep(0.4)

        selectors = [
            "a[href*='/products/']",
            "a[href*='/vp/products/']",
            "li.goldbox-product",
            "div.goldbox-product",
            ".product-card",
            "[data-product-id]",
            "div[class*='Product']",
            "div[class*='product']",
            "div[class*='Deal']",
            "div[class*='deal']",
            "li[class*='item']",
        ]
        
        combined_selector = ", ".join(selectors)
        card_elements = page.query_selector_all(combined_selector)

        if not card_elements:
            card_elements = page.query_selector_all("a, li, div")

        print(f"[스크린샷] 화면에서 상품 카드 {len(card_elements)}개 탐색됨")

        cards_data = []
        for card in card_elements:
            try:
                text = card.inner_text() or ""
                outer_html = card.evaluate("el => el.outerHTML") or ""
                # 카드에 텍스트나 의미 있는 내용이 있는 경우에만 포함
                if len(text.strip()) > 3 or "href" in outer_html:
                    cards_data.append((card, text, outer_html))
            except Exception:
                continue

        # 후보 목록 순서대로 매칭 검증
        for price, name, candidate in ready_candidates:
            target_ids = _deep_extract_ids((price, name, candidate))
            keywords = _clean_keywords(name)

            brand_keyword = keywords[0] if keywords else ""
            sub_keywords = keywords[1:] if len(keywords) > 1 else []
            
            price_int = int(price) if price else 0
            price_num_str = str(price_int)
            price_formatted = f"{price_int:,}"

            print(
                f"[스크린샷] 매칭 시도 -> 브랜드: '{brand_keyword}' / 키워드목록: {keywords[:4]} / "
                f"ID: {target_ids} / 가격: {price_formatted}원"
            )

            for card, text, outer_html in cards_data:
                is_matched = False
                matched_reason = ""

                # 1. 고유 ID 일치 (최우선)
                if target_ids:
                    for tid in target_ids:
                        if tid in outer_html:
                            is_matched = True
                            matched_reason = f"고유 ID({tid}) 일치"
                            break

                # 2. 브랜드 키워드가 포함된 경우 텍스트 기반 매칭
                if not is_matched and brand_keyword and (brand_keyword in text or brand_keyword in outer_html):
                    # 2-1. 브랜드 + 가격 일치
                    if price_num_str and (price_formatted in text or price_num_str in text or price_formatted in outer_html):
                        is_matched = True
                        matched_reason = f"브랜드('{brand_keyword}') + 가격({price_formatted}) 일치"
                    else:
                        # 2-2. 브랜드 + 서브 키워드 조합 일치 (1개 이상 추가 포함)
                        matched_subs = [kw for kw in sub_keywords[:3] if kw in text or kw in outer_html]
                        if matched_subs:
                            is_matched = True
                            matched_reason = f"브랜드('{brand_keyword}') + 서브키워드({matched_subs}) 일치"

                # 3. 브랜드명이 카드에 정확히 포함되지 않더라도 전체 키워드 중 2개 이상 포함 시 매칭
                if not is_matched and len(keywords) >= 2:
                    matched_kws = [kw for kw in keywords if kw in text or kw in outer_html]
                    if len(matched_kws) >= 2:
                        # 가격 검증 또는 추가 키워드 검증
                        if price_num_str and (price_formatted in text or price_num_str in text):
                            is_matched = True
                            matched_reason = f"복수키워드({matched_kws}) + 가격({price_formatted}) 일치"
                        elif len(matched_kws) >= 3:
                            is_matched = True
                            matched_reason = f"다중키워드({matched_kws}) 일치"

                if is_matched:
                    print(f"[스크린샷] ✅ 매칭 성공! 사유: {matched_reason}")
                    card.scroll_into_view_if_needed()
                    time.sleep(0.5)

                    card.screenshot(path=screenshot_path)

                    lines = [l.strip() for l in text.split("\n") if l.strip()]
                    full_name = name
                    for l in lines:
                        if brand_keyword in l and len(l) > 5:
                            full_name = l
                            break

                    parsed_discount = None
                    discount_match = re.search(r"(\d+)%", text)
                    if discount_match:
                        parsed_discount = float(discount_match.group(1))

                    print(f"[스크린샷] 캡처 완료: {full_name} / 할인율: {parsed_discount}")
                    browser.close()
                    return candidate, full_name, parsed_discount

        browser.close()
        return None, None, None
