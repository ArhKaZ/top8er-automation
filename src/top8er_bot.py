#!/usr/bin/env python3
"""POC: génère un visuel Top8er SSBU à partir d'un lien de tournoi start.gg
et d'un fichier de skins de référence. Voir ../SPEC.md pour le détail du flux.
"""
import argparse
import base64
import datetime
import re
import sys
from pathlib import Path

import openpyxl
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.top8er.com/old/ssbu"

FIXED_LCOLOR1 = "#f1c4ee"
FIXED_LCOLOR2 = "#cecece"

ALIASES = {
    "r.o.b": "ROB",
    "rob": "ROB",
    "pac man": "Pac-Man",
    "palu": "Palutena",
    "dadidou": "King Dedede",
    "pyra & mythra": "Pyra and Mythra",  # ordre non précisé dans le xlsx, "Pyra and Mythra" pris par défaut
    "random character": "Random",  # libellé renvoyé par l'API start.gg pour une sélection aléatoire
}


def normalize(text: str) -> str:
    text = str(text).strip().rstrip("*").strip()
    text = re.sub(r"\s+", " ", text)
    return text.casefold()


def normalize_char_name(name: str) -> str:
    name = re.sub(r"\s+", " ", str(name).strip())
    return name


def make_inclusive(text: str) -> str:
    """Remplace "participant(e)s" par "participant.e.s" (écriture inclusive),
    utilisé sur le texte du bas importé automatiquement par Top8er (date/
    ville/nombre de participant.e.s)."""
    return re.sub(r"\b([Pp]articipant)e?s\b", r"\1.e.s", text)


# ---------------------------------------------------------------------------
# Step 1/2: fetch the page and parse the pre-filled form1 after importing the
# tournament link via form2.
# ---------------------------------------------------------------------------

def get_csrf_and_cookies(session: requests.Session) -> str:
    r = session.get(BASE_URL, timeout=30)
    r.raise_for_status()
    m = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', r.text)
    if not m:
        raise RuntimeError("csrfmiddlewaretoken introuvable sur la page GET")
    return m.group(1)


def import_tournament(session: requests.Session, csrf_token: str, event_url: str) -> str:
    data = {"csrfmiddlewaretoken": csrf_token, "event": event_url}
    r = session.post(BASE_URL, data=data, headers={"Referer": BASE_URL}, timeout=60)
    r.raise_for_status()
    return r.text


def parse_form1_fields(html: str):
    """Extrait tous les champs (hors file inputs) de form1 avec leur valeur
    courante, telle que pré-remplie par Top8er après l'import."""
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form", class_="form1")
    if form is None:
        raise RuntimeError("form1 introuvable dans la réponse (import du lien a-t-il échoué ?)")

    fields = {}
    checkboxes = {}

    for inp in form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        itype = inp.get("type", "text")
        if itype in ("file", "submit", "image"):
            continue
        if itype == "checkbox":
            checkboxes[name] = inp.has_attr("checked")
        else:
            fields[name] = inp.get("value", "")

    for sel in form.find_all("select"):
        name = sel.get("name")
        if not name:
            continue
        chosen = sel.find("option", selected=True)
        if chosen is None:
            chosen = sel.find("option")
        fields[name] = chosen.get("value", "") if chosen else ""

    # roster / flag option lists, needed to validate overrides against the
    # exact values the site accepts
    char_select = form.find("select", attrs={"name": "player1_char"})
    roster = [opt.get("value") for opt in char_select.find_all("option")]

    csrf = fields.get("csrfmiddlewaretoken")
    return fields, checkboxes, roster, csrf


# ---------------------------------------------------------------------------
# Skin xlsx loading + normalization
# ---------------------------------------------------------------------------

