"""Record the README demo with Playwright: one video per browser context, a magenta
marker frame before each scene, and scenes.json with each scene's length.
encode.py cuts the scenes at the markers and writes MP4 and GIF.

Usage: python record.py <work_dir>   (expects <work_dir>/demo_state.json from setup.py)
"""

import json
import shutil
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

SP = Path(sys.argv[1])
OUT = SP / "rec_out"
OUT.mkdir(parents=True, exist_ok=True)
for d in ("v_anon", "v_app"):
    shutil.rmtree(OUT / d, ignore_errors=True)
W, H = 1440, 900
WEB = "http://localhost:3000"

# A visible cursor and a caption chip, drawn in the page so they are crisp in the video.
OVERLAY = """
(() => {
  if (window.__demoOverlay) return; window.__demoOverlay = true;
  const add = () => {
    const c = document.createElement('div');
    c.id = '__cursor';
    c.style.cssText = 'position:fixed;left:-40px;top:-40px;width:22px;height:22px;z-index:2147483647;pointer-events:none;transition:transform .08s';
    c.innerHTML = '<svg width="22" height="22" viewBox="0 0 24 24"><path d="M4 2l16 9.5-7 1.6-3.6 6.9z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    document.documentElement.appendChild(c);
    addEventListener('mousemove', e => { c.style.left = e.clientX - 3 + 'px'; c.style.top = e.clientY - 2 + 'px'; }, true);
    addEventListener('dragover', e => { c.style.left = e.clientX - 3 + 'px'; c.style.top = e.clientY - 2 + 'px'; }, true);
    addEventListener('mousedown', () => c.style.transform = 'scale(.82)', true);
    addEventListener('mouseup', () => c.style.transform = '', true);
    const cap = document.createElement('div');
    cap.id = '__caption';
    cap.style.cssText = 'position:fixed;left:50%;bottom:34px;transform:translate(-50%,12px);opacity:0;z-index:2147483646;pointer-events:none;'
      + 'background:#0f1f17;color:#f4f7f2;font:600 19px/1.3 Inter,system-ui,sans-serif;letter-spacing:-.01em;padding:13px 22px;border-radius:999px;'
      + 'box-shadow:0 10px 30px rgba(0,0,0,.25);transition:opacity .35s ease,transform .35s ease;white-space:nowrap';
    document.documentElement.appendChild(cap);
    window.__caption = (t) => { cap.innerHTML = t; cap.style.opacity = 1; cap.style.transform = 'translate(-50%,0)'; };
  };
  if (document.readyState === 'loading') addEventListener('DOMContentLoaded', add); else add();
})();
"""

VIDEO = {}
scenes: list[dict] = []


T0 = {}


def now(page):
    return time.time() - T0[id(page)]


def hold(page, seconds):
    end = time.time() + seconds
    while time.time() < end:
        page.wait_for_timeout(40)


def glide(page, x, y, steps=18):
    page.mouse.move(x, y, steps=steps)


MARK = """() => { const d = document.createElement('div'); d.id='__mark';
  d.style.cssText='position:fixed;inset:0;background:#ff00ff;z-index:2147483647';
  document.documentElement.appendChild(d); }"""


def scene(page, fn):
    page.wait_for_timeout(250)
    # A magenta frame the encoder finds in the video: frame-accurate scene starts.
    page.evaluate(MARK)
    page.wait_for_timeout(200)
    page.evaluate("document.getElementById('__mark').remove()")
    page.wait_for_timeout(60)
    start = now(page)
    fn()
    scenes.append({"video": VIDEO[id(page)], "start": start, "end": now(page)})


