# -*- coding: utf-8 -*-
"""
Playwright를 사용하여 골드박스 페이지에서 대상 상품 카드를 찾고 스크린샷을 캡처하는 모듈.
(Access Denied 캡처 방지 + API 썸네일 Fallback + 유연한 골드박스 카드 매칭)
"""
import re
import time
import requests
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


def _download_api_image(img_url: str, save_path: str) -> bool:
    """Playwright 캡처 실패 시 파트너스 API의 상품 이미지를 직접 다운로드한다."""
    if not img_url:
        return False
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        }
        res = requests.get(img_url, headers=headers, timeout=10)
        if res.status_code == 200 and len(res.content) > 1000:
            with open(save_path, "wb") as f:
                f.write(res.content)
            print(f"[스크린샷] API 이미지 직접 다운로드 성공: {save_path}")
            return True
    except Exception as e:
        print(f"[스크린샷] API 이미지 다운로드 실패: {e}")
    return False


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
    골드박스 페이지 접속 -> 카드 스크린샷 -> 실패시 API 썸네일 이미지 fallback
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

        # Access Denied 인지 체크
        if "Access Denied" in page.title() or "Access Denied" in (page.content() or ""):
            print("[에러] 골드박스 페이지 접속 차단됨(Access Denied)")
            browser.close()
            # API 이미지 직접 다운로드 Fallback
            first_cand = ready_candidates[0]
            img_url = first_cand[2].get("productImage") or first_cand[2].get("imageContentUrl")
            if _download_api_image(img_url, screenshot_path):
                return first_cand[2], first_cand[1], None
            return None, None, None

        # 가상 스크롤
        for _ in range(8):
            page.mouse.wheel(0, 800)
            time.sleep(0.3)
        time.sleep(1.5)

        # 카드 수집
        cards_data = []
        selectors = ["a", "li", "div[class*='product']", "div[class*='deal']", "div[class*='item']", "div[class*='card']"]
        
        for frame in page.frames:
            try:
                elements = frame.query_selector_all(", ".join(selectors))
                for el in elements:
                    try:
                        raw_text = el.inner_text() or ""
                        if len(raw_text.strip()) > 3:
                            norm_text = _normalize_text(raw_text)
                            cards_data.append((el, raw_text, norm_text))
                    except Exception:
                        continue
            except Exception:
                continue

        print(f"[스크린샷] 수집된 후보 요소: {len(cards_data)}개")

        # 매칭 검사
        for price, name, candidate in ready_candidates:
            keywords = _clean_keywords(name)
            price_int = int(price) if price else 0
            price_num_str = str(price_int)
            price_formatted = f"{price_int:,}"

            norm_kws = [_normalize_text(k) for k in keywords if len(k) > 1]

            for card, raw_text, norm_text in cards_data:
                is_matched = False

                # 가격 존재 여부
                has_price = (price_num_str in norm_text) or (price_formatted in raw_text)
                # 키워드 일치 개수
                matched_kws = [k for k in norm_kws if k in norm_text]

                # 조건: (가격 일치 AND 키워드 1개 이상) OR (키워드 2개 이상)
                if (has_price and len(matched_kws) >= 1) or (len(matched_kws) >= 2):
                    is_matched = True

                if is_matched:
                    print(f"[스크린샷] ✅ 골드박스 카드 매칭 성공: {name} (키워드: {matched_kws})")
                    try:
                        card.scroll_into_view_if_needed()
                        time.sleep(0.5)
                        card.screenshot(path=screenshot_path)
                        
                        # 캡처 결과물 차단 화면 검증
                        if "Access Denied" in (card.inner_text() or ""):
                            raise Exception("차단 화면 캡처됨")

                        parsed_discount = None
                        discount_match = re.search(r"(\d+)%", raw_text)
                        if discount_match:
                            parsed_discount = float(discount_match.group(1))

                        browser.close()
                        return candidate, name, parsed_discount
                    except Exception as e:
                        print(f"[스크린샷] 카드 캡처 오류: {e}")

        browser.close()

        # 3차 Fallback: 골드박스 스크린샷 매칭이 모두 실패했거나 차단 시
        # 절대 차단 페이지를 찍어 올리지 않고, 쿠팡 파트너스 API의 깔끔한 상품 이미지 원본 다운로드!
        print("[스크린샷] 골드박스 매칭 실패 -> 파트너스 API 상품 원본 이미지 다운로드 Fallback")
        first_price, first_name, first_candidate = ready_candidates[0]
        img_url = (
            first_candidate.get("productImage") 
            or first_candidate.get("imageContentUrl")
            or first_candidate.get("productImageUrl")
        )

        if img_url and _download_api_image(img_url, screenshot_path):
            return first_candidate, first_name, None

        return None, None, None
