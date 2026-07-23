"""Extraction assistée par LLM des informations d'un BL à partir de ses pages.

Appelle un endpoint de model serving Databricks (modèle vision, format chat
OpenAI-compatible) via l'authentification runtime de l'app (aucun jeton en dur).
Optionnel et non bloquant : si l'endpoint n'est pas configuré (BL_LLM_ENDPOINT)
ou en cas d'échec, l'app bascule sur la saisie semi-manuelle.

Toutes les pages du BL sont analysées ensemble. Les valeurs extraites sont
RAPPROCHÉES des référentiels : le code tiers (S-000000 / C-000000) prime sur
la raison sociale ; le numéro de BL est confronté aux DESADV du tiers
(préfixe/suffixe). Le rapprochement est itératif : premier appel sans
référentiel, puis appels supplémentaires en injectant, au besoin, la liste des
tiers ou les BL connus du tiers reconnu (points 6.i–6.iv).
"""

import base64
import difflib
import json
import logging
import os
import re
from typing import Callable, Optional, Union

logger = logging.getLogger("bl.extraction")

# Champs que le modèle doit renvoyer (toujours des chaînes, vides si absents).
# Le quai n'est PAS détecté par l'IA : il vient du protocole logistique (PLA)
# du tiers, avec un quai par défaut sinon.
CHAMPS_ATTENDUS = ["numero_bl", "code_tiers", "tiers", "adresse",
                   "statut", "date", "commentaire"]

# Nombre max de lignes de référentiel injectées dans le contexte (coût tokens).
MAX_CONTEXTE = 400
# Nombre max d'appels au modèle par extraction (passes de raffinement).
MAX_PASSES = 3
# Nombre max de pages envoyées au modèle : les informations d'en-tête sont sur
# les premières pages, et chaque page ajoute ~2,7 Mo de base64 à la requête.
MAX_PAGES_IA = 4

Images = Union[bytes, bytearray, list]


def endpoint_configure() -> Optional[str]:
    """Nom de l'endpoint de model serving à utiliser, ou None si l'extraction
    IA n'est pas activée (l'app fonctionne alors en saisie manuelle)."""
    return os.environ.get("BL_LLM_ENDPOINT") or None


# ---------------------------------------------------------------------------
# Référentiel injecté (découplé du repository pour rester testable).
# ---------------------------------------------------------------------------
class Referentiel:
    """Données de référence fournies au rapprochement et, au besoin, au modèle.

    - ``tiers`` : libellés du référentiel, au format « code : raison sociale »
      (ex. « S-001234 : ACME SARL »).
    - ``bls_pour_tiers(nom)`` : numéros de BL (DESADV) connus pour ce tiers.
    - ``adresses`` : adresse de site par tiers, si disponible (évolution
      future du référentiel — utilisée dès qu'elle est renseignée)."""

    def __init__(self, tiers: Optional[list] = None,
                 bls_pour_tiers: Optional[Callable[[str], list]] = None,
                 adresses: Optional[dict] = None) -> None:
        self.tiers = list(tiers or [])
        self._bls = bls_pour_tiers
        self.adresses = dict(adresses) if adresses else {}

    def bls_pour_tiers(self, nom: str) -> list:
        if not self._bls or not nom:
            return []
        try:
            return list(self._bls(nom) or [])
        except Exception as e:  # ne jamais bloquer l'extraction pour ça
            logger.warning("BLs du tiers « %s » indisponibles : %s", nom, e)
            return []


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
def _prompt(tiers_libelle: str, contexte: Optional[dict] = None) -> str:
    t = tiers_libelle.lower()
    prefixe_code = "C-000000" if t.startswith("client") else "S-000000"
    base = (
        "Tu es un assistant logistique qui lit des bordereaux de livraison (BL) "
        "photographiés. Les images fournies sont les PAGES d'un même BL : "
        "analyse-les TOUTES ensemble. Distingue bien le texte IMPRIMÉ des "
        "annotations MANUSCRITES. Réponds UNIQUEMENT par un objet JSON valide, "
        "sans aucun texte autour, avec exactement ces clés :\n"
        '- "numero_bl" : le numéro du BL (texte imprimé) tel qu\'il est écrit ;\n'
        f'- "code_tiers" : le code du {t} s\'il figure sur le BL '
        f'(format « {prefixe_code} »), sinon "" ;\n'
        f'- "tiers" : la raison sociale du {t} (texte imprimé) telle qu\'elle '
        "apparaît ;\n"
        f'- "adresse" : l\'adresse du site du {t} si elle figure, sinon "" ;\n'
        '- "statut" : UNIQUEMENT si une mention MANUSCRITE l\'indique clairement, '
        'renvoie "OK" (équivalent « EDI OK ») ou "NOK" (équivalent « EDI NOK ») ; '
        "si rien n'est écrit à la main, renvoie \"\" (n'utilise JAMAIS une "
        "mention imprimée) ;\n"
        '- "date" : UNIQUEMENT si une date de réception/livraison est écrite À LA '
        'MAIN, au format AAAA-MM-JJ ; ignore les dates imprimées ; sinon "" ;\n'
        '- "commentaire" : une autre mention manuscrite pertinente, sinon "".\n'
        "Si une information est absente ou illisible, mets une chaîne vide."
    )
    return base + _bloc_contexte(contexte, t)


