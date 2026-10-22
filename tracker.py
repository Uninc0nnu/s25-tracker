import html
import os
import re
import sys
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


def send_telegram(message: str) -> bool:
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
        return True
    except requests.RequestException as err:
        print(f"Erreur Telegram : {err}")
        return False


def check_updates() -> None:
    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        res = session.get(URL, timeout=15)
        res.raise_for_status()
    except requests.RequestException as err:
        print(f"Erreur doc.html : {err}")
        sys.exit(1)

    fra_match = re.search(r'([^\s"\'=]+fra\.html)', res.text)
    if not fra_match:
        print("Erreur : fra.html introuvable.")
        sys.exit(1)

    fra_url = urljoin(URL, fra_match.group(1))

    try:
        res_fra = session.get(fra_url, headers={"Referer": URL}, timeout=15)
        res_fra.raise_for_status()
        res_fra.encoding = "utf-8"
    except requests.RequestException as err:
        print(f"Erreur {fra_url} : {err}")
        sys.exit(1)

    page_html = res_fra.text
    soup = BeautifulSoup(page_html, "html.parser")

    # 1. Extraction stricte d'un numéro de build Samsung (13 caractères : S931B + 8 alphanumériques)
    build_match = re.search(r"S931B[A-Z0-9]{8}", page_html)
    if not build_match:
        print("Erreur : Aucun numéro de build valide trouvé sur la page.")
        sys.exit(1)
    current_build = build_match.group(0)

    # 2. Isoler uniquement la première mise à jour (section courante)
    text_full = soup.get_text("\n")
    sections = re.split(r"(?:Num[eé]ro de version\s*:\s*)", text_full)
    current_section = ""
    for sec in sections:
        if current_build in sec:
            current_section = sec
            break

    # 3. Extraction du patch de sécurité et de la date (dans la section courante en priorité)
    search_zone = current_section if current_section else page_html
    security_patch = "Non précisé"
    release_date = ""

    patch_match = re.search(
        r"(?:Niveau du correctif de s[eé]curit[eé]|Correctif de s[eé]curit[eé])\s*:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})",
        search_zone,
        re.IGNORECASE,
    )
    if patch_match:
        security_patch = patch_match.group(1).strip()

    date_match = re.search(
        r"(?:Date de sortie)\s*:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})",
        search_zone,
        re.IGNORECASE,
    )
    if date_match:
        release_date = date_match.group(1).strip()

    # 4. Nettoyage ciblé du changelog
    changelog_lines = []
    if current_section:
        raw_lines = [l.strip() for l in current_section.splitlines() if l.strip()]
        for line in raw_lines:
            low = line.lower()
            if any(
                low.startswith(k)
                for k in [
                    current_build.lower(),
                    "version android",
                    "date de sortie",
                    "niveau du correctif",
                    "correctif de s",
                    "ces modifications peuvent varier",
                ]
            ):
                continue
            changelog_lines.append(line)

    changelog = "\n".join(changelog_lines).strip()
    if not changelog:
        changelog = "Consultez le lien pour plus de détails."

    # Troncature AVANT échappement HTML pour ne jamais couper une entité (&amp;, etc.)
    if len(changelog) > 1500:
        changelog = changelog[:1500] + "\n[...]"
    changelog = html.escape(changelog)

    # 5. Comparaison d'état
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
        date_str = f" ({release_date})" if release_date else ""
        message = (
            f"🚀 <b>Nouvelle mise à jour Galaxy S25 ({CSC})</b>\n\n"
            f"📦 <b>Version :</b> <code>{current_build}</code>{date_str}\n"
            f"🛡️ <b>Patch sécurité :</b> {html.escape(security_patch)}\n\n"
            f"<b>Changelog :</b>\n{changelog}\n\n"
            f"🔗 <a href='{URL}'>Voir sur doc.samsungmobile</a>"
        )
        # On ne met à jour last_build.txt QUE si Telegram a bien reçu le message
        if send_telegram(message):
            with open(LAST_BUILD_FILE, "w", encoding="utf-8") as f:
                f.write(current_build)
            print(f"Notification envoyée : {current_build}")
        else:
            sys.exit(1)
    else:
        print(f"À jour ({current_build}).")


if __name__ == "__main__":
    check_updates()
