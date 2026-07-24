"""Contrôle d'accès basé sur les rôles (RBAC).

Les RÔLES d'un utilisateur (email Databricks) sont lus dans la table
`roles_utilisateurs` (gérée dans l'app Administration, Gestion ▸ Rôles).
La MATRICE des droits par vue est portée ici, dans le code : elle change avec
les évolutions fonctionnelles de la solution et est donc versionnée avec elle.

Niveaux : AUCUN (vue masquée), LECTURE (consultation seule),
MODIFICATION (toutes les actions). Mode ouvert : tant que la table des rôles
est vide (ou absente), les apps donnent l'accès complet — le RBAC s'active à
la première ligne insérée. Un utilisateur sans rôle, RBAC actif, ne voit rien.
"""

from . import repository

ROLE_LOG = "LOG"
ROLE_APPROS = "APPROS"
ROLE_ADV = "ADV"
ROLE_FINANCE = "FINANCE"
ROLE_ADMIN = "ADMIN_METIER"
ROLES = [ROLE_LOG, ROLE_APPROS, ROLE_ADV, ROLE_FINANCE, ROLE_ADMIN]

AUCUN, LECTURE, MODIFICATION = "aucun", "lecture", "modification"
_ORDRE = {AUCUN: 0, LECTURE: 1, MODIFICATION: 2}

# --- App Création : rôles autorisés par type d'opération (matrice RBAC). ---
OPERATIONS_CREATION = {
    repository.TYPE_RECEPTION: {ROLE_LOG, ROLE_ADMIN},
    repository.TYPE_EXPEDITION: {ROLE_LOG, ROLE_ADMIN},
    repository.TYPE_ARCHIVAGE_RECEPTION: {ROLE_APPROS, ROLE_ADMIN},
    repository.TYPE_ARCHIVAGE_EXPEDITION: {ROLE_ADV, ROLE_ADMIN},
}

# --- App Administration : niveau par vue et par rôle (matrice RBAC ;
# Fournisseurs et Clients sont désormais dans Gestion, droits inchangés). ---
VUES_ADMINISTRATION = {
    "Tableau de bord": {ROLE_APPROS: LECTURE, ROLE_ADV: LECTURE,
                        ROLE_FINANCE: LECTURE, ROLE_ADMIN: MODIFICATION},
    "BL réception": {ROLE_APPROS: MODIFICATION, ROLE_FINANCE: LECTURE,
                     ROLE_ADMIN: MODIFICATION},
    "DESADV achat": {ROLE_APPROS: LECTURE, ROLE_ADMIN: MODIFICATION},
    "Rapprochement achat": {ROLE_APPROS: LECTURE, ROLE_FINANCE: LECTURE,
                            ROLE_ADMIN: MODIFICATION},
    "BL expédition": {ROLE_ADV: MODIFICATION, ROLE_FINANCE: LECTURE,
                      ROLE_ADMIN: MODIFICATION},
    "DESADV vente": {ROLE_ADV: LECTURE, ROLE_ADMIN: MODIFICATION},
    "Rapprochement vente": {ROLE_ADV: LECTURE, ROLE_FINANCE: LECTURE,
                            ROLE_ADMIN: MODIFICATION},
    "Fournisseurs": {ROLE_ADMIN: MODIFICATION},
    "Clients": {ROLE_ADMIN: MODIFICATION},
    "Notifications": {ROLE_APPROS: LECTURE, ROLE_ADV: LECTURE, ROLE_ADMIN: LECTURE},
    # « Tout le reste » du module Gestion : administrateurs métier uniquement.
    "Gestionnaires": {ROLE_ADMIN: MODIFICATION},
    "Portefeuilles": {ROLE_ADMIN: MODIFICATION},
    "Quais": {ROLE_ADMIN: MODIFICATION},
    "Adresses": {ROLE_ADMIN: MODIFICATION},
    "Sites logistiques": {ROLE_ADMIN: MODIFICATION},
    "PLA": {ROLE_ADMIN: MODIFICATION},
    "Rôles": {ROLE_ADMIN: MODIFICATION},
    "Qualité IA": {ROLE_ADMIN: MODIFICATION},
}


def contexte_rbac(utilisateur: str) -> dict:
    """{'actif': bool, 'roles': [...]} — en mode ouvert (table vide/absente),
    actif=False et tout est autorisé."""
    try:
        actif = repository.rbac_actif()
        roles = repository.roles_utilisateur(utilisateur) if actif else []
    except Exception:
        actif, roles = False, []
    return {"actif": actif, "roles": roles}


def niveau_vue(vue: str, ctx: dict) -> str:
    """Niveau d'accès de l'utilisateur sur une vue de l'app Administration."""
    if not ctx["actif"]:
        return MODIFICATION
    droits = VUES_ADMINISTRATION.get(vue, {})
    niveaux = [droits.get(r, AUCUN) for r in ctx["roles"]] or [AUCUN]
    return max(niveaux, key=_ORDRE.get)


def operations_autorisees(ctx: dict) -> list[str]:
    """Types d'opération de l'app Création accessibles à l'utilisateur."""
    if not ctx["actif"]:
        return list(OPERATIONS_CREATION)
    return [t for t, roles in OPERATIONS_CREATION.items()
            if roles & set(ctx["roles"])]
