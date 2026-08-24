# -*- coding: utf-8 -*-
"""
Playwright를 사용하여 골드박스 페이지에서 정확한 상품 카드 엘리먼트를 찾아 
할인율, 전체 상품명, 가격이 포함된 카드 전체를 스크린샷 캡처하는 모듈.
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
    골드박스 페이지에서 후보 상품과 일치하는 '카드 UI 엘리먼트'를 찾아 
    카드 영역 그대로 스크린샷을 찍어 반환한다. (할인율 및 풀네임 자동 추출)
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
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            },
        )

        page = context.new_page()
        apply_stealth_scripts(page)

        # Step 1: 메인 세션 확보
        try:
            page.goto(main_url, wait_until="domcontentloaded", timeout=15000)
            time.sleep(1.5)
        except Exception:
            pass

        # Step 2: 골드박스 페이지 접속
        print(f"[스크린샷] 골드박스 페이지 접속: {target_goldbox_url}")
        try:
            page.goto(target_goldbox_url, wait_until="domcontentloaded", timeout=25000)
            time.sleep(3)
        except Exception as e:
            print(f"[스크린샷] 접속 경고: {e}")

        if "Access Denied" in page.title() or "Access Denied" in (page.content() or ""):
            print("[에러] 골드박스 페이지 접속 차단됨(Access Denied)")
            browser.close()
            return None, None, None

        # 충분한 스크롤을 통해 모든 골드박스 카드 로딩 유도
        for _ in range(12):
            page.mouse.wheel(0, 900)
            time.sleep(0.3)
        time.sleep(2)

        # 골드박스 상품 카드를 감싸고 있는 컨테이너 셀렉터 집중 탐색
        card_selectors = [
            "li.baby-product", "div.baby-product",
            "div[class*='product-card']", "div[class*='ProductCard']",
            "div[class*='deal-item']", "div[class*='DealItem']",
            "li[class*='item']", "div[class*='item']",
            "a[href*='/products/']"
        ]
        combined_selector = ", ".join(card_selectors)

        cards_data = []
        for frame in page.frames:
            try:
                elements = frame.query_selector_all(combined_selector)
                for el in elements:
                    try:
                        raw_text = el.inner_text() or ""
                        # 상품 카드 형태를 갖추고 가격 및 텍스트가 있는 경우만 수집
                        if len(raw_text.strip()) > 10 and ("원" in raw_text or "%" in raw_text):
                            norm_text = _normalize_text(raw_text)
                            cards_data.append((el, raw_text, norm_text))
                    except Exception:
                        continue
            except Exception:
                continue

        print(f"[스크린샷] 수집된 유효 상품 카드 후보: {len(cards_data)}개")

        # 각 후보 순회하며 매칭 검증
        for price, name, candidate in ready_candidates:
            keywords = _clean_keywords(name)
            price_int = int(price) if price else 0
            price_num_str = str(price_int)
            price_formatted = f"{price_int:,}"

            norm_kws = [_normalize_text(k) for k in keywords if len(k) > 1]
            brand_keyword = norm_kws[0] if norm_kws else ""

            for card, raw_text, norm_text in cards_data:
                is_matched = False

                has_price = (price_num_str in norm_text) or (price_formatted in raw_text)
                matched_kws = [k for k in norm_kws if k in norm_text]

                # 브랜드가 일치하고 가격 또는 다중 키워드가 맞는 경우
                if brand_keyword and brand_keyword in norm_text:
                    if has_price or len(matched_kws) >= 2:
                        is_matched = True

                if is_matched:
                    print(f"[스크린샷] ✅ 골드박스 카드 완벽 매칭 성공! (매칭 키워드: {matched_kws})")
                    try:
                        card.scroll_into_view_if_needed()
                        time.sleep(0.5)
                        
                        # 카드 요소 영역만 깔끔하게 스크린샷 캡처
                        card.screenshot(path=screenshot_path)

                        # 카드 내부 텍스트에서 정확한 풀네임 추출
                        lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
                        full_name = name
                        for line in lines:
                            if len(line) > 10 and not "원" in line and not "%" in line and not "남은" in line:
                                full_name = line
                                break

                        # 할인율(%) 파싱
                        parsed_discount = None
                        discount_match = re.search(r"(\d+)%", raw_text)
                        if discount_match:
                            parsed_discount = float(discount_match.group(1))

                        print(f"[스크린샷] 📌 추출된 풀네임: {full_name}")
                        print(f"[스크린샷] 📌 추출된 할인율: {parsed_discount}%")

                        browser.close()
                        return candidate, full_name, parsed_discount

                    except Exception as e:
                        print(f"[스크린샷] 카드 엘리먼트 캡처 중 오류 발생: {e}")

        print("[스크린샷] 골드박스 카드 매칭 실패 (이번 회차는 스킵)")
        browser.close()
        return None, None, None
