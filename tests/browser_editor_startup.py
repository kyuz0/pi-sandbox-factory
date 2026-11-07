"""Check that a fresh browser editor loads Pendant without selecting its tab."""
import argparse
import time
from playwright.sync_api import sync_playwright


def check(url, screenshot):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={'width': 1440, 'height': 1000})
            page.goto(url)
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                for frame in page.frames:
                    if '/webview/' not in frame.url:
                        continue
                    composer = frame.locator('textarea')
                    if composer.count() and composer.first.is_visible():
                        page.wait_for_timeout(1000)  # Let the webview's opening animation settle.
                        composer.first.fill('Browser keyboard fixture')
                        assert composer.first.input_value() == 'Browser keyboard fixture'
                        composer.first.fill('')
                        page.screenshot(path=screenshot)
                        print('PASS Pendant composer loaded without clicking its tab; typing works')
                        return
                page.wait_for_timeout(250)
            page.screenshot(path=screenshot)
            raise AssertionError('Pendant composer did not appear within 60 seconds')
        finally:
            browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url', help='URL of a fresh disposable browser editor, including its folder query')
    parser.add_argument('--screenshot', required=True)
    args = parser.parse_args()
    check(args.url, args.screenshot)
