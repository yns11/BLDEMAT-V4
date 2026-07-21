"""Extraction assistée par LLM des informations d'un BL à partir de son image.

Appelle un endpoint de model serving Databricks (modèle vision, format chat
OpenAI-compatible) via l'authentification runtime de l'app (aucun jeton en dur).
Optionnel et non bloquant : si l'endpoint n'est pas configuré (BL_LLM_ENDPOINT)
ou en cas d'échec, l'app bascule sur la saisie semi-manuelle.

Les valeurs extraites sont ensuite RAPPROCHÉES des référentiels (fournisseurs/
clients, quais) pour être confirmées ; sans correspondance, l'utilisateur
choisit manuellement.
"""

import base64
import difflib
import json
import logging
import os
from typing import Optional

logger = logging.getLogger("bl.extraction")

# Champs que le modèle doit renvoyer (toujours des chaînes, vides si absents).
CHAMPS_ATTENDUS = ["numero_bl", "tiers", "statut", "date", "quai", "commentaire"]


def endpoint_configure() -> Optional[str]:
    """Nom de l'endpoint de model serving à utiliser, ou None si l'extraction
    IA n'est pas activée (l'app fonctionne alors en saisie manuelle)."""
    return os.environ.get("BL_LLM_ENDPOINT") or None


def _prompt(tiers_libelle: str) -> str:
    t = tiers_libelle.lower()
    return (
        "Tu es un assistant logistique qui lit des bordereaux de livraison (BL) "
        "photographiés, parfois annotés à la main. Analyse l'image et extrais les "
        "informations demandées. Réponds UNIQUEMENT par un objet JSON valide, sans "
        "aucun texte autour, avec exactement ces clés :\n"
        '- "numero_bl" : le numéro du BL tel qu\'il est écrit ;\n'
        f'- "tiers" : le nom du {t} (raison sociale) tel qu\'il apparaît ;\n'
        '- "statut" : "OK" ou "EDI NOK" UNIQUEMENT si une mention ou un tampon '
        "manuscrit l'indique clairement, sinon \"\" ;\n"
        '- "date" : la date de livraison au format AAAA-MM-JJ si lisible, sinon "" ;\n'
        '- "quai" : l\'identifiant du quai si visible, sinon "" ;\n'
        '- "commentaire" : une mention manuscrite pertinente, sinon "".\n'
        "Si une information est absente ou illisible, mets une chaîne vide."
    )


def _texte_reponse(contenu) -> str:
    """Le contenu d'un message peut être une chaîne ou une liste de blocs."""
    if isinstance(contenu, list):
        return " ".join(bloc.get("text", "") for bloc in contenu
                        if isinstance(bloc, dict))
    return contenu or ""


def _parser_json(texte: str) -> dict:
    t = _texte_reponse(texte).strip()
    debut, fin = t.find("{"), t.rfind("}")
    if debut == -1 or fin == -1:
        raise ValueError("Réponse du modèle non JSON.")
    data = json.loads(t[debut:fin + 1])
    return {c: str(data.get(c, "") or "").strip() for c in CHAMPS_ATTENDUS}


def extraire_infos_bl(image_bytes: bytes, tiers_libelle: str = "fournisseur") -> dict:
    """Interroge le modèle vision et renvoie un dict des champs extraits (chaînes,
    éventuellement vides). Lève RuntimeError si l'endpoint n'est pas configuré,
    et propage les erreurs d'appel/parsing (l'appelant gère le repli)."""
    endpoint = endpoint_configure()
    if not endpoint:
        raise RuntimeError("Aucun endpoint LLM configuré (variable BL_LLM_ENDPOINT).")

    from databricks.sdk import WorkspaceClient

    b64 = base64.b64encode(image_bytes).decode("ascii")
    body = {
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": _prompt(tiers_libelle)},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ],
        }],
        "max_tokens": 700,
        "temperature": 0,
    }
    resp = WorkspaceClient().api_client.do(
        "POST", f"/serving-endpoints/{endpoint}/invocations", body=body)
    contenu = resp["choices"][0]["message"]["content"]
    infos = _parser_json(contenu)
    logger.info("Extraction BL : %s", {k: v for k, v in infos.items() if v})
    return infos


def rapprocher(valeur: str, options: list[str], seuil: float = 0.6) -> Optional[str]:
    """Option du référentiel la plus proche de la valeur extraite, ou None
    (insensible à la casse : exact, puis sous-chaîne, puis proximité difflib)."""
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
