import asyncio
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime

from playwright.async_api import async_playwright

# ── Config ──────────────────────────────────────────────────────────────────
PHONE = os.environ["WHATSAPP_PHONE"]          # e.g. +521234567890
CALLMEBOT_APIKEY = os.environ["CALLMEBOT_APIKEY"]
POLL_SECONDS = int(os.environ.get("POLL_SECONDS", "1800"))  # default 30 min
URL = "https://labs.scale.com/leaderboard/humanitys_last_exam"

# Match any variant: claude-opus-4-8, claude opus 4.8, with or without date suffix
TARGET_RE = re.compile(r"claude[-\s]opus[-\s]4[.\-]8", re.IGNORECASE)

SCORE_RE = re.compile(r"(\d+\.\d+±\d+\.\d+)")
CALIB_RE = re.compile(r"Calib Err:\s*(\d+)")

# JS to run inside the browser page — extracts all leaderboard rows
EXTRACT_JS = """() => {
    const SCORE_RE = /(\\d+\\.\\d+±\\d+\\.\\d+)/;
    const CALIB_RE = /Calib Err:\\s*(\\d+)/;

    const rows = [];
    for (const el of document.querySelectorAll('p.text-xs.font-mono')) {
        const name = el.innerText.trim();
        // Skip elements that ARE scores, not names
        if (SCORE_RE.test(name)) continue;
        if (!name) continue;

        // Row container is 3 levels up from the <p>
        const container = el.parentElement
            ?.parentElement
            ?.parentElement
            ?.parentElement;
        const rowText = container ? (container.innerText || '') : '';

        const scoreMatch = rowText.match(SCORE_RE);
        const calibMatch = rowText.match(CALIB_RE);
        rows.push({
            name,
            score: scoreMatch ? scoreMatch[1] : null,
            calib_err: calibMatch ? calibMatch[1] : null,
        });
    }
    return rows;
}"""


# ── WhatsApp ─────────────────────────────────────────────────────────────────
def send_whatsapp(message: str) -> None:
    encoded = urllib.parse.quote(message)
    api_url = (
        f"https://api.callmebot.com/whatsapp.php"
        f"?phone={PHONE}&text={encoded}&apikey={CALLMEBOT_APIKEY}"
    )
    with urllib.request.urlopen(api_url, timeout=30) as resp:
        body = resp.read().decode()
        print(f"  [WA] {body[:120]}")


# ── Scraper ───────────────────────────────────────────────────────────────────
async def fetch_leaderboard() -> list[dict]:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        page = await browser.new_page(
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        )
        await page.goto(URL, wait_until="networkidle", timeout=90_000)
        await page.wait_for_timeout(3_000)  # let JS hydrate
        rows: list[dict] = await page.evaluate(EXTRACT_JS)
        await browser.close()
    return rows


def find_target(rows: list[dict]) -> dict | None:
    for row in rows:
        if TARGET_RE.search(row["name"]):
            return row
    return None


# ── Main loop ─────────────────────────────────────────────────────────────────
async def main() -> None:
    ts = lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts()}] Monitor iniciado. Intervalo: {POLL_SECONDS}s")

    try:
        send_whatsapp(
            f"Monitor HLE iniciado. Buscando Claude Opus 4.8 cada {POLL_SECONDS//60} min."
        )
    except Exception as exc:
        print(f"[{ts()}] Advertencia: no se pudo enviar mensaje inicial: {exc}")

    while True:
        try:
            print(f"[{ts()}] Consultando leaderboard…")
            rows = await fetch_leaderboard()
            print(f"[{ts()}] {len(rows)} modelos encontrados.")

            target = find_target(rows)
            if target:
                score = target["score"] or "N/A"
                calib = target["calib_err"] or "N/A"
                msg = (
                    f"Claude Opus 4.8 aparecio en HLE!\n"
                    f"Score: {score} | Calib Err: {calib}\n"
                    f"{URL}"
                )
                print(f"[{ts()}] ENCONTRADO → {msg}")
                send_whatsapp(msg)
                print(f"[{ts()}] Notificacion enviada. Finalizando.")
                return

            print(f"[{ts()}] Claude Opus 4.8 aun no aparece. Proximo chequeo en {POLL_SECONDS}s.")

        except Exception as exc:
            print(f"[{ts()}] Error: {exc}")

        await asyncio.sleep(POLL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
