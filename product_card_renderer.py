# -*- coding: utf-8 -*-
"""
상품 정보를 쿠팡 카드 스타일 홍보 이미지로 렌더링한다.

레이아웃 (좌: 상품사진 / 우: 정보):
  상품명 (형광펜 하이라이트)
  쿠폰할인 + 정가(취소선)
  [할인율 배지] 판매가
  로켓배송 라벨
  남은 시간

골드박스 페이지 캡처가 실패했을 때의 대체 경로로 쓰인다.
Playwright로 HTML을 렌더해 스크린샷을 뜨므로 별도 이미지 편집 패키지가 없다.
"""
import base64
import html
import mimetypes
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

CARD_WIDTH = 1000
CARD_HEIGHT = 470


def _image_source(path: str = None, url: str = None) -> str:
    """로컬 이미지를 우선 사용하고, 없으면 원본 URL을 사용한다."""
    if path and os.path.exists(path):
        file_path = Path(path)
        mime = mimetypes.guess_type(file_path.name)[0] or "image/png"
        encoded = base64.b64encode(file_path.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{encoded}"
    return url or ""


def _money(value) -> str:
    try:
        return f"{int(value):,}원"
    except (TypeError, ValueError):
        return ""


def _safe(value) -> str:
    return html.escape(str(value or ""), quote=True)


def _proxy_options() -> dict:
    proxy = (
        os.environ.get("BROWSER_PROXY")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("HTTP_PROXY")
    )
    return {"server": proxy} if proxy else {}


def _build_html(product: dict) -> str:
    sale_price = product.get("price")
    original_price = product.get("original_price")
    discount_rate = product.get("discount_rate")
    coupon_required = product.get("coupon_required")
    remaining = product.get("remaining_time") or ""
    image_src = _image_source(product.get("product_image_path"), product.get("image_url"))

    # 할인율 배지
    discount_html = ""
    try:
        if discount_rate is not None and float(discount_rate) > 0:
            discount_html = (
                f'<span class="rate">{float(discount_rate):.0f}<small>%</small></span>'
            )
    except (TypeError, ValueError):
        pass

    # 정가 줄. 쿠폰 조건부면 '쿠폰할인' 라벨을 붙인다.
    original_html = ""
    if original_price and sale_price and original_price > sale_price:
        label = '<span class="coupon">쿠폰할인</span>' if coupon_required else ""
        original_html = (
            f'<div class="origin">{label}'
            f'<span class="strike">{_money(original_price)}</span></div>'
        )

    rocket_html = ""
    if product.get("is_rocket"):
        rocket_html = (
            '<div class="rocket"><span class="icon">🚀</span>'
            '<span class="label">로켓배송</span>'
            '<span class="sub">내일 도착</span></div>'
        )

    timer_html = ""
    if remaining:
        timer_html = f'<div class="timer">{_safe(remaining)} 남음</div>'

    if image_src:
        image_html = f'<img src="{html.escape(image_src, quote=True)}" alt="상품">'
    else:
        image_html = '<div class="ph">상품 이미지</div>'

    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><style>
  * {{ box-sizing: border-box; margin: 0; }}
  html, body {{ width: {CARD_WIDTH}px; height: {CARD_HEIGHT}px; background: #fff; }}
  body {{
    font-family: "Malgun Gothic", "Noto Sans KR", "Apple SD Gothic Neo", sans-serif;
    color: #212121; -webkit-font-smoothing: antialiased;
  }}
  .card {{
    width: {CARD_WIDTH}px; height: {CARD_HEIGHT}px;
    display: grid; grid-template-columns: 44% 56%;
    gap: 26px; padding: 34px 40px;
    border: 1px solid #ececec; border-radius: 14px; background: #fff;
  }}
  .visual {{ display: flex; align-items: center; justify-content: center; min-width: 0; }}
  .visual img {{ width: 100%; height: 100%; object-fit: contain; }}
  .ph {{ color: #bbb; font-size: 24px; }}
  .info {{
    min-width: 0; display: flex; flex-direction: column;
    justify-content: center; gap: 16px; padding-right: 6px;
  }}
  /* 상품명: 형광펜 하이라이트 */
  .name {{
    display: -webkit-box; overflow: hidden;
    -webkit-box-orient: vertical; -webkit-line-clamp: 2;
    font-size: 38px; font-weight: 700; line-height: 1.34;
    letter-spacing: -1.6px; word-break: keep-all;
    background: linear-gradient(transparent 58%, #fff176 58%);
    align-self: flex-start;
  }}
  .origin {{ display: flex; align-items: center; gap: 12px; }}
  .coupon {{ color: #c62828; font-size: 27px; font-weight: 700; letter-spacing: -1px; }}
  .strike {{
    color: #9e9e9e; font-size: 27px; font-weight: 400;
    text-decoration: line-through; letter-spacing: -1px;
  }}
  .pricing {{ display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }}
  .rate {{
    display: inline-flex; align-items: baseline;
    padding: 7px 15px; border-radius: 7px;
    background: #d32f2f; color: #fff;
    font-size: 44px; font-weight: 900; letter-spacing: -2px;
  }}
  .rate small {{ font-size: 26px; font-weight: 800; margin-left: 2px; }}
  .sale {{ color: #212121; font-size: 52px; font-weight: 900; letter-spacing: -2.5px; }}
  .rocket {{ display: flex; align-items: center; gap: 9px; }}
  .rocket .icon {{ font-size: 27px; }}
  .rocket .label {{ color: #00a862; font-size: 27px; font-weight: 800; letter-spacing: -1.2px; }}
  .rocket .sub {{ color: #424242; font-size: 25px; letter-spacing: -1.2px; }}
  .timer {{
    align-self: flex-start; padding: 9px 18px; border-radius: 8px;
    background: #fdecea; color: #c62828; font-size: 24px;
    font-weight: 700; letter-spacing: -1px;
  }}
</style></head>
<body><main class="card">
  <section class="visual">{image_html}</section>
  <section class="info">
    <div class="name">{_safe(product.get("name"))}</div>
    {original_html}
    <div class="pricing">{discount_html}<span class="sale">{_money(sale_price)}</span></div>
    {rocket_html}
    {timer_html}
  </section>
</main></body></html>"""


def render_product_card(product: dict, output_path: str) -> None:
    """상품 정보를 홍보 카드 이미지로 저장한다."""
    template = _build_html(product)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    with sync_playwright() as playwright:
        launch_options = {"headless": True, "args": ["--no-sandbox"]}
        proxy = _proxy_options()
        if proxy:
            launch_options["proxy"] = proxy

        browser = playwright.chromium.launch(**launch_options)
        page = browser.new_page(
            viewport={"width": CARD_WIDTH, "height": CARD_HEIGHT},
            device_scale_factor=2,
            locale="ko-KR",
        )
        try:
            page.set_content(template, wait_until="load")
            page.wait_for_timeout(700)
            page.screenshot(path=output_path, full_page=False)
        finally:
            browser.close()
