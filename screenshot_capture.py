# -*- coding: utf-8 -*-
"""
변경된 쿠팡 골드박스 랜딩 페이지 대응 스크린샷 캡처 모듈
"""

import re
import math
import time
from playwright.sync_api import sync_playwright

# ★ 변경된 신규 골드박스 랜딩 페이지 URL 적용
GOLDBOX_URL = "https://www.coupang.com/mlp/web/mlp-landing-page?landingId=3712&sourceType=gm_crm_goldbox&subSourceType=cmgoms"
FALLBACK_GOLDBOX_URL = "https://pages.coupang.com/p/121237?sourceType=oms_goldbox"

DISCOUNT_WITH_LABEL_PATTERN = re.compile(r"(\d+)\s*%\s*할인")
BARE_PERCENT_PATTERN = re.compile(r"^(\d+)\s*%$")
TWO_PRICE_PATTERN = re.compile(r"([\d,]+)\s*원[^0-9]{0,10}?([\d,]+)\s*원")
SKIP_LINE_PATTERN = re.compile(r"원|%|로켓|남음|배송|판매|쿠폰|무료")
HANGUL_PATTERN = re.compile(r"[가-힣]")


def _normalize_text(text: str) -> str:
    if not text:
        return ""
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


def extract_product_id(text: str) -> str:
    if not text:
        return ""
    m = re.search(r"products/(\d+)", text) or re.search(r"itemId=(\d+)", text) or re.search(r"(\d{7,12})", text)
    if m:
        return m.group(1)
    return ""


def find_and_capture_first_match(candidates_to_try: list, output_path: str):
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            channel="chromium",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-web-security",
                "--window-size=1920,1080",
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

        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.navigator.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'languages', {get: () => ['ko-KR', 'ko', 'en-US', 'en']});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
        """)

        try:
            print(f"[스크린샷] 변경된 골드박스 랜딩 페이지 접속 시도: {GOLDBOX_URL}")
            try:
                page.goto(GOLDBOX_URL, wait_until="networkidle", timeout=60000)
            except Exception as goto_err:
                print(f"[스크린샷] 지연 발생 -> 폴백 URL 접속 시도: {FALLBACK_GOLDBOX_URL}")
                page.goto(FALLBACK_GOLDBOX_URL, wait_until="domcontentloaded", timeout=60000)

            page.wait_for_timeout(2000)

            # 리뉴얼 안내 화면의 파란색 버튼이 노출되는 경우 자동 클릭 처리
            try:
                renewal_btn = page.locator("text=더욱 새로워진 골드박스 살펴보기")
                if renewal_btn.count() > 0 and renewal_btn.first.is_visible():
                    print("[스크린샷] '새로워진 골드박스' 안내 버튼 클릭")
                    renewal_btn.first.click()
                    page.wait_for_timeout(3000)
            except Exception:
                pass

            print(f"[디버그] 최종 로드 페이지 제목: '{page.title()}'")

            prepared_candidates = []
            for price, name, candidate in candidates_to_try:
                price_num = int(price) if price else 0
                price_str = f"{price_num:,}" if price_num > 0 else ""
                raw_price_str = str(price_num) if price_num > 0 else ""

                clean_name = re.sub(r"\[.*?\]|\(.*?\)", "", name).strip()
                name_fragment = clean_name[:4] if clean_name else name[:4]

                target_url = candidate.get("url", "") if isinstance(candidate, dict) and candidate else ""
                target_pid = extract_product_id(target_url)

                prepared_candidates.append({
                    "price_str": price_str,
                    "raw_price_str": raw_price_str,
                    "norm_name_fragment": _normalize_text(name_fragment),
                    "orig_name_fragment": name_fragment,
                    "target_pid": target_pid,
                    "fallback_name": name,
                    "candidate_data": candidate,
                })

            processed_elements = set()

            for scroll_step in range(30):
                print(f"[스크린샷] 실시간 탐색 단계 {scroll_step + 1}/30")

                for frame in page.frames:
                    try:
                        for cand in prepared_candidates:
                            if not cand["price_str"]:
                                continue

                            # 가격 텍스트 기반 Locator 추출
                            price_locators = frame.locator(f"text={cand['price_str']}").all()

                            for price_loc in price_locators:
                                try:
                                    if not price_loc.is_visible():
                                        continue

                                    # 상위 카드 요소 탐색
                                    card_loc = price_loc.locator("xpath=ancestor::*[self::li or self::a or contains(@class, 'item') or contains(@class, 'card') or contains(@class, 'Product') or contains(@class, 'unit') or contains(@class, 'landing')][1]")

                                    if card_loc.count() == 0:
                                        card_loc = price_loc.locator("xpath=ancestor::div[contains(@style, 'width') or contains(@class, 'div')][2]")

                                    if card_loc.count() == 0:
                                        continue

                                    text = card_loc.inner_text()
                                    norm_text = _normalize_text(text)

                                    if norm_text in processed_elements:
                                        continue

                                    name_matched = cand["norm_name_fragment"] and (cand["norm_name_fragment"] in norm_text)
                                    card_pid = extract_product_id(text)
                                    pid_matched = bool(cand["target_pid"] and card_pid and cand["target_pid"] in text)

                                    if name_matched or pid_matched:
                                        match_reason = "상품 ID" if pid_matched else "가격 + 키워드"
                                        print(f"[스크린샷] ★ 매칭 성공! ({match_reason}) -> 키워드: '{cand['orig_name_fragment']}' / 가격: {cand['price_str']}원")

                                        card_loc.scroll_into_view_if_needed()
                                        page.wait_for_timeout(1000)

                                        card_loc.screenshot(path=output_path)

                                        full_name, discount_rate = _parse_card_text(text, cand["fallback_name"])
                                        print(f"[스크린샷] 캡처 완료 -> {output_path} (상품명: {full_name}, 할인율: {discount_rate}%)")
                                        return cand["candidate_data"], full_name, discount_rate

                                    processed_elements.add(norm_text)

                                except Exception:
                                    continue
                    except Exception:
                        continue

                page.mouse.wheel(0, 650)
                page.wait_for_timeout(1000)

            print("[스크린샷] 탐색 실패 -> 진단용 이미지 'debug_page.png' 저장 중...")
            page.screenshot(path="debug_page.png", full_page=True)
            return None, None, None

        except Exception as e:
            print(f"[스크린샷] 실행 오류: {e}")
            return None, None, None
        finally:
            browser.close()


def capture_goldbox_card_screenshot(target_price: int, target_name: str, output_path: str):
    matched, full_name, discount_rate = find_and_capture_first_match(
        [(target_price, target_name, None)], output_path
    )
    return matched is not None, full_name or target_name, discount_rate
