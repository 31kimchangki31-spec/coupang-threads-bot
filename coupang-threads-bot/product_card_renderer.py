# -*- coding: utf-8 -*-
"""
골드박스 상품 정보를 Threads용 홍보 카드 이미지로 렌더링한다.

원본 골드박스 카드 전체를 그대로 캡처하지 않고, 상품 이미지와 추출한
텍스트를 1번 예시와 비슷한 고정 레이아웃으로 다시 배치한다.
Playwright만 사용하므로 별도의 이미지 편집 패키지가 필요하지 않다.
"""
import base64
import html
import mimetypes
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


CARD_WIDTH = 960
CARD_HEIGHT = 540


def _image_source(path: str = None, url: str = None) -> str:
    """로컬 캡처 이미지를 우선 사용하고, 없으면 원본 URL을 사용한다."""
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


def _safe_text(value) -> str:
    return html.escape(str(value or ""), quote=True)


def _proxy_options() -> dict:
    """Playwright 브라우저에 선택적으로 프록시를 적용한다."""
    proxy = (
        os.environ.get("BROWSER_PROXY")
        or os.environ.get("COUPANG_PROXY")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("HTTP_PROXY")
    )
    return {"server": proxy} if proxy else {}


def render_product_card(product: dict, output_path: str) -> None:
    """상품 정보를 16:9 홍보 카드 이미지로 저장한다."""
    sale_price = product.get("price")
    original_price = product.get("original_price")
    discount_rate = product.get("discount_rate")
    remaining_time = product.get("remaining_time") or ""
    image_src = _image_source(
        product.get("product_image_path"),
        product.get("image_url"),
    )

    discount_text = ""
    try:
        if discount_rate is not None and float(discount_rate) > 0:
            discount_text = f"{float(discount_rate):.0f}"
    except (TypeError, ValueError):
        pass

    original_html = ""
    if original_price and original_price != sale_price:
        original_html = f'<span class="original">{_money(original_price)}</span>'

    timer_html = ""
    if remaining_time:
        timer_html = (
            f'<div class="timer">{_safe_text(remaining_time)} <span>남음</span></div>'
        )

    if image_src:
        image_html = (
            f'<img id="product-image" src="{html.escape(image_src, quote=True)}" '
            'alt="상품 이미지">'
        )
    else:
        image_html = '<div class="image-placeholder">상품 이미지 없음</div>'

    template = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; }}
  html, body {{
    margin: 0;
    width: {CARD_WIDTH}px;
    height: {CARD_HEIGHT}px;
    background: #fff;
  }}
  body {{
    font-family: "Malgun Gothic", "Noto Sans KR", Arial, sans-serif;
    color: #242424;
  }}
  .card {{
    width: {CARD_WIDTH}px;
    height: {CARD_HEIGHT}px;
    display: grid;
    grid-template-columns: 43% 57%;
    gap: 18px;
    padding: 32px 38px;
    border: 2px solid #e1e1e1;
    border-radius: 12px;
    background: #fff;
    overflow: hidden;
  }}
  .visual {{
    display: flex;
    align-items: center;
    justify-content: center;
    min-width: 0;
    min-height: 0;
  }}
  #product-image {{
    width: 100%;
    height: 100%;
    object-fit: contain;
  }}
  .image-placeholder {{
    color: #888;
    font-size: 22px;
  }}
  .details {{
    min-width: 0;
    display: flex;
    flex-direction: column;
    padding: 8px 0 0 4px;
  }}
  .rocket {{
    display: inline-flex;
    align-items: center;
    width: fit-content;
    margin-bottom: 18px;
    color: #1ca24a;
    font-weight: 800;
    font-size: 27px;
    letter-spacing: -1.5px;
  }}
  .rocket::first-letter {{ color: #20a4e8; }}
  .name {{
    display: -webkit-box;
    overflow: hidden;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    min-height: 84px;
    font-size: 33px;
    line-height: 1.28;
    letter-spacing: -1.8px;
    word-break: keep-all;
  }}
  .discount {{
    position: relative;
    width: 118px;
    height: 102px;
    margin: 12px 0 22px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #fff;
    background: #d91b0b;
    font-size: 44px;
    font-weight: 900;
  }}
  .discount::after {{
    content: "";
    position: absolute;
    bottom: -28px;
    left: 0;
    border-top: 29px solid #d91b0b;
    border-right: 59px solid transparent;
    border-left: 59px solid transparent;
  }}
  .discount small {{
    margin: 17px 0 0 4px;
    font-size: 25px;
  }}
  .prices {{
    display: flex;
    align-items: baseline;
    flex-wrap: wrap;
    gap: 10px;
    margin-top: 2px;
    color: #bd2117;
    font-size: 43px;
    font-weight: 900;
    letter-spacing: -2px;
  }}
  .original {{
    color: #888;
    font-size: 25px;
    font-weight: 400;
    text-decoration: line-through;
    letter-spacing: -1px;
  }}
  .timer {{
    margin-top: auto;
    padding: 11px 14px;
    color: #b44a41;
    background: #fde7e4;
    border-radius: 10px;
    text-align: center;
    font-size: 23px;
  }}
  .timer span {{ margin-left: 3px; }}
</style>
</head>
<body>
  <main class="card">
    <section class="visual">{image_html}</section>
    <section class="details">
      <div class="rocket">🚀 로켓 <strong>내일</strong></div>
      <div class="name">{_safe_text(product.get("name"))}</div>
      <div class="discount">{discount_text or "-"}<small>%</small></div>
      <div class="prices">{_money(sale_price)} {original_html}</div>
      {timer_html}
    </section>
  </main>
</body>
</html>"""

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with sync_playwright() as playwright:
        launch_options = {
            "headless": True,
            "channel": "chromium",
            "args": ["--headless=new", "--no-sandbox"],
        }
        proxy = _proxy_options()
        if proxy:
            launch_options["proxy"] = proxy

        browser = playwright.chromium.launch(**launch_options)
        page = browser.new_page(
            viewport={"width": CARD_WIDTH, "height": CARD_HEIGHT},
            device_scale_factor=1,
            locale="ko-KR",
        )
        try:
            page.set_content(template, wait_until="domcontentloaded")
            page.wait_for_timeout(500)
            page.screenshot(path=output_path, full_page=False)
        finally:
            browser.close()