with sync_playwright() as p:
    b = p.chromium.launch(args=["--force-device-scale-factor=1"])

    # Signed-out landing page.
    anon = b.new_context(
        viewport={"width": W, "height": H},
        color_scheme="light",
        record_video_dir=str(OUT / "v_anon"),
        record_video_size={"width": W, "height": H},
    )
    anon.add_init_script(OVERLAY)
    page = anon.new_page()
    T0[id(page)] = time.time()
    VIDEO[id(page)] = "anon"
    page.goto(WEB + "/", wait_until="networkidle")
    page.wait_for_timeout(1200)
    page.mouse.move(700, 600)

    def landing():
        page.evaluate("window.__caption('Fresh tech roles from company job boards, every day')")
        glide(page, 980, 430, 20)
        hold(page, 1.4)

    scene(page, landing)
    anon_page = page
    anon.close()
    videos = {"anon": anon_page.video.path()}

    # Signed-in demo user.
    ctx = b.new_context(
        viewport={"width": W, "height": H},
        color_scheme="light",
        storage_state=str(SP / "demo_state.json"),
        extra_http_headers={"X-Rolecall": "1"},
        record_video_dir=str(OUT / "v_app"),
        record_video_size={"width": W, "height": H},
    )
    ctx.add_init_script(OVERLAY)
    # Fresh tracker for every take.
    apps = ctx.request.get(WEB + "/api/applications").json()
    for a in apps if isinstance(apps, list) else apps.get("items", []):
        ctx.request.delete(f"{WEB}/api/applications/{a['id']}")
    page = ctx.new_page()
    T0[id(page)] = time.time()
    VIDEO[id(page)] = "app"

    def warm(path, ready):
        page.goto(WEB + path, wait_until="networkidle")
        page.wait_for_selector(ready, timeout=90_000)
        page.wait_for_timeout(700)
        page.mouse.move(W - 200, H - 200)

    warm("/feed", '[aria-label*=" at "]')

    def feed():
        page.evaluate(
            "window.__caption('Ranked against <b>your</b> resume, with the reason for every match')"
        )
        glide(page, 470, 340, 12)
        hold(page, 0.5)
        save = page.get_by_role("button", name="Save").first
        box = save.bounding_box()
        glide(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, 20)
        page.mouse.down()
        page.mouse.up()
        hold(page, 1.1)

    scene(page, feed)

    warm("/search", "input")

    QUERY = "RAG intern Bengaluru"
    ctx.request.post(
        WEB + "/api/search",
        data={"q": QUERY, "filters": {}, "limit": 20, "offset": 0},
        timeout=120_000,
    )  # warm caches

    def search_type():
        page.evaluate(
            "window.__caption('Plain-language search: keyword and semantic, fused and reranked')"
        )
        box = page.locator("input").first.bounding_box()
        glide(page, box["x"] + 260, box["y"] + box["height"] / 2, 10)
        page.mouse.down()
        page.mouse.up()
        page.locator("input").first.click()
        page.keyboard.type(QUERY, delay=28)
        page.keyboard.press("Enter")

    scene(page, search_type)
    page.wait_for_selector('[aria-label*=" at "]', timeout=60_000)  # jump-cut over the wait
    page.wait_for_timeout(400)

    def search_results():
        glide(page, 640, 470, 12)
        hold(page, 1.2)

    scene(page, search_results)

    warm("/tracker", "li[draggable]")

    def tracker():
        page.evaluate("window.__caption('Saved, applied, OA, interview, offer: drag it along')")
        card = page.locator("li[draggable]").first
        target = page.locator('section[aria-label="Applied"]')
        cb, tb = card.bounding_box(), target.bounding_box()
        sx, sy = cb["width"] - 14, cb["height"] - 12  # blank corner, not the title link
        glide(page, cb["x"] + sx, cb["y"] + sy, 12)
        hold(page, 0.15)
        card.drag_to(
            target,
            source_position={"x": sx, "y": sy},
            target_position={"x": tb["width"] / 2, "y": 120},
        )
        glide(page, tb["x"] + tb["width"] / 2, tb["y"] + 125, 4)
        hold(page, 1.0)

    scene(page, tracker)
    print("applied column:", page.locator('section[aria-label="Applied"] li').count())

    warm("/evals", "tbody tr")

    def evals():
        page.evaluate("window.__caption('Measured, not guessed: blind-judged evals, published')")
        for _ in range(12):
            page.mouse.wheel(0, 40)
            page.wait_for_timeout(24)
        glide(page, 880, 560, 10)
        hold(page, 1.3)

    scene(page, evals)
    page.wait_for_timeout(300)
    app_page = page
    ctx.close()
    videos["app"] = app_page.video.path()
    b.close()

(OUT / "scenes.json").write_text(
    json.dumps({"videos": {k: str(v) for k, v in videos.items()}, "scenes": scenes}, indent=1)
)
print([round(s["end"] - s["start"], 2) for s in scenes])
