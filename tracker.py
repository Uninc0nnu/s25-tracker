import os
import re
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

MODEL = "SM-S931B"
CSC = "EUX"
URL = f"https://doc.samsungmobile.com/{MODEL}/{CSC}/doc.html"
LAST_BUILD_FILE = "last_build.txt"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": URL,
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
}


def send_telegram(message: str) -> None:
    api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        res = requests.post(api_url, json=payload, timeout=10)
        res.raise_for_status()
    except requests.RequestException as err:
        print(f"Erreur Telegram : {err}")


def check_updates() -> None:
    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        res = session.get(URL, timeout=15)
        res.raise_for_status()
    except requests.RequestException as err:
        print(f"Erreur doc.html : {err}")
        return

    fra_match = re.search(r'([^\s"\'=]+fra\.html)', res.text)
    if not fra_match:
        print("Erreur : fra.html introuvable.")
        return

    fra_url = urljoin(URL, fra_match.group(1))

    try:
        res_fra = session.get(fra_url, headers={"Referer": URL}, timeout=15)
        res_fra.raise_for_status()
    except requests.RequestException as err:
        print(f"Erreur {fra_url} : {err}")
        return

    soup = BeautifulSoup(res_fra.text, "html.parser")
    build_match = re.search(r"S931B[A-Z0-9]+", res_fra.text)
    current_build = build_match.group(0) if build_match else "Inconnue"

    security_patch = "Non précisé"
    changelog = "Consultez le lien pour plus de détails."

    containers = soup.find_all("div", class_="container")
    if containers:
        first_box = containers[0]
        for tag in first_box.find_all(["p", "span", "li"]):
            txt = tag.get_text(strip=True)
            if "Correctif" in txt or "sécurité" in txt:
                security_patch = txt
                break

        c_body = first_box.find("div", class_="c-body")
        if c_body:
            changelog = c_body.get_text("\n", strip=True)

    if len(changelog) > 2000:
        changelog = changelog[:2000] + "\n[...]"

    last_build = ""
    if os.path.exists(LAST_BUILD_FILE):
        with open(LAST_BUILD_FILE, "r", encoding="utf-8") as f:
            last_build = f.read().strip()

    if not last_build:
        with open(LAST_BUILD_FILE, "w", encoding="utf-8") as f:
            f.write(current_build)
        print(f"Initialisation : {current_build}")
        return

    if current_build != last_build:
        message = (
            f"🚀 <b>Nouvelle mise à jour Galaxy S25 ({CSC})</b>\n\n"
            f"📦 <b>Version :</b> <code>{current_build}</code>\n"
            f"🛡️ <b>Détails :</b> {security_patch}\n\n"
            f"<b>Changelog :</b>\n{changelog}\n\n"
            f"🔗 <a href='{URL}'>Voir sur doc.samsungmobile</a>"
        )
        send_telegram(message)

        with open(LAST_BUILD_FILE, "w", encoding="utf-8") as f:
            f.write(current_build)
        print(f"Notification envoyée : {current_build}")
    else:
        print(f"À jour ({current_build}).")


if __name__ == "__main__":
    check_updates()
