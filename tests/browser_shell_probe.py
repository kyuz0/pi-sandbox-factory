import os
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, proxy={'server':os.environ['HTTPS_PROXY']} if os.environ.get('HTTPS_PROXY') else None)
    page = browser.new_page()
    response = page.goto('http://local-model.internal:18187/browser-fixture', wait_until='domcontentloaded')
    print(f"HTTP_STATUS {response.status}", flush=True)
    assert response.status == 200
    page.locator('#name').fill('Workshop')
    page.locator('button').click()
    assert page.locator('#result').inner_text() == 'Hello Workshop'
    page.screenshot(path='/workspace/python-browser.png')
    print('PLAYWRIGHT_INTERACTION_OK')
    browser.close()
