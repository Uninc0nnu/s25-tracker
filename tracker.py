from datetime import datetime
import html
import os
import re
from urllib.parse import urljoin
from zoneinfo import ZoneInfo
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

MODEL = "SM-S931B"
CSC = "EUX"
URL = f"https://doc.samsungmobile.com/{MODEL}/{CSC}/doc.html"
LAST_BUILD_FILE = "last_build.txt"

# Heure du premier rapport (matin) et seuil à partir duquel l'après-midi peut s'envoyer
MORNING_REPORT_HOUR = 8
AFTERNOON_REPORT_HOUR = 14

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": URL,
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
}


def create_session() -> requests.Session:
    """Crée une session HTTP qui réessaie automatiquement 3 fois en cas d'erreur DNS ou réseau."""
    session = requests.Session()
    session.headers.update(HEADERS)
    retry_strategy = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def send_telegram(session: requests.Session, message: str) -> bool:
    api_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        res = session.post(api_url, json=payload, timeout=15)
        res.raise_for_status()
        return True
    except requests.RequestException as err:
        print(f"Erreur Telegram : {err}")
        return False


def save_state(build: str, report_tag: str) -> None:
    """Enregistre le build et le dernier créneau de rapport envoyé (ex: YYYY-MM-DD_morning ou YYYY-MM-DD_afternoon)"""
    with open(LAST_BUILD_FILE, "w", encoding="utf-8") as f:
        f.write(f"{build}|{report_tag}\n")


def check_updates() -> None:
    session = create_session()

    try:
        res = session.get(URL, timeout=15)
        res.raise_for_status()
    except requests.RequestException as err:
        print(f"Serveur Samsung temporairement injoignable (doc.html) : {err}")
        return

    fra_match = re.search(r'([^\s"\'=]+fra\.html)', res.text)
    if not fra_match:
        print("Erreur : fra.html introuvable.")
        return

    fra_url = urljoin(URL, fra_match.group(1))

    try:
        res_fra = session.get(fra_url, headers={"Referer": URL}, timeout=15)
        res_fra.raise_for_status()
        res_fra.encoding = "utf-8"
    except requests.RequestException as err:
        print(f"Serveur Samsung temporairement injoignable ({fra_url}) : {err}")
        return

    page_html = res_fra.text
    soup = BeautifulSoup(page_html, "html.parser")

    # 1. Extraction stricte du numéro de build le plus récent (13 caractères)
    build_match = re.search(r"S931B[A-Z0-9]{8}", page_html)
    if not build_match:
        print("Erreur : Aucun numéro de build valide trouvé sur la page.")
        return
    current_build = build_match.group(0)

    # 2. Isoler uniquement la première mise à jour (section courante)
    text_full = soup.get_text("\n")
    sections = re.split(r"(?:Num[eé]ro de version\s*:\s*)", text_full)
    current_section = ""
    for sec in sections:
        if current_build in sec:
            current_section = sec
            break

    # 3. Extraction du patch de sécurité et de la date dans la section courante
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

    if len(changelog) > 1500:
        changelog = changelog[:1500] + "\n[...]"
    changelog = html.escape(changelog)

    # 5. Gestion des états et des dates (Europe/Paris)
    now_paris = datetime.now(ZoneInfo("Europe/Paris"))
    today_str = now_paris.strftime("%Y-%m-%d")
    current_hour = now_paris.hour

    last_build = ""
    last_report_tag = ""
    if os.path.exists(LAST_BUILD_FILE):
        with open(LAST_BUILD_FILE, "r", encoding="utf-8") as f:
            raw_state = f.read().strip()
            if "|" in raw_state:
                last_build, last_report_tag = raw_state.split("|", 1)
            else:
                last_build = raw_state

    if not last_build:
        save_state(current_build, f"{today_str}_none")
        print(f"Initialisation : {current_build} ({today_str})")
        return

    date_str = f" ({release_date})" if release_date else ""

    # Cas A : Nouvelle mise à jour détectée -> Alerte immédiate prioritaire
    if current_build != last_build:
        message = (
            f"🚀 <b>Nouvelle mise à jour Galaxy S25 ({CSC})</b>\n\n"
            f"📦 <b>Version :</b> <code>{current_build}</code>{date_str}\n"
            f"🛡️ <b>Patch sécurité :</b> {html.escape(security_patch)}\n\n"
            f"<b>Changelog :</b>\n{changelog}\n\n"
            f"🔗 <a href='{URL}'>Voir sur doc.samsungmobile</a>"
        )
        if send_telegram(session, message):
            save_state(current_build, f"{today_str}_update")
            print(f"Notification de mise à jour envoyée : {current_build}")

    # Cas B1 : Rapport du matin (à partir de 8h00, si pas encore fait aujourd'hui)
    elif current_hour >= MORNING_REPORT_HOUR and current_hour < AFTERNOON_REPORT_HOUR and last_report_tag != f"{today_str}_morning":
        message = (
            f"✅ <b>Bilan matinal Galaxy S25 ({CSC})</b>\n\n"
            f"Aucune nouvelle mise à jour pour l'instant.\n"
            f"📦 <b>Version actuelle :</b> <code>{current_build}</code>{date_str}\n"
            f"🛡️ <b>Patch sécurité :</b> {html.escape(security_patch)}\n\n"
            f"🔗 <a href='{URL}'>Voir sur doc.samsungmobile</a>"
        )
        if send_telegram(session, message):
            save_state(current_build, f"{today_str}_morning")
            print(f"Bilan matinal envoyé pour le {today_str} ({current_build}).")

    # Cas B2 : Rapport de l'après-midi (à partir de 14h00, si le rapport matinal a été fait mais pas celui de l'après-midi)
    elif current_hour >= AFTERNOON_REPORT_HOUR and last_report_tag != f"{today_str}_afternoon":
        # Si par hasard le cron du matin a été raté, on s'assure de ne pas bloquer l'après-midi
        tag_to_save = f"{today_str}_afternoon"
        message = (
            f"✅ <b>Bilan de l'après-midi Galaxy S25 ({CSC})</b>\n\n"
            f"Le système est stable et à jour.\n"
            f"📦 <b>Version actuelle :</b> <code>{current_build}</code>{date_str}\n"
            f"🛡️ <b>Patch sécurité :</b> {html.escape(security_patch)}\n\n"
            f"🔗 <a href='{URL}'>Voir sur doc.samsungmobile</a>"
        )
        if send_telegram(session, message):
            save_state(current_build, tag_to_save)
            print(f"Bilan de l'après-midi envoyé pour le {today_str} ({current_build}).")

    # Cas C : Rien à envoyer pour l'instant (ex: avant 8h00 ou créneau déjà rempli)
    else:
        print(f"À jour ({current_build}). Dernier tag enregistré : {last_report_tag or 'aucun'}.")


if __name__ == "__main__":
    check_updates()