def _bloc_contexte(contexte: Optional[dict], t: str) -> str:
    if not contexte:
        return ""
    typ = contexte.get("type")
    if typ == "liste_tiers":
        adresses = contexte.get("adresses") or {}
        lignes = []
        for nom in contexte.get("tiers", [])[:MAX_CONTEXTE]:
            adr = adresses.get(nom)
            lignes.append(f"- {nom}" + (f" — {adr}" if adr else ""))
        if not lignes:
            return ""
        return (
            f"\n\nPour t'aider, voici la liste des {t}s connus au référentiel "
            "(format « code : raison sociale »). Le " + t + " du BL correspond "
            "forcément à l'un d'eux : identifie le bon et renvoie dans "
            '"code_tiers" et "tiers" son code et sa raison sociale EXACTS.\n'
            + "\n".join(lignes)
        )
    if typ == "tiers_et_bls":
        bls = contexte.get("bls", [])[:MAX_CONTEXTE]
        if not bls:
            return ""
        return (
            f"\n\nLe {t} a été identifié : « {contexte.get('tiers_retenu', '')} ». "
            "Voici ses numéros de BL connus au référentiel :\n"
            + "\n".join(f"- {b}" for b in bls)
            + "\nSi le numéro que tu lis correspond à l'un d'eux (éventuellement à "
            'un préfixe ou suffixe près), renvoie dans "numero_bl" le numéro EXACT '
            "du référentiel."
        )
    return ""


# ---------------------------------------------------------------------------
# Décodage de la réponse
# ---------------------------------------------------------------------------
def _texte_reponse(contenu) -> str:
    """Le contenu d'un message peut être une chaîne ou une liste de blocs."""
    if isinstance(contenu, list):
        return " ".join(bloc.get("text", "") for bloc in contenu
                        if isinstance(bloc, dict))
    return contenu or ""


def _extraire_contenu(resp) -> str:
    """Récupère le texte de la réponse quel que soit le format de l'endpoint :
    OpenAI-compatible (choices[].message.content) ou Anthropic natif
    (content[].text / completion). Lève une erreur explicite sinon, en
    exposant les clés reçues pour faciliter le diagnostic."""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, dict):
        # Format chat OpenAI-compatible (cas nominal).
        choix = resp.get("choices")
        if choix:
            msg = choix[0].get("message") or {}
            if "content" in msg:
                return _texte_reponse(msg["content"])
            if "text" in choix[0]:
                return choix[0]["text"]
        # Format Anthropic natif.
        if "content" in resp:
            return _texte_reponse(resp["content"])
        for cle in ("completion", "output_text", "predictions", "result"):
            if resp.get(cle):
                return _texte_reponse(resp[cle])
    raise ValueError(
        "Réponse de l'endpoint au format inattendu "
        f"(clés : {list(resp.keys()) if isinstance(resp, dict) else type(resp).__name__})."
    )