def parse_skin_cell(raw, roster_norm: dict):
    """Parse une cellule "<Personnage> <couleur>" combinée (ancien format
    MAIN/SECONDARY/TERTIARY). N'est plus utilisée par load_skin_db (format
    triplet désormais), gardée pour migrate_skins_format.py.
    Retourne (char, color_str) ou (None, raison) si la cellule est vide,
    illisible ou ambigüe (cf. SPEC.md, section "Cas ambigus")."""
    if raw is None:
        return None, None
    text = str(raw).strip()
    if not text:
        return None, None

    # le nom du personnage précède toujours le premier chiffre, quel que
    # soit le texte d'annotation qui suit (virgules, "ou", parenthèses...)
    m_first_digit = re.search(r"\d", text)
    if m_first_digit is None:
        return None, f"ambigu ou couleur manquante : {text!r}"
    char_part = normalize_char_name(text[: m_first_digit.start()]).rstrip(" ,")
    if not char_part:
        return None, f"personnage vide après parsing : {text!r}"

    m_default = re.search(r"(\d)\s*\(?\s*(?:par\s*d[ée]faut|default)", text, re.IGNORECASE)
    if m_default:
        color = m_default.group(1)
    else:
        digits = re.findall(r"(?<!\w)([0-7])(?!\w)", text)
        if len(digits) != 1:
            return None, f"ambigu ou couleur manquante : {text!r}"
        color = digits[0]

    key = ALIASES.get(char_part.casefold())
    if key is None:
        key = roster_norm.get(char_part.casefold())
    if key is None:
        return None, f"personnage non reconnu : {char_part!r} (brut: {text!r})"

    return (key, color), None


def load_skin_db(xlsx_path: Path, roster: list):
    """Charge le xlsx (format triplet : une ligne = Joueur | Perso | skin)
    en une table de skins indexée par joueur puis par PERSONNAGE. Si
    plusieurs lignes donnent un skin différent pour le même (joueur, perso),
    on garde le skin le plus bas qui ne soit pas 0 (0 seulement si c'est la
    seule valeur disponible)."""
    roster_norm = {normalize_char_name(r).casefold(): r for r in roster}
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb.active

    raw_names = {}
    skins_by_player = {}
    ignored = []
    rows = list(ws.iter_rows(values_only=True))[1:]
    for row in rows:
        name = row[0] if row else None
        if not name or not str(name).strip():
            continue
        norm = normalize(name)
        if not norm or norm == "`":
            ignored.append((name, None, "nom de joueur illisible"))
            continue

        char_raw = row[1] if len(row) > 1 else None
        if not char_raw or not str(char_raw).strip():
            continue  # ligne sans perso renseigné pour ce joueur

        char_part = normalize_char_name(str(char_raw))
        official = ALIASES.get(char_part.casefold()) or roster_norm.get(char_part.casefold())
        if official is None:
            ignored.append((name, char_raw, f"personnage non reconnu : {char_raw!r}"))
            continue

        skin_raw = row[2] if len(row) > 2 else None
        if skin_raw is None or str(skin_raw).strip() == "":
            skin = 0
        else:
            try:
                skin = int(skin_raw)
            except (TypeError, ValueError):
                ignored.append((name, char_raw, f"skin non numérique : {skin_raw!r}"))
                continue
            if not 0 <= skin <= 7:
                ignored.append((name, char_raw, f"skin hors plage 0-7 : {skin_raw!r}"))
                continue

        raw_names.setdefault(norm, name)
        skins_by_player.setdefault(norm, {}).setdefault(official, []).append(skin)

    db = {}
    for norm, char_values in skins_by_player.items():
        resolved = {}
        for char, values in char_values.items():
            nonzero = [v for v in values if v != 0]
            resolved[char] = min(nonzero) if nonzero else 0
        db[norm] = {"raw_name": raw_names[norm], "skins": resolved}
    return db, ignored


def find_skin_entry(player_name: str, skin_db: dict):
    candidates = [player_name] + player_name.split("|")
    for cand in candidates:
        key = normalize(cand)
        if key in skin_db:
            return skin_db[key]
    return None


# ---------------------------------------------------------------------------
# start.gg: usage réel des personnages (nombre de games joués), pour décider
# quels persos afficher par joueur.
# ---------------------------------------------------------------------------

STARTGG_API_URL = "https://api.start.gg/gql/alpha"

EVENT_SETS_QUERY = """
query EventSets($slug: String!, $page: Int!, $perPage: Int!) {
  event(slug: $slug) {
    id
    sets(page: $page, perPage: $perPage, sortType: STANDARD) {
      pageInfo { totalPages }
      nodes {
        id
        slots { entrant { id name } }
        games {
          id
          selections {
            selectionType
            entrant { id }
            character { name }
          }
        }
      }
    }
  }
}
"""


def parse_event_slug(tournament_link: str) -> str:
    """Extrait 'tournament/<slug>/event/<slug>' du lien start.gg fourni,
    tel qu'attendu par l'API GraphQL (champ `slug` de `event`)."""
    m = re.search(r"tournament/([^/]+)/event/([^/]+)", tournament_link)
    if not m:
        raise ValueError(f"lien start.gg inattendu, impossible d'en extraire le slug d'event : {tournament_link!r}")
    return f"tournament/{m.group(1)}/event/{m.group(2)}"


