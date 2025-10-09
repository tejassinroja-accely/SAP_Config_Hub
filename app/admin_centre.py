# admin_centre_keep_open.py
import asyncio
import time
import traceback
import os
from app.sap_config_hub import SapConfigHub

# Config
KEEP_BROWSER_OPEN = True         # <--- If True, do NOT kill the browser session at the end
SLEEP_AFTER_LANDING = 20         # seconds to sleep after landing so you can inspect the browser
COMPANY_ID = "SFCPART001662"
USERNAME = "sfadmin"
PASSWORD = "Part@dc99"

# Try typical env toggles to reduce heavy DOM/LLM processing (optional)
os.environ.setdefault("USE_DOM_AI", "0")
os.environ.setdefault("DISABLE_LLM_DOM", "1")
os.environ.setdefault("BROWSER_USE_DISABLE_DOM_AI", "1")

config = SapConfigHub()

async def safe_call(coro, timeout=20):
    try:
        res = await asyncio.wait_for(coro, timeout=timeout)
        return res, None
    except Exception as e:
        return None, e

async def try_eval(browser_session, js, timeout=3):
    try:
        res = await asyncio.wait_for(browser_session.evaluate(js), timeout=timeout)
        return res, None
    except Exception as e:
        return None, e

async def wait_for_navigation_or_ready(browser_session, timeout=25, poll_interval=0.5):
    """Poll location.href and document.readyState until readyState == 'complete' or timeout."""
    start = time.time()
    last_url = None
    last_ready = None
    while time.time() - start < timeout:
        url, err1 = await try_eval(browser_session, "() => location.href", timeout=2)
        ready, err2 = await try_eval(browser_session, "() => document.readyState", timeout=2)

        # if both evaluations failed, return last-knowns so caller can fallback
        if err1 and err2:
            return last_url, last_ready

        if url is None:
            url = last_url
        if ready is None:
            ready = last_ready

        if url != last_url or ready != last_ready:
            print(f"[nav-poll] url={url} readyState={ready}")
            last_url, last_ready = url, ready

            if ready == "complete":
                return url, ready

        await asyncio.sleep(poll_interval)

    return last_url, last_ready

async def get_page_index_with_retry(retries=4, per_try_timeout=6, delay_between=0.6):
    last_exc = None
    for i in range(retries):
        try:
            print(f"[page-index] attempt {i+1}/{retries}")
            res = await asyncio.wait_for(config.current_page_index(), timeout=per_try_timeout)
            return res
        except asyncio.TimeoutError as te:
            print(f"[page-index] timed out attempt {i+1}/{retries}")
            last_exc = te
        except Exception as e:
            print(f"[page-index] raised attempt {i+1}/{retries} -> {e!r}")
            last_exc = e
        await asyncio.sleep(delay_between)
    raise RuntimeError("current_page_index() failed after retries") from last_exc