def _parser_json(texte: str) -> dict:
    t = _texte_reponse(texte).strip()
    debut, fin = t.find("{"), t.rfind("}")
    if debut == -1 or fin == -1:
        raise ValueError("Réponse du modèle non JSON.")
    data = json.loads(t[debut:fin + 1])
    return {c: str(data.get(c, "") or "").strip() for c in CHAMPS_ATTENDUS}


# ---------------------------------------------------------------------------
# Appel au modèle (une passe, toutes les pages)
# ---------------------------------------------------------------------------
def _normaliser_images(images: Images) -> list:
    if images is None:
        return []
    if isinstance(images, (bytes, bytearray)):
        return [bytes(images)]
    return [bytes(i) for i in images if i]


def _appel(client, endpoint: str, pages: list, prompt: str) -> dict:
    contenu = [{"type": "text", "text": prompt}]
    for img in pages:
        b64 = base64.b64encode(img).decode("ascii")
        contenu.append({"type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
    body = {"messages": [{"role": "user", "content": contenu}], "max_tokens": 900}
    resp = client.api_client.do(
        "POST", f"/serving-endpoints/{endpoint}/invocations", body=body)
    return _parser_json(_extraire_contenu(resp))


# ---------------------------------------------------------------------------
# Orchestration : extraction + rapprochement itératif
# ---------------------------------------------------------------------------
def extraire_infos_bl(images: Images, tiers_libelle: str = "fournisseur",
                      referentiel: Optional[Referentiel] = None,
                      max_passes: int = MAX_PASSES) -> dict:
    """Analyse toutes les pages du BL et renvoie un dict des champs extraits
    (chaînes, éventuellement vides). Si un ``referentiel`` est fourni, affine
    l'extraction en réinterrogeant le modèle avec du contexte (liste des tiers,
    puis BL du tiers reconnu) tant que le rapprochement n'est pas fiable.

    Lève RuntimeError si l'endpoint n'est pas configuré ; propage les erreurs
    d'appel/parsing (l'appelant gère le repli)."""
    endpoint = endpoint_configure()
    if not endpoint:
        raise RuntimeError("Aucun endpoint LLM configuré (variable BL_LLM_ENDPOINT).")
    pages = _normaliser_images(images)[:MAX_PAGES_IA]
    if not pages:
        raise ValueError("Aucune image à analyser.")

    from databricks.sdk import WorkspaceClient
    client = WorkspaceClient()

    contexte: Optional[dict] = None
    deja_essaye: set = set()
    infos: dict = {}
    for tentative in range(max(1, max_passes)):
        infos = _appel(client, endpoint, pages, _prompt(tiers_libelle, contexte))
        logger.info("Extraction BL (passe %d) : %s", tentative + 1,
                    {k: v for k, v in infos.items() if v})
        if referentiel is None or not referentiel.tiers:
            break

        tiers_opt, fiab = rapprocher_tiers(
            infos.get("code_tiers"), infos.get("tiers"), referentiel.tiers)

        # (iv) tiers non reconnu -> fournir la liste des tiers, une seule fois.
        if fiab == "aucun":
            if "liste_tiers" in deja_essaye:
                break
            deja_essaye.add("liste_tiers")
            contexte = {"type": "liste_tiers", "tiers": referentiel.tiers,
                        "adresses": referentiel.adresses}
            continue

        # (ii/iii) tiers reconnu -> confronter le numéro de BL à ses DESADV.
        bls = referentiel.bls_pour_tiers(tiers_opt)
        bl_opt = rapprocher_bl(infos.get("numero_bl"), bls)
        if bl_opt:
            infos["numero_bl"] = bl_opt   # préférer la version du référentiel
            break
        # tiers ok mais BL non retrouvé -> fournir ses BL, une seule fois.
        if not bls or "tiers_et_bls" in deja_essaye:
            break
        deja_essaye.add("tiers_et_bls")
        contexte = {"type": "tiers_et_bls", "tiers_retenu": tiers_opt, "bls": bls}

    return infos


# ---------------------------------------------------------------------------
# Rapprochement des valeurs extraites avec le référentiel
# ---------------------------------------------------------------------------
def _norm_code(code: Optional[str]) -> str:
    """Normalise un code tiers pour comparaison : alphanumérique, majuscules
    (« S-001234 », « s 001234 » -> « S001234 »)."""
    return re.sub(r"[^A-Za-z0-9]", "", code or "").upper()


def _scinder_tiers(name: str) -> tuple:
    """« S-001234 : ACME SARL » -> ("S001234", "ACME SARL")."""
    if ":" in name:
        code, raison = name.split(":", 1)
    else:
        code, raison = "", name
    return _norm_code(code), raison.strip()


def rapprocher_tiers(code_tiers: Optional[str], nom_tiers: Optional[str],
                     options: list) -> tuple:
    """Rapproche un tiers détecté du référentiel. Renvoie (libellé, fiabilité)
    où fiabilité ∈ {"code", "nom", "aucun"}. Le code prime (très fiable) ;
    à défaut, rapprochement sur la raison sociale (exact, sous-chaîne, puis
    difflib en dernier recours)."""
    if not options:
        return None, "aucun"

    nc = _norm_code(code_tiers)
    if nc:
        for o in options:
            if _scinder_tiers(o)[0] == nc:
                return o, "code"

    nom = (nom_tiers or "").strip().lower()
    if nom:
        raisons = {_scinder_tiers(o)[1].lower(): o for o in options}
        if nom in raisons:
            return raisons[nom], "nom"
        for o in options:
            rs = _scinder_tiers(o)[1].lower()
            if len(nom) >= 3 and (nom in rs or rs in nom):
                return o, "nom"
        proches = difflib.get_close_matches(nom, list(raisons), n=1, cutoff=0.7)
        if proches:
            return raisons[proches[0]], "nom"
    return None, "aucun"


def rapprocher_bl(numero: Optional[str], bls: list) -> Optional[str]:
    """Numéro de BL du référentiel correspondant au numéro détecté : exact
    (insensible à la casse) ou par inclusion préfixe/suffixe (on préfère alors
    la version du référentiel). Pas de difflib (risque d'appariement erroné)."""
    if not numero or not bls:
        return None
    n = numero.strip().lower()
    bas = {b.lower(): b for b in bls}
    if n in bas:
        return bas[n]
    for b in bls:
        bl = b.lower()
        if len(n) >= 4 and (n in bl or bl in n):
            return b
    return None


def statut_est_nok(statut: Optional[str]) -> Optional[bool]:
    """Interprète le statut manuscrit détecté : True si NOK, False si OK,
    None si non renseigné. « EDI NOK » ≡ « NOK », « EDI OK » ≡ « OK »."""
    s = (statut or "").strip().upper().replace("EDI", "").strip()
    if not s:
        return None
    if "NOK" in s:
        return True
    if "OK" in s:
        return False
    return None


def rapprocher(valeur: str, options: list, seuil: float = 0.6) -> Optional[str]:
    """Option du référentiel la plus proche de la valeur extraite, ou None
    (insensible à la casse : exact, puis sous-chaîne, puis proximité difflib).
    Utilisé pour des champs simples comme le quai."""
    if not valeur or not options:
        return None
    v = valeur.strip().lower()
    bas = {o.lower(): o for o in options}
    if v in bas:
        return bas[v]
    for o in options:
        ol = o.lower()
        if len(v) >= 3 and (v in ol or ol in v):
            return o
    proches = difflib.get_close_matches(v, list(bas), n=1, cutoff=seuil)
    return bas[proches[0]] if proches else None