def fetch_character_usage(token: str, tournament_link: str) -> dict:
    """Interroge l'API start.gg pour compter, par entrant (joueur), le nombre
    de games joués par personnage sur l'ensemble de l'event (pools + bracket).
    Retourne {entrant_name: {char_name: nb_games}}."""
    slug = parse_event_slug(tournament_link)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    usage = {}
    page = 1
    while True:
        resp = requests.post(
            STARTGG_API_URL,
            headers=headers,
            json={"query": EVENT_SETS_QUERY, "variables": {"slug": slug, "page": page, "perPage": 25}},
            timeout=60,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("errors"):
            raise RuntimeError(f"erreur API start.gg : {payload['errors']}")
        event = payload["data"]["event"]
        if event is None:
            raise RuntimeError(f"event introuvable sur start.gg pour le slug {slug!r}")
        sets_data = event["sets"]
        for s in sets_data["nodes"] or []:
            entrant_by_id = {
                slot["entrant"]["id"]: slot["entrant"]["name"]
                for slot in (s.get("slots") or [])
                if slot.get("entrant")
            }
            for game in s.get("games") or []:
                for sel in game.get("selections") or []:
                    if sel.get("selectionType") != "CHARACTER":
                        continue
                    char = (sel.get("character") or {}).get("name")
                    entrant = (sel.get("entrant") or {}).get("id")
                    if not char or entrant not in entrant_by_id:
                        continue
                    name = entrant_by_id[entrant]
                    usage.setdefault(name, {})
                    usage[name][char] = usage[name].get(char, 0) + 1
        if page >= sets_data["pageInfo"]["totalPages"]:
            break
        page += 1
    return usage


def select_played_characters(usage_for_player: dict, roster_norm: dict):
    """Applique la règle : perso joué = au moins 2 games ; on garde les 3 plus
    joués, triés du plus joué au moins joué. Retourne une liste de noms de
    perso (valeurs exactes du roster Top8er) ou [] si rien ne qualifie.
    "Random Character" (sélection aléatoire côté start.gg) n'est pas un vrai
    perso affichable (le site n'accepte même pas "Random" en secondaire/
    tertiaire) : on l'exclut du classement plutôt que de planter la soumission."""
    qualifying = [(char, n) for char, n in usage_for_player.items() if n >= 2]
    qualifying.sort(key=lambda item: item[1], reverse=True)
    resolved = []
    unresolved = []
    excluded_random = []
    for char, n in qualifying:
        if len(resolved) >= 3:
            break
        official = ALIASES.get(char.casefold()) or roster_norm.get(normalize_char_name(char).casefold())
        if official is None:
            unresolved.append((char, n))
            continue
        if official == "Random":
            excluded_random.append((char, n))
            continue
        resolved.append((official, n))
    return resolved, unresolved, excluded_random


# ---------------------------------------------------------------------------
# Apply overrides
# ---------------------------------------------------------------------------

SLOT_FIELDS = [("char", "color"), ("extra1", "extra_color1"), ("extra2", "extra_color2")]
DEFAULT_COLOR = "0"


def apply_overrides(fields: dict, skin_db: dict, usage: dict, roster: list, report: list):
    roster_norm = {normalize_char_name(r).casefold(): r for r in roster}
    for n in range(1, 9):
        pname = fields.get(f"player{n}_name", "")
        if not pname:
            continue

        usage_for_player = usage.get(pname)
        if usage_for_player is None:
            for cand in pname.split("|"):
                usage_for_player = usage.get(cand.strip())
                if usage_for_player is not None:
                    break
        if not usage_for_player:
            report.append(f"player{n} ({pname!r}): aucune donnée de perso jouée sur start.gg, perso Top8er conservé")
            continue

        played, unresolved, excluded_random = select_played_characters(usage_for_player, roster_norm)
        if unresolved:
            report.append(f"player{n} ({pname!r}): perso non reconnu ignoré : {unresolved}")
        if excluded_random:
            report.append(f"player{n} ({pname!r}): sélection aléatoire exclue du classement : {excluded_random}")
        if not played:
            report.append(f"player{n} ({pname!r}): aucun perso joué >= 2 games, perso Top8er conservé")
            continue

        skin_entry = find_skin_entry(pname, skin_db)
        player_skins = skin_entry["skins"] if skin_entry else {}

        applied = []
        for (char, games_count), (char_field, color_field) in zip(played, SLOT_FIELDS):
            color = player_skins.get(char, DEFAULT_COLOR)
            source = "xlsx" if char in player_skins else "défaut"
            fields[f"player{n}_{char_field}"] = char
            fields[f"player{n}_{color_field}"] = color
            applied.append(f"{char} #{color} ({source}, {games_count} games)")
        # un perso déjà positionné a droit à un slot fixe ; si moins de 3
        # persos qualifient, les slots restants gardent la valeur Top8er
        # (généralement vide) sans y toucher.
        report.append(f"player{n} ({pname!r}): {', '.join(applied)}")


# ---------------------------------------------------------------------------
# Final POST + result extraction
# ---------------------------------------------------------------------------

def submit_generation(session, csrf_token, fields, checkboxes, font_file, background, logo):
    data = {"csrfmiddlewaretoken": csrf_token}
    data.update(fields)
    for name, checked in checkboxes.items():
        if checked:
            data[name] = "on"

    files = {
        "font_file": (font_file.name, open(font_file, "rb")),
        "background": (background.name, open(background, "rb")),
        "logo": (logo.name, open(logo, "rb")),
    }
    try:
        r = session.post(BASE_URL, data=data, files=files, headers={"Referer": BASE_URL}, timeout=120)
    finally:
        for _, (_, fh) in files.items():
            fh.close()
    r.raise_for_status()
    return r.text


def extract_result_image(html: str):
    soup = BeautifulSoup(html, "html.parser")

    # le visuel généré est embarqué en base64 ; de nombreux <img> non liés au
    # résultat (logos d'autres jeux, etc.) sont présents ailleurs sur la page,
    # donc on cherche directement une source data:image plutôt que de
    # naviguer depuis l'ancre #result.
    for candidate in soup.find_all("img"):
        src = candidate.get("src", "").strip()
        if src.startswith("data:image"):
            header, b64data = src.split(",", 1)
            ext = header.split("/")[1].split(";")[0]
            return ext, base64.b64decode(b64data.strip())

    anchor = soup.find(attrs={"id": "result"}) or soup.find(attrs={"name": "result"})
    img = (anchor.find("img") or anchor.find_next("img")) if anchor is not None else None
    if img is None:
        return None
    return ("url", img.get("src", ""))


# ---------------------------------------------------------------------------
# Mode revue : ouvre un vrai navigateur, pré-rempli avec nos calculs, pour
# relecture/modification manuelle avant de cliquer soi-même sur "Generate".
# ---------------------------------------------------------------------------

SELECT_SUFFIXES = ("_char", "_color", "_flag", "_extra1", "_extra_color1", "_extra2", "_extra_color2")
GLOBAL_SELECT_NAMES = {"fontt"}
SKIP_FIELDS = {"csrfmiddlewaretoken"}


def open_for_review(tournament_link, fields, checkboxes, font_file, background, logo):
    from playwright.sync_api import sync_playwright

    # profil Chrome dédié et isolé : éviter de piloter/perturber le Chrome
    # personnel de l'utilisateur (déjà ouvert, verrou de profil, sessions...).
    profile_dir = Path(__file__).parent.parent / ".browser-profile"
    profile_dir.mkdir(exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(profile_dir), channel="chrome", headless=False
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(BASE_URL)

        # form2 (import de lien) est masqué par défaut ; il faut d'abord
        # cliquer sur l'onglet "Enter tournament link" pour le révéler.
        page.click("button.sggform")
        page.fill("form.form2 [name='event']", tournament_link)
        page.click("form.form2 input[type='submit']")
        page.wait_for_selector("form.form1 [name='player1_name']")

        # "Layout Options" (couleurs) et "Font Options" (police) sont des
        # sections repliées par défaut (display:none) qu'il faut déplier
        # avant de pouvoir y remplir quoi que ce soit.
        page.click("span.togglelayopt")
        page.click("span.togglefontopt")
        # chaque joueur a son propre "+" repliant les champs perso secondaire/
        # tertiaire (extra1/extra2) : il faut cliquer les 8.
        for toggle in page.locator("span.showextra").all():
            toggle.click()

        for name, value in fields.items():
            if name in SKIP_FIELDS:
                continue
            is_select = name in GLOBAL_SELECT_NAMES or name.endswith(SELECT_SUFFIXES)
            locator = page.locator(f"form.form1 [name='{name}']")
            if locator.count() == 0:
                continue
            if is_select:
                locator.select_option(value)
            else:
                locator.fill(value)

        for name, checked in checkboxes.items():
            locator = page.locator(f"form.form1 [name='{name}']")
            if locator.count() == 0:
                continue
            if checked:
                locator.check()
            else:
                locator.uncheck()

        page.set_input_files("form.form1 [name='font_file']", str(font_file))
        page.set_input_files("form.form1 [name='background']", str(background))
        page.set_input_files("form.form1 [name='logo']", str(logo))

        print("\nFormulaire pré-rempli ouvert dans le navigateur — relis/modifie à ta guise,")
        print("puis clique toi-même sur \"Generate\". Ferme la fenêtre pour rendre la main ici.")
        try:
            page.wait_for_event("close", timeout=24 * 3600 * 1000)  # jusqu'à 24h, pas de vraie limite utile ici
        except Exception:
            pass
        context.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="POC automatisation Top8er SSBU")
    parser.add_argument("tournament_link", help="Lien start.gg/challonge/tonamel/parry.gg")
    parser.add_argument("--background", required=True, type=Path, help="Image de fond")
    parser.add_argument("--logo", required=True, type=Path, help="Logo")
    parser.add_argument(
        "--startgg-token", required=True,
        help="Token API start.gg (developer.start.gg -> Developer Settings -> Create new token)",
    )
    parser.add_argument(
        "--skins", type=Path,
        default=Path(__file__).parent.parent / "data" / "skin.xlsx",
    )
    parser.add_argument(
        "--font", type=Path,
        default=Path(__file__).parent.parent / "data" / "Basteleur-Bold.ttf",
    )
    parser.add_argument(
        "--outdir", type=Path,
        default=Path(__file__).parent.parent / "output",
    )
    parser.add_argument(
        "--review", action="store_true",
        help="Bloque avant la génération : ouvre un navigateur pré-rempli avec nos calculs "
             "pour relecture/modification manuelle (nécessite `pip install playwright`).",
    )
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})

    print(f"[1/4] GET {BASE_URL}")
    csrf = get_csrf_and_cookies(session)

    print(f"[2/4] POST import du tournoi : {args.tournament_link}")
    imported_html = import_tournament(session, csrf, args.tournament_link)
    fields, checkboxes, roster, csrf2 = parse_form1_fields(imported_html)
    if csrf2:
        csrf = csrf2
    if "btext" in fields:
        fields["btext"] = make_inclusive(fields["btext"])

    print("[3/4] Résolution des skins depuis le xlsx + usage réel des persos (API start.gg)")
    skin_db, ignored = load_skin_db(args.skins, roster)
    usage = fetch_character_usage(args.startgg_token, args.tournament_link)
    report = []
    apply_overrides(fields, skin_db, usage, roster, report)
    fields["lcolor1"] = FIXED_LCOLOR1
    fields["lcolor2"] = FIXED_LCOLOR2

    print("\n--- Rapport ---")
    for line in report:
        print(" -", line)
    if ignored:
        print("\nLignes xlsx ignorées :")
        for item in ignored:
            print(" -", item)

    if args.review:
        print("\n[4/4] Mode revue : ouverture du navigateur, génération non lancée")
        open_for_review(args.tournament_link, fields, checkboxes, args.font, args.background, args.logo)
        return

    print("\n[4/4] POST génération finale (police + couleurs + background + logo)")
    result_html = submit_generation(session, csrf, fields, checkboxes, args.font, args.background, args.logo)

    args.outdir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", args.tournament_link.rstrip("/").split("/")[-1]) or "tournoi"

    raw_path = args.outdir / f"{timestamp}-{slug}.response.html"
    raw_path.write_text(result_html, encoding="utf-8")
    print(f"Réponse brute sauvegardée : {raw_path}")

    extracted = extract_result_image(result_html)
    if extracted is None:
        print("Image de résultat non détectée automatiquement — inspecter la réponse HTML ci-dessus.")
    else:
        kind, payload = extracted
        if kind == "url":
            print(f"Image de résultat référencée par URL : {payload}")
        else:
            img_path = args.outdir / f"{timestamp}-{slug}.{kind}"
            img_path.write_bytes(payload)
            print(f"Image de résultat sauvegardée : {img_path}")


if __name__ == "__main__":
    sys.exit(main())
