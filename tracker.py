import html
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

    # 1. Extraction du build
    build_match = re.search(r"S931B[A-Z0-9]+", res_fra.text)
    current_build = build_match.group(0) if build_match else "Inconnue"

    # 2. Extraction du patch de sécurité et de la date
    security_patch = "Non précisé"
    patch_match = re.search(
        r"(?:Correctif de sécurité|Niveau du correctif de sécurité)\s*:\s*([^\r\n<]+)",
        res_fra.text,
        re.IGNORECASE,
    )
    if patch_match:
        security_patch = patch_match.group(1).strip()

    # 3. Extraction du texte de changelog
    changelog = "Consultez le lien pour plus de détails."

    # Cible la section descriptive ou le premier conteneur de mise à jour
    desc_node = soup.find(class_=re.compile(r"desc|c-body|section", re.I))
    if not desc_node:
        containers = soup.find_all("div", class_=re.compile(r"container|item|box", re.I))
        if containers:
            desc_node = containers[0]

    if desc_node:
        # Nettoyage des listes et paragraphes
        lines = [line.strip() for line in desc_node.get_text("\n").splitlines() if line.strip()]
        # Élimination des lignes redondantes d'en-tête (Numéro de version, date, etc.)
        filtered_lines = [
            l for l in lines
            if not any(k in l.lower() for k in ["numéro de version", "correctif de sécurité", "date de publication"])
        ]
        if filtered_lines:
            changelog = "\n".join(filtered_lines)

    # Échappement des balises HTML parasites pour Telegram
    changelog = html.escape(changelog)
    if len(changelog) > 1500:
        changelog = changelog[:1500] + "\n[...]"

    # 4. Comparaison avec la dernière version mémorisée
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
            f"🛡️ <b>Patch sécurité :</b> {html.escape(security_patch)}\n\n"
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
