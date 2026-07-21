"""Couche d'accès aux données (repository) — V3 Lakebase Postgres.

Les métadonnées ET les photos sont stockées dans une base Lakebase (Postgres
managé Databricks). Authentification par jeton OAuth du service principal
(renouvelé avant expiration), requêtes paramétrées, reconnexion automatique.

V3 :
- numéro de BL UNIQUE (violation -> ValueError avec message utilisateur) ;
- quatre types d'opération (réception / expédition / archivage de chacun) ;
- référentiels gérés en base : tiers (fournisseurs/clients), DESADV par sens
  (achat/vente), gestionnaires, portefeuilles, quais — avec un CRUD générique
  utilisé par l'app Administration.
"""

import datetime
import logging
import os
import time
import uuid
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd
import psycopg
import streamlit as st

from .config import get_settings

logger = logging.getLogger("bl.repository")

STATUT_OK = "1"
STATUT_EDI_NOK = "0"

# --- Types d'opération -----------------------------------------------------
TYPE_RECEPTION = "RECEPTION"
TYPE_EXPEDITION = "EXPEDITION"
TYPE_ARCHIVAGE_RECEPTION = "ARCHIVAGE_RECEPTION"
TYPE_ARCHIVAGE_EXPEDITION = "ARCHIVAGE_EXPEDITION"
LIBELLES_OPERATION = {
    TYPE_RECEPTION: "Nouvelle réception",
    TYPE_EXPEDITION: "Nouvelle expédition",
    TYPE_ARCHIVAGE_RECEPTION: "Archivage d'un ancien BL réception",
    TYPE_ARCHIVAGE_EXPEDITION: "Archivage d'un ancien BL expédition",
}
TYPES_ACHAT = [TYPE_RECEPTION, TYPE_ARCHIVAGE_RECEPTION]      # tiers = fournisseur
TYPES_VENTE = [TYPE_EXPEDITION, TYPE_ARCHIVAGE_EXPEDITION]    # tiers = client

SENS_ACHAT = "ACHAT"
SENS_VENTE = "VENTE"
TIERS_FOURNISSEUR = "FOURNISSEUR"
TIERS_CLIENT = "CLIENT"


def sens_operation(type_operation: str) -> str:
    return SENS_VENTE if type_operation in TYPES_VENTE else SENS_ACHAT


def libelle_tiers(type_operation: str) -> str:
    """« Client » côté vente (expéditions), « Fournisseur » côté achat."""
    return "Client" if type_operation in TYPES_VENTE else "Fournisseur"


def operation_avec_plage_et_quai(type_operation: str) -> bool:
    """Plage horaire, quai et commentaire : nouvelles réceptions/expéditions
    uniquement (les archivages ne portent que numéro, date et tiers)."""
    return type_operation in (TYPE_RECEPTION, TYPE_EXPEDITION)


def operation_avec_statut(type_operation: str) -> bool:
    """L'état OK / EDI NOK n'existe que pour une nouvelle réception."""
    return type_operation == TYPE_RECEPTION


# --- Plages horaires -------------------------------------------------------
PLAGES_HORAIRES = ["00h-06h"] + [f"{h:02d}h-{h + 2:02d}h" for h in range(6, 20, 2)] + ["20h-00h"]


def maintenant_local() -> datetime.datetime:
    """Heure locale du site (le conteneur d'app tourne en UTC)."""
    try:
        fuseau = ZoneInfo(os.environ.get("BL_FUSEAU", "Europe/Paris"))
    except Exception:
        fuseau = None
    return datetime.datetime.now(fuseau)


