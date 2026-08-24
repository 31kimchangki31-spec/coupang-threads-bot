# -*- coding: utf-8 -*-
"""
Playwright를 사용하여 골드박스 페이지에서 대상 상품 카드를 찾고 스크린샷을 캡처하는 모듈.
(공백 제거 정규화 매칭 + 카드 요소 수집 범위 확대 + 상품 상세페이지 Direct Fallback)
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


def _normalize_text(text: str) -> str:
    """공백 및 특수문자를 제거하여 텍스트 매칭율을 극대화한다."""
    if not text:
        return ""
    return re.sub(r"\s+", "", text).lower()


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
    골드박스 페이지에서 카드를 찾아 캡처하거나, 실패 시 직접 상품 URL에 접속하여 스크린샷을 저장한다.
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
                "--window-size=1280,1200",
            ],
        )

        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 1200},
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

        # Step 1: 쿠팡 메인 접속으로 세션 확보
        print(f"[스크린샷] 세션 확보용 쿠팡 메인 접속: {main_url}")
        try:
            page.goto(main_url, wait_until="domcontentloaded", timeout=20000)
            time.sleep(2)
        except Exception as e:
            print(f"[스크린샷] 메인 접속 경고 (계속 진행): {e}")

        # Step 2: 골드박스 페이지 접속
        print(f"[스크린샷] 골드박스 페이지 접속 시도: {target_goldbox_url}")
        try:
            page.goto(target_goldbox_url, wait_until="domcontentloaded", timeout=25000)
            time.sleep(3)
        except Exception as e:
            print(f"[스크린샷] 골드박스 페이지 접속 경고: {e}")

        # 스크롤 동작으로 카드 동적 로딩 유도
        for _ in range(10):
            page.mouse.wheel(0, 900)
            time.sleep(0.3)
        time.sleep(2)

        # 모든 프레임에서 가능한 모든 카드 요소 추출
        cards_data = []
        selectors = [
            "a", "li", "div[class*='product']", "div[class*='Product']",
            "div[class*='deal']", "div[class*='Deal']", "div[class*='card']",
            "div[class*='Card']", "div[class*='item']", "div[class*='Item']"
        ]
        combined_selector = ", ".join(selectors)

        for frame in page.frames:
            try:
                elements = frame.query_selector_all(combined_selector)
                for el in elements:
                    try:
                        raw_text = el.inner_text() or ""
                        if len(raw_text.strip()) > 2:
                            norm_text = _normalize_text(raw_text)
                            outer_html = el.evaluate("e => e.outerHTML") or ""
                            cards_data.append((el, raw_text, norm_text, outer_html))
                    except Exception:
                        continue
            except Exception:
                continue

        print(f"[스크린샷] 수집된 상품 카드 후보 요소: {len(cards_data)}개")

        # 1차 시도: 골드박스 페이지 내 카드 매칭
        for price, name, candidate in ready_candidates:
            target_ids = _deep_extract_ids((price, name, candidate))
            keywords = _clean_keywords(name)

            brand_keyword = keywords[0] if keywords else ""
            sub_keywords = keywords[1:] if len(keywords) > 1 else []
            
            norm_brand = _normalize_text(brand_keyword)
            norm_subs = [_normalize_text(k) for k in sub_keywords if _normalize_text(k)]
            norm_all_kws = [_normalize_text(k) for k in keywords if _normalize_text(k)]

            price_int = int(price) if price else 0
            price_num_str = str(price_int)
            price_formatted = f"{price_int:,}"

            print(
                f"[스크린샷] 매칭 시도 -> 브랜드: '{brand_keyword}' / 키워드: {keywords[:3]} / "
                f"ID: {target_ids} / 가격: {price_formatted}원"
            )

            for card, raw_text, norm_text, outer_html in cards_data:
                is_matched = False
                matched_reason = ""

                # 1. ID 매칭
                if target_ids:
                    for tid in target_ids:
                        if tid in outer_html:
                            is_matched = True
                            matched_reason = f"고유 ID({tid}) 일치"
                            break

                # 2. 브랜드 정규화 텍스트 매칭
                if not is_matched and norm_brand and (norm_brand in norm_text or norm_brand in outer_html.lower()):
                    if price_num_str and (price_formatted in raw_text or price_num_str in norm_text):
                        is_matched = True
                        matched_reason = f"브랜드('{brand_keyword}') + 가격({price_formatted}) 일치"
                    elif norm_subs:
                        matched_subs = [k for k in norm_subs if k in norm_text]
                        if matched_subs:
                            is_matched = True
                            matched_reason = f"브랜드('{brand_keyword}') + 서브키워드({matched_subs}) 일치"

                # 3. 키워드 2개 이상 정규화 매칭
                if not is_matched and len(norm_all_kws) >= 2:
                    matched_kws = [k for k in norm_all_kws if k in norm_text]
                    if len(matched_kws) >= 2:
                        is_matched = True
                        matched_reason = f"다중 키워드({matched_kws}) 일치"

                if is_matched:
                    print(f"[스크린샷] ✅ 골드박스 페이지 매칭 성공! 사유: {matched_reason}")
                    try:
                        card.scroll_into_view_if_needed()
                        time.sleep(0.5)
                        card.screenshot(path=screenshot_path)
                    except Exception as e:
                        print(f"[스크린샷] 카드 단독 캡처 실패, 전체 화면 캡처 대체: {e}")
                        page.screenshot(path=screenshot_path)

                    parsed_discount = None
                    discount_match = re.search(r"(\d+)%", raw_text)
                    if discount_match:
                        parsed_discount = float(discount_match.group(1))

                    browser.close()
                    return candidate, name, parsed_discount

        # 2차 Fallback 시도: 골드박스 페이지 매칭 실패 시 1위 후보 상품 상세 URL로 직접 접속하여 스크린샷 캡처
        print("[스크린샷] 골드박스 카드 매칭 실패 -> 1순위 후보 상품 페이지 직접 접속 Fallback 진행")
        fallback_price, fallback_name, fallback_candidate = ready_candidates[0]
        prod_url = fallback_candidate.get("productUrl") or fallback_candidate.get("landingUrl")

        if prod_url:
            print(f"[스크린샷] 상품 URL 직접 접속: {prod_url}")
            try:
                page.goto(prod_url, wait_until="domcontentloaded", timeout=20000)
                time.sleep(2)
                page.screenshot(path=screenshot_path)
                print(f"[스크린샷] ✅ Fallback 캡처 완료: {fallback_name}")
                browser.close()
                return fallback_candidate, fallback_name, None
            except Exception as e:
                print(f"[스크린샷] Fallback 접속 캡처 에러: {e}")

        browser.close()
        return None, None, None