async def main():
    browser_session = await config.get_browser_session()
    try:
        await browser_session.start()
        print("➡️ started browser_session")

        # Navigate to SuccessFactors
        _, err = await safe_call(config.go_to_url(url="https://salesdemo.successfactors.eu/", new_tab=False), timeout=30)
        if err:
            print("go_to_url failed:", err)

        await asyncio.sleep(1)
        # initial snapshot (best-effort)
        try:
            snap = await get_page_index_with_retry(retries=2, per_try_timeout=4, delay_between=0.3)
            print("initial snapshot (short):\n", snap)
        except Exception as e:
            print("initial snapshot failed:", e)

        # Input company id and click continue (single click only)
        _, err = await safe_call(config.input_text(index=1, text=COMPANY_ID, clear_existing=False), timeout=8)
        if err:
            print("input_text company id failed:", err)

        _, err = await safe_call(config.click_element_by_index(index=4, while_holding_ctrl=False), timeout=10)
        if err:
            print("click continue failed:", err)
        else:
            print("Clicked Continue (company id) — waiting for navigation / readyState")

        # Wait for navigation / page load (SAML or redirect could be involved)
        url, ready = await wait_for_navigation_or_ready(browser_session, timeout=30)
        print("after continue nav poll ->", url, ready)

        # Take a more robust snapshot after landing (with retries)
        try:
            after_snap = await get_page_index_with_retry(retries=5, per_try_timeout=6, delay_between=0.6)
            print("after-continue page_index snapshot:\n", after_snap)
        except Exception as e:
            print("Failed to get page_index after continue:", e)

        # If landing loaded the login form (usual flow), fill credentials and submit
        # (If SAML / external auth landed directly to homepage, these indices may be absent; safe_call handles timeouts)
        _, err = await safe_call(config.input_text(index=1, text=USERNAME, clear_existing=False), timeout=8)
        if err:
            print("username input failed (maybe already authenticated or different page):", err)
        _, err = await safe_call(config.input_text(index=2, text=PASSWORD, clear_existing=False), timeout=8)
        if err:
            print("password input failed (maybe already authenticated or different page):", err)

        # Click login once (do not double-click)
        _, err = await safe_call(config.click_element_by_index(index=10, while_holding_ctrl=False), timeout=12)
        if err:
            print("click login failed (may be SAML/new tab):", err)
        else:
            print("Clicked login (submit) — waiting for landing")

        # Wait for final navigation / homepage ready
        url, ready = await wait_for_navigation_or_ready(browser_session, timeout=30)
        print("post-login nav poll ->", url, ready)

        # Try cheap fallback evaluate to get URL/title quickly (avoids heavy DOM snapshot)
        u, ue = await try_eval(browser_session, "() => location.href", timeout=2)
        t, te = await try_eval(browser_session, "() => document.title", timeout=2)
        print("evaluate url/title:", u, t, "errs:", ue, te)

        # If login opened a new tab (SAML), attempt a best-effort listing/switch (some frameworks use config.switch_tab)
        if hasattr(config, "switch_tab"):
            try:
                # try switching to the last tab
                print("Attempting to switch to last tab (best-effort)")
                # many switch_tab APIs accept an index; adjust if your API differs
                await safe_call(config.switch_tab(-1), timeout=5)
            except Exception as e:
                print("switch_tab attempt failed or unsupported:", e)

        # Final robust snapshot of the home page (if present)
        try:
            final_snap = await get_page_index_with_retry(retries=6, per_try_timeout=6, delay_between=0.7)
            print("final page_index snapshot (home):\n", final_snap)
        except Exception as e:
            print("Could not get final page_index snapshot:", e)

        # Also produce a lightweight list of visible elements (first 50) via evaluate — cheaper than full DOM+LLM processing
        elems_js = """
            () => Array.from(document.querySelectorAll('body *'))
                      .slice(0,50)
                      .map(e => ({
                          tag: e.tagName,
                          id: e.id || null,
                          class: e.className || null,
                          text: (e.innerText || '').trim().slice(0,120)
                      }))
        """
        elems, elems_err = await try_eval(browser_session, elems_js, timeout=4)
        if elems_err:
            print("element list eval failed:", elems_err)
        else:
            print("page elements (first 50):")
            for i, el in enumerate(elems):
                print(f"  [{i}] {el}")

        # Now sleep so user can inspect the live browser before optionally killing
        if KEEP_BROWSER_OPEN:
            print(f"\nKeeping browser open. Sleeping for {SLEEP_AFTER_LANDING} seconds so you can inspect the page.")
            print("After the sleep the script will exit WITHOUT killing the browser session (you can re-attach if your framework supports it).")
            try:
                await asyncio.sleep(SLEEP_AFTER_LANDING)
            except asyncio.CancelledError:
                pass
            print("Sleep finished — leaving browser session running (not killed).")
        else:
            # short wait then cleanup
            await asyncio.sleep(2)
            print("KEEP_BROWSER_OPEN=False -> will cleanup and kill browser session below.")

    except Exception as exc:
        print("Unhandled exception in main:", exc)
        traceback.print_exc()
    finally:
        if KEEP_BROWSER_OPEN:
            print("KEEP_BROWSER_OPEN=True: skipping browser_session.kill() — leaving session running.")
        else:
            try:
                print("Cleaning up: killing browser session")
                await browser_session.kill()
            except Exception as kill_err:
                print("Error while killing browser session:", repr(kill_err))

if __name__ == "__main__":
    asyncio.run(main())
