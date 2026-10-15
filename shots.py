from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_page(viewport={"width":1400,"height":1000},timezone_id="America/New_York")
    for n in ["index","schedule","news"]:
        pg.goto(f"http://localhost:8765/{n}.html"); pg.wait_for_timeout(1200)
        pg.screenshot(path=f"screenshots/{n}.png",full_page=True)
    b.close()