def plage_horaire_courante() -> str:
    """Plage horaire contenant l'heure locale courante (préremplissage)."""
    h = maintenant_local().hour
    if h < 6:
        return PLAGES_HORAIRES[0]
    if h >= 20:
        return PLAGES_HORAIRES[-1]
    debut = 6 + ((h - 6) // 2) * 2
    return f"{debut:02d}h-{debut + 2:02d}h"


# ---------------------------------------------------------------------------
# Connexion Lakebase (une par processus, renouvelée avant expiration du jeton)
# ---------------------------------------------------------------------------
_DUREE_MAX_CONNEXION_S = 45 * 60
_ERREURS_CONNEXION = (psycopg.OperationalError, psycopg.InterfaceError)


@st.cache_resource(show_spinner=False)
def _etat_connexion() -> dict:
    return {"conn": None, "creee_a": 0.0}


def _jeton_acces() -> str:
    """Mot de passe Postgres = jeton OAuth Databricks du service principal
    (DATABRICKS_CLIENT_ID/SECRET injectés par la plateforme). Si le workspace
    injecte LAKEBASE_ENDPOINT, le jeton dédié à l'endpoint est préféré."""
    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient()
    endpoint = os.environ.get("LAKEBASE_ENDPOINT", "")
    if endpoint:
        try:
            return w.postgres.generate_database_credential(endpoint=endpoint).token
        except Exception as e:
            logger.warning("generate_database_credential en échec (%s) : repli sur le jeton OAuth.", e)
    return w.config.oauth_token().access_token


def _nouvelle_connexion():
    if not os.environ.get("PGHOST"):
        raise RuntimeError(
            "PGHOST absent : vérifiez que la ressource d'app « postgres » "
            "(base Lakebase) est bien attachée à l'application, puis redéployez-la."
        )
    return psycopg.connect(
        host=os.environ["PGHOST"],
        port=int(os.environ.get("PGPORT", "5432")),
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=_jeton_acces(),
        sslmode="require",
    )


def _fermer_connexion() -> None:
    etat = _etat_connexion()
    if etat["conn"] is not None:
        try:
            etat["conn"].close()
        except Exception:
            pass
    etat["conn"] = None


def _get_connection():
    etat = _etat_connexion()
    conn = etat["conn"]
    if conn is None or conn.closed or time.monotonic() - etat["creee_a"] > _DUREE_MAX_CONNEXION_S:
        _fermer_connexion()
        etat["conn"] = _nouvelle_connexion()
        etat["creee_a"] = time.monotonic()
    return etat["conn"]


def _run(query: str, params: Optional[dict] = None, fetch: bool = False):
    """Requête paramétrée. Rejouée une fois sur coupure de connexion (réveil
    après scale-to-zero, jeton expiré) ; les erreurs de données (doublon,
    clé étrangère...) remontent immédiatement après rollback."""
    for tentative in (1, 2):
        try:
            conn = _get_connection()
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                resultat = None
                if fetch:
                    cols = [d[0] for d in cursor.description]
                    resultat = pd.DataFrame(cursor.fetchall(), columns=cols)
            conn.commit()
            return resultat
        except _ERREURS_CONNEXION as e:
            _fermer_connexion()
            if tentative == 1:
                logger.warning("Connexion Lakebase perdue, nouvelle tentative : %s", e)
                continue
            logger.error("Erreur SQL Lakebase : %s | requête : %s", e, query.strip().split("\n")[0])
            raise
        except Exception:
            try:
                conn.rollback()
            except Exception:
                _fermer_connexion()
            raise


# ---------------------------------------------------------------------------
# Référentiels — lectures en cache court (utilisées par l'app Création)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=300, show_spinner=False)
def lister_tiers(type_tiers: str) -> list[str]:
    """Fournisseurs (TIERS_FOURNISSEUR) ou clients (TIERS_CLIENT)."""
    s = get_settings()
    df = _run(
        f"SELECT name FROM {s.pg_schema}.base_tiers WHERE type_tiers = %(t)s ORDER BY name",
        params={"t": type_tiers},
        fetch=True,
    )
    return df["name"].tolist() if df is not None else []


@st.cache_data(ttl=300, show_spinner=False)
def lister_quais() -> list[str]:
    s = get_settings()
    df = _run(f"SELECT code_quai FROM {s.pg_schema}.quais ORDER BY code_quai", fetch=True)
    return df["code_quai"].tolist() if df is not None else []


@st.cache_data(ttl=300, show_spinner=False)
def lister_gestionnaires() -> list[str]:
    s = get_settings()
    df = _run(f"SELECT code_gestionnaire FROM {s.pg_schema}.gestionnaires ORDER BY code_gestionnaire",
              fetch=True)
    return df["code_gestionnaire"].tolist() if df is not None else []


@st.cache_data(ttl=300, show_spinner=False)
def fournisseur_pour_bl(numero_bl: str, sens: str) -> Optional[str]:
    """Tiers annoncé par l'avis d'expédition (DESADV) du sens donné pour ce
    numéro de BL — None si absent (l'utilisateur choisira manuellement)."""
    s = get_settings()
    df = _run(
        f"SELECT nom_fournisseur FROM {s.pg_schema}.base_desadv "
        "WHERE upper(numero_bl) = upper(%(num)s) AND sens = %(sens)s LIMIT 1",
        params={"num": numero_bl, "sens": sens},
        fetch=True,
    )
    if df is None or df.empty:
        return None
    return df["nom_fournisseur"].iloc[0]


def vider_caches_referentiels() -> None:
    """À appeler après un CRUD sur un référentiel (app Administration)."""
    lister_tiers.clear()
    lister_quais.clear()
    lister_gestionnaires.clear()
    fournisseur_pour_bl.clear()


# ---------------------------------------------------------------------------
# Référentiels — CRUD générique (app Administration)
# Les tables sont sur liste blanche ; le diff avant/après est calculé sur les
# lignes complètes (tous nos référentiels sont entièrement clés).
# ---------------------------------------------------------------------------
# « colonnes » = colonnes ÉCRITES par le CRUD ; « cles » = clé primaire
# (une ligne est valide si ses colonnes-clés sont renseignées ; les autres
# colonnes écrites peuvent être vides -> NULL). Les colonnes d'affichage seul
# (ex. horodatages DESADV venus de l'ERP) sont gérées par les lectures dédiées.
REFERENTIELS = {
    "tiers": {"table": "base_tiers", "colonnes": ["name", "type_tiers"], "cles": ["name"]},
    "desadv": {"table": "base_desadv", "colonnes": ["numero_bl", "nom_fournisseur", "sens"],
               "cles": ["numero_bl", "sens"]},
    "gestionnaires": {"table": "gestionnaires", "colonnes": ["code_gestionnaire"],
                      "cles": ["code_gestionnaire"]},
    "portefeuilles": {"table": "portefeuilles", "colonnes": ["code_gestionnaire", "nom_fournisseur"],
                      "cles": ["code_gestionnaire", "nom_fournisseur"]},
    "quais": {"table": "quais", "colonnes": ["code_quai"], "cles": ["code_quai"]},
}


def _table_referentiel(nom: str) -> tuple[str, list[str], list[str]]:
    cfg = REFERENTIELS[nom]  # KeyError = bug d'appel, pas une entrée utilisateur
    return f"{get_settings().pg_schema}.{cfg['table']}", cfg["colonnes"], cfg["cles"]


def lire_referentiel(nom: str, filtres: Optional[dict] = None) -> pd.DataFrame:
    table, colonnes, _ = _table_referentiel(nom)
    filtres = {k: v for k, v in (filtres or {}).items() if k in colonnes}
    where = " AND ".join(f"{c} = %({c})s" for c in filtres) or "1=1"
    ordre = ", ".join(colonnes)
    return _run(f"SELECT {', '.join(colonnes)} FROM {table} WHERE {where} ORDER BY {ordre}",
                params=filtres, fetch=True)


def _norme(valeur) -> str:
    """Valeur de cellule -> chaîne comparable ('' pour vide/None/NaN)."""
    if valeur is None:
        return ""
    txt = str(valeur).strip()
    return "" if txt.lower() in ("", "nan", "none", "nat") else txt


def _indexer(df: pd.DataFrame, visibles: list[str], cles_visibles: list[str],
             detecter_doublons: bool = False) -> dict:
    """{ clé -> ligne complète } pour les lignes dont toutes les colonnes-clés
    sont renseignées (lignes incomplètes en cours de saisie ignorées).
    detecter_doublons=True (grille éditée) : refuse deux lignes de même clé."""
    index = {}
    for _, ligne in df.iterrows():
        cle = tuple(_norme(ligne.get(c)) for c in cles_visibles)
        if all(cle):
            if detecter_doublons and cle in index:
                raise ValueError(
                    "Opération refusée : doublon dans la grille pour "
                    f"« {' / '.join(cle)} » (chaque clé doit être unique).")
            index[cle] = tuple(_norme(ligne.get(c)) for c in visibles)
    return index


def sauver_referentiel(nom: str, df_avant: pd.DataFrame, df_apres: pd.DataFrame,
                       valeurs_fixes: Optional[dict] = None) -> tuple[int, int]:
    """Applique le diff avant/après d'un éditeur de données. Une ligne modifiée
    (même clé, contenu changé) = suppression puis réinsertion. `valeurs_fixes`
    porte les colonnes masquées à l'écran (ex. sens='ACHAT'). df_avant est le
    jeu chargé (éventuellement filtré) : les lignes non chargées ne sont jamais
    touchées. Retourne (nb_ajouts/modifications, nb_suppressions)."""
    table, colonnes, cles = _table_referentiel(nom)
    valeurs_fixes = valeurs_fixes or {}
    visibles = [c for c in colonnes if c not in valeurs_fixes]
    cles_visibles = [c for c in cles if c not in valeurs_fixes]

    avant = _indexer(df_avant, visibles, cles_visibles)
    apres = _indexer(df_apres, visibles, cles_visibles, detecter_doublons=True)

    cles_a_supprimer = {k for k in avant if k not in apres or apres[k] != avant[k]}
    cles_a_inserer = {k for k in apres if k not in avant or apres[k] != avant[k]}

    try:
        for cle in cles_a_supprimer:
            params = dict(zip(cles_visibles, cle)) | valeurs_fixes
            where = " AND ".join(f"{c} = %({c})s" for c in params)
            _run(f"DELETE FROM {table} WHERE {where}", params=params)
        for cle in cles_a_inserer:
            valeurs = dict(zip(visibles, apres[cle]))
            params = {c: (v if v != "" else None) for c, v in valeurs.items()} | valeurs_fixes
            cols = ", ".join(params)
            marqueurs = ", ".join(f"%({c})s" for c in params)
            _run(f"INSERT INTO {table} ({cols}) VALUES ({marqueurs})", params=params)
    except psycopg.errors.ForeignKeyViolation:
        raise ValueError(
            "Opération refusée : une valeur est encore référencée ailleurs "
            "(portefeuille, BL...) ou référence une entrée inexistante."
        ) from None
    except psycopg.errors.UniqueViolation:
        raise ValueError(
            "Opération refusée : ce numéro de BL / cette entrée existe déjà "
            "(doublon interdit)."
        ) from None

    vider_caches_referentiels()
    return len(cles_a_inserer), len(cles_a_supprimer)


# ---------------------------------------------------------------------------
# Lectures filtrées des vues (app Administration)
# ---------------------------------------------------------------------------
def lire_desadv(sens: str, numero: str = "", fournisseur: str = "",
                gestionnaire: str = "", date_min: Optional[datetime.date] = None,
                date_max: Optional[datetime.date] = None) -> pd.DataFrame:
    """Avis d'expédition d'un sens (ACHAT/VENTE), avec filtres numéro de BL,
    tiers, gestionnaire (via portefeuille) et plage de dates d'intégration.
    Renvoie numero_bl, nom_fournisseur, issuedatetime, integrationdate."""
    s = get_settings()
    conditions = ["sens = %(sens)s"]
    params: dict = {"sens": sens}
    if numero:
        conditions.append("lower(numero_bl) LIKE %(num)s")
        params["num"] = f"%{numero.lower()}%"
    if fournisseur:
        conditions.append("lower(nom_fournisseur) LIKE %(frs)s")
        params["frs"] = f"%{fournisseur.lower()}%"
    if gestionnaire:
        conditions.append(
            f"nom_fournisseur IN (SELECT nom_fournisseur FROM {s.pg_schema}.portefeuilles "
            "WHERE code_gestionnaire = %(gest)s)")
        params["gest"] = gestionnaire
    if date_min:
        conditions.append("integrationdate >= %(dmin)s")
        params["dmin"] = date_min
    if date_max:
        conditions.append("integrationdate <= %(dmax)s")
        params["dmax"] = date_max
    where = " AND ".join(conditions)
    return _run(
        f"SELECT numero_bl, nom_fournisseur, issuedatetime, integrationdate "
        f"FROM {s.pg_schema}.base_desadv WHERE {where} "
        "ORDER BY integrationdate DESC NULLS LAST, numero_bl",
        params=params, fetch=True)


def lire_portefeuilles(gestionnaire: str = "", fournisseur: str = "") -> pd.DataFrame:
    """Portefeuilles avec filtres gestionnaire et fournisseur."""
    s = get_settings()
    conditions = ["1=1"]
    params: dict = {}
    if gestionnaire:
        conditions.append("code_gestionnaire = %(gest)s")
        params["gest"] = gestionnaire
    if fournisseur:
        conditions.append("lower(nom_fournisseur) LIKE %(frs)s")
        params["frs"] = f"%{fournisseur.lower()}%"
    where = " AND ".join(conditions)
    return _run(
        f"SELECT code_gestionnaire, nom_fournisseur FROM {s.pg_schema}.portefeuilles "
        f"WHERE {where} ORDER BY code_gestionnaire, nom_fournisseur",
        params=params, fetch=True)


# ---------------------------------------------------------------------------
# Notifications (journal EDI NOK -> OK ; affichées en lecture dans l'app Admin)
# ---------------------------------------------------------------------------
def enregistrer_notification(type_notif: str, numero_bl: str, message: str,
                             utilisateur: str) -> None:
    s = get_settings()
    _run(
        f"INSERT INTO {s.pg_schema}.notifications (type_notif, numero_bl, message, cree_par) "
        "VALUES (%(t)s, %(num)s, %(msg)s, %(par)s)",
        params={"t": type_notif, "num": numero_bl, "msg": message, "par": utilisateur},
    )


def lister_notifications(limite: int = 200) -> pd.DataFrame:
    s = get_settings()
    return _run(
        f"SELECT cree_le, type_notif, numero_bl, message, cree_par, envoyee "
        f"FROM {s.pg_schema}.notifications ORDER BY cree_le DESC LIMIT %(lim)s",
        params={"lim": limite}, fetch=True)


# ---------------------------------------------------------------------------
# Tableau de bord (agrégats calculés côté app pour l'interactivité)
# ---------------------------------------------------------------------------
def lire_bl_pour_dashboard(date_min: Optional[datetime.date] = None,
                           date_max: Optional[datetime.date] = None) -> pd.DataFrame:
    """BL non supprimés (colonnes utiles au tableau de bord), filtrés sur la
    date d'opération. Les agrégats/KPI sont calculés dans l'app."""
    s = get_settings()
    conditions = ["(est_supprime IS NULL OR est_supprime = false)"]
    params: dict = {}
    if date_min:
        conditions.append("date_reception >= %(dmin)s")
        params["dmin"] = date_min
    if date_max:
        conditions.append("date_reception <= %(dmax)s")
        params["dmax"] = date_max
    where = " AND ".join(conditions)
    return _run(
        f"SELECT id_bl, numero_bl, date_reception, type_operation, statut_bl, "
        f"nom_fournisseur, saisie_le FROM {s.pg_schema}.suivi_bl WHERE {where}",
        params=params, fetch=True)


# ---------------------------------------------------------------------------
# Création d'un BL
# ---------------------------------------------------------------------------
def numero_bl_disponible(numero_bl: str) -> bool:
    """V3 : plus de suffixe automatique — un numéro déjà pris est refusé
    (comparaison insensible à la casse, BL supprimés inclus)."""
    s = get_settings()
    df = _run(
        f"SELECT 1 FROM {s.pg_schema}.suivi_bl WHERE upper(numero_bl) = upper(%(num)s) LIMIT 1",
        params={"num": numero_bl},
        fetch=True,
    )
    return df is None or df.empty


def inserer_bl(
    id_bl: str,
    numero_bl: str,
    nom_fournisseur: str,
    statut_bl: str,
    type_operation: str,
    utilisateur: str,
    date_reception: Optional[datetime.date] = None,
    quai_reception: Optional[str] = None,
    comment_bl: str = "",
    plage_horaire: Optional[str] = None,
) -> None:
    """Lève ValueError si le numéro de BL existe déjà (contrainte d'unicité :
    la vérification à la saisie ne suffit pas en cas de créations simultanées)."""
    s = get_settings()
    try:
        _run(
            f"""
            INSERT INTO {s.pg_schema}.suivi_bl
              (id_bl, numero_bl, date_reception, plage_horaire, nom_fournisseur, quai_reception,
               statut_bl, comment_bl, saisie_par, saisie_le, type_operation, est_supprime)
            VALUES
              (%(id)s, %(num)s, %(dr)s, %(plage)s, %(frs)s, %(quai)s,
               %(st)s, %(com)s, %(par)s, now(), %(op)s, false)
            """,
            params={
                "id": id_bl,
                "num": numero_bl,
                "dr": date_reception,
                "plage": plage_horaire,
                "frs": nom_fournisseur,
                "quai": quai_reception,
                "st": statut_bl,
                "com": comment_bl,
                "par": utilisateur,
                "op": type_operation,
            },
        )
    except psycopg.errors.UniqueViolation:
        raise ValueError(f"Le numéro de BL « {numero_bl} » existe déjà.") from None


def bl_existe(id_bl: str) -> bool:
    s = get_settings()
    df = _run(
        f"SELECT 1 FROM {s.pg_schema}.suivi_bl WHERE id_bl = %(id)s LIMIT 1",
        params={"id": id_bl},
        fetch=True,
    )
    return df is not None and not df.empty


def enregistrer_page(id_bl: str, index_page: int, image_bytes: bytes) -> None:
    """Insère une page scannée directement en base (colonne BYTEA)."""
    s = get_settings()
    id_photo = str(uuid.uuid4())
    _run(
        f"INSERT INTO {s.pg_schema}.pieces_jointes_bl (id_photo, id_bl, contenu, index_page) "
        "VALUES (%(idp)s, %(idb)s, %(contenu)s, %(idx)s)",
        params={"idp": id_photo, "idb": id_bl, "contenu": image_bytes, "idx": index_page},
    )


def pages_enregistrees(id_bl: str) -> set[int]:
    """Index des pages déjà en base — reprise idempotente après un échec."""
    s = get_settings()
    df = _run(
        f"SELECT index_page FROM {s.pg_schema}.pieces_jointes_bl WHERE id_bl = %(id)s",
        params={"id": id_bl},
        fetch=True,
    )
    return set(df["index_page"].tolist()) if df is not None else set()


# ---------------------------------------------------------------------------
# Recherche / lecture (app Administration)
# ---------------------------------------------------------------------------
def rechercher_bl(
    fournisseur: str = "",
    numero: str = "",
    types: Optional[list[str]] = None,
    date_min: Optional[datetime.date] = None,
    date_max: Optional[datetime.date] = None,
    statut: Optional[str] = None,
    gestionnaire: str = "",
    inclure_supprimes: bool = False,
    page: int = 1,
    page_size: int = 50,
) -> tuple[pd.DataFrame, int]:
    """Recherche multicritère insensible à la casse, paginée (50 par défaut).
    `types` restreint aux types d'opération donnés (vue achat / vue vente) ;
    `gestionnaire` filtre les BL dont le fournisseur est dans son portefeuille."""
    s = get_settings()
    conditions = ["1=1"]
    params: dict = {}

    if not inclure_supprimes:
        conditions.append("(est_supprime IS NULL OR est_supprime = false)")
    if types:
        conditions.append("type_operation = ANY(%(types)s)")
        params["types"] = list(types)
    if fournisseur:
        conditions.append("lower(nom_fournisseur) LIKE %(frs)s")
        params["frs"] = f"%{fournisseur.lower()}%"
    if gestionnaire:
        conditions.append(
            f"nom_fournisseur IN (SELECT nom_fournisseur FROM {s.pg_schema}.portefeuilles "
            "WHERE code_gestionnaire = %(gest)s)")
        params["gest"] = gestionnaire
    if numero:
        conditions.append("lower(numero_bl) LIKE %(num)s")
        params["num"] = f"%{numero.lower()}%"
    if date_min:
        conditions.append("date_reception >= %(dmin)s")
        params["dmin"] = date_min
    if date_max:
        conditions.append("date_reception <= %(dmax)s")
        params["dmax"] = date_max
    if statut in (STATUT_OK, STATUT_EDI_NOK):
        conditions.append("statut_bl = %(st)s")
        params["st"] = statut

    where = " AND ".join(conditions)

    df_total = _run(
        f"SELECT COUNT(*) AS n FROM {s.pg_schema}.suivi_bl WHERE {where}", params=params, fetch=True
    )
    total = int(df_total["n"].iloc[0]) if df_total is not None else 0

    params_page = dict(params)
    params_page["lim"] = page_size
    params_page["off"] = max(page - 1, 0) * page_size
    df = _run(
        f"""
        SELECT id_bl, numero_bl, date_reception, plage_horaire, nom_fournisseur, quai_reception,
               statut_bl, comment_bl, saisie_par, saisie_le, modifie_par, modifie_le,
               type_operation, est_supprime
        FROM {s.pg_schema}.suivi_bl
        WHERE {where}
        ORDER BY saisie_le DESC
        LIMIT %(lim)s OFFSET %(off)s
        """,
        params=params_page,
        fetch=True,
    )
    return (df if df is not None else pd.DataFrame()), total


def photos_pour_bls(ids_bl: list[str]) -> dict[str, list[str]]:
    """Identifiants des photos des BL affichés, en une seule requête."""
    if not ids_bl:
        return {}
    s = get_settings()
    params = {f"id_{i}": v for i, v in enumerate(ids_bl)}
    placeholders = ", ".join(f"%({k})s" for k in params)
    df = _run(
        f"SELECT id_bl, id_photo, index_page FROM {s.pg_schema}.pieces_jointes_bl "
        f"WHERE id_bl IN ({placeholders}) ORDER BY index_page",
        params=params,
        fetch=True,
    )
    if df is None or df.empty:
        return {}
    return df.groupby("id_bl")["id_photo"].apply(list).to_dict()


@st.cache_data(ttl=3600, show_spinner=False, max_entries=200)
def telecharger_photo(id_photo: str) -> bytes:
    """Octets d'une photo stockée en base, en cache."""
    s = get_settings()
    df = _run(
        f"SELECT contenu FROM {s.pg_schema}.pieces_jointes_bl WHERE id_photo = %(id)s",
        params={"id": id_photo},
        fetch=True,
    )
    if df is None or df.empty:
        raise ValueError(f"Photo introuvable : {id_photo}")
    return bytes(df["contenu"].iloc[0])


# ---------------------------------------------------------------------------
# Mise à jour / suppression logique (app Administration)
# ---------------------------------------------------------------------------
CHAMPS_MODIFIABLES = {"numero_bl", "date_reception", "plage_horaire", "nom_fournisseur",
                      "quai_reception", "statut_bl", "comment_bl"}


def mettre_a_jour_bl(id_bl: str, champs: dict, utilisateur: str) -> None:
    """UPDATE des seuls champs autorisés (liste blanche), avec traçabilité.
    Lève ValueError si le nouveau numéro de BL est déjà pris."""
    a_modifier = {k: v for k, v in champs.items() if k in CHAMPS_MODIFIABLES}
    if not a_modifier:
        return
    s = get_settings()
    set_clause = ", ".join(f"{k} = %({k})s" for k in a_modifier)
    params = dict(a_modifier)
    params["id"] = id_bl
    params["par"] = utilisateur
    try:
        _run(
            f"UPDATE {s.pg_schema}.suivi_bl SET {set_clause}, "
            "modifie_par = %(par)s, modifie_le = now() "
            "WHERE id_bl = %(id)s",
            params=params,
        )
    except psycopg.errors.UniqueViolation:
        raise ValueError(f"Le numéro de BL « {champs.get('numero_bl', '')} » existe déjà.") from None


def supprimer_bl(id_bl: str, utilisateur: str) -> None:
    """Suppression LOGIQUE : le BL et ses images restent en base."""
    s = get_settings()
    _run(
        f"UPDATE {s.pg_schema}.suivi_bl SET est_supprime = true, "
        "supprime_par = %(par)s, supprime_le = now() "
        "WHERE id_bl = %(id)s",
        params={"id": id_bl, "par": utilisateur},
    )


def restaurer_bl(id_bl: str, utilisateur: str) -> None:
    s = get_settings()
    _run(
        f"UPDATE {s.pg_schema}.suivi_bl SET est_supprime = false, "
        "modifie_par = %(par)s, modifie_le = now() "
        "WHERE id_bl = %(id)s",
        params={"id": id_bl, "par": utilisateur},
    )
