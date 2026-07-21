"""Aides d'interface communes aux deux applications."""

import logging
import os
import sys

import streamlit as st

from . import repository


def configurer_logs() -> None:
    """Logs structurés vers stdout : repris par `databricks apps logs` et par la
    télémétrie OTEL de Databricks Apps si elle est activée sur l'app."""
    if not logging.getLogger().handlers:
        logging.basicConfig(
            stream=sys.stdout,
            level=logging.INFO,
            format='{"ts":"%(asctime)s","niveau":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
        )


def injecter_style() -> None:
    """Habillage visuel commun aux deux applications, à appeler juste après
    st.set_page_config. Complète le thème déclaré dans .streamlit/config.toml
    (couleurs de base) : ici, uniquement du polish — cartes, boutons, titres."""
    st.markdown(
        """
        <style>
        /* Titre principal : plus grand, graisse forte + soulignement dégradé */
        [data-testid="stAppViewContainer"] h1 {
            font-weight: 800;
            font-size: 2.45rem;
            letter-spacing: -0.02em;
            padding-bottom: 0.4rem;
            background: linear-gradient(90deg, #0F62A6, #43B02A)
                        bottom left / 120px 5px no-repeat;
        }
        /* Boutons : coins arrondis, relief léger au survol */
        .stButton > button, [data-testid="stFormSubmitButton"] > button {
            border-radius: 10px;
            font-weight: 600;
            transition: transform 0.08s ease, box-shadow 0.15s ease;
        }
        .stButton > button:hover, [data-testid="stFormSubmitButton"] > button:hover {
            transform: translateY(-1px);
            box-shadow: 0 4px 14px rgba(15, 98, 166, 0.25);
        }
        /* Barre de progression du wizard en dégradé */
        .stProgress > div > div > div {
            background: linear-gradient(90deg, #0F62A6, #4FA3E3);
        }
        /* Conteneurs bordés et expanders en "cartes" */
        [data-testid="stExpander"], div[data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 12px;
        }
        [data-testid="stExpander"] {
            border: 1px solid #E3E9F2;
            box-shadow: 0 1px 4px rgba(27, 42, 58, 0.06);
        }
        /* Champs de saisie adoucis */
        .stTextInput input, .stTextArea textarea, .stDateInput input,
        [data-baseweb="select"] > div {
            border-radius: 8px;
        }
        /* Tableau du récapitulatif : lignes aérées */
        [data-testid="stMarkdownContainer"] table { width: 100%; }
        [data-testid="stMarkdownContainer"] td { padding: 0.45rem 0.6rem; }
        /* Pied de page Streamlit masqué (application métier) */
        footer { visibility: hidden; }
        /* Navigation latérale type "model-driven" : fond sombre, items nets */
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #10263C 0%, #16334F 100%);
        }
        [data-testid="stSidebar"] * { color: #E8EFF7 !important; }
        [data-testid="stSidebar"] hr { border-color: rgba(232, 239, 247, 0.22); margin: 0.5rem 0; }
        /* Navigation en arbre : chaque item est un bouton pleine largeur, aligné
           à gauche, police plus grande. L'item actif est surligné (barre verte
           à gauche). Les vues sont indentées sous leur module. */
        [data-testid="stSidebar"] .stButton > button {
            background: transparent;
            border: none;
            box-shadow: none !important;
            color: #E8EFF7;
            text-align: left;
            justify-content: flex-start;
            font-size: 1.18rem;
            font-weight: 600;
            padding: 0.52rem 0.6rem;
            margin: 0.06rem 0;
            border-radius: 9px;
            width: 100%;
        }
        [data-testid="stSidebar"] .stButton > button:hover {
            background: rgba(255, 255, 255, 0.09);
            transform: none;
        }
        [data-testid="stSidebar"] .stButton > button[kind="primary"] {
            background: rgba(67, 176, 42, 0.20) !important;
            color: #FFFFFF !important;
            font-weight: 800;
            box-shadow: inset 3px 0 0 #43B02A !important;
        }
        /* Grilles de données : cadre net */
        [data-testid="stDataFrame"], [data-testid="stDataEditor"] {
            border: 1px solid #E3E9F2;
            border-radius: 10px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# Logo eMotors — recréation SVG fidèle du logo officiel : marque « E »
# anguleux (arms à droite coupés en biais vers l'avant, arm central plus court)
# + mot « EMOTORS », E vert. Version claire (blanc/vert) pour la barre latérale
# sombre. Remplaçable par le SVG officiel (garder l'appel afficher_logo()).
_NAVY = "#0B1B3A"
_VERT = "#43B02A"
LOGO_EMOTORS_SVG = """
<svg viewBox="0 0 214 200" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="eMotors"
     style="width:82%;max-width:190px;height:auto;display:block;margin:0.3rem auto 0.5rem;">
  <path transform="translate(52,4)" fill="#FFFFFF" d="
    M6 6 L104 6 L82 32 L30 32 L30 48 L92 48 L74 66 L30 66 L30 84 L100 84
    L78 110 L6 110 Z"/>
  <text x="107" y="188" text-anchor="middle" font-family="Segoe UI, Arial, sans-serif"
        font-size="41" font-weight="800" letter-spacing="-1.5">
    <tspan fill="#43B02A">E</tspan><tspan fill="#FFFFFF">MOTORS</tspan>
  </text>
</svg>
"""


LOGO_PATH = "logo.png"


def afficher_logo() -> None:
    """Logo eMotors en haut de la barre latérale (haut à gauche de l'app).
    Utilise le fichier officiel logo.png s'il est présent dans le dossier de
    l'app, sinon la recréation SVG (repli sur fond sombre)."""
    if os.path.exists(LOGO_PATH):
        st.image(LOGO_PATH, use_column_width=True)
    else:
        st.markdown(
            f'<div style="padding:0.2rem 0 0.5rem;">{LOGO_EMOTORS_SVG}</div>',
            unsafe_allow_html=True,
        )


def entete_app(titre: str, icone: str = "🗂️") -> None:
    """Grand titre de l'application avec icône de dossier numérisé."""
    st.markdown(f"# {icone} {titre}")


# --- Messages "flash" : survivent à un st.rerun (sinon le message disparaît
# avant que l'utilisateur ait pu le lire). ---
def set_flash(kind: str, message: str) -> None:
    st.session_state["flash"] = (kind, message)


def show_flash() -> None:
    flash = st.session_state.pop("flash", None)
    if flash:
        kind, message = flash
        getattr(st, kind)(message)


def libelle_statut(statut_bl: str) -> str:
    return "✅ OK" if statut_bl == repository.STATUT_OK else "🟥 EDI NOK"


def afficher_photo_volume(id_photo: str) -> None:
    """Affiche une page stockée dans Lakebase (téléchargée via le repository,
    en cache). Nom conservé de la V1 pour ne pas toucher aux applications."""
    try:
        st.image(repository.telecharger_photo(id_photo), use_column_width=True)
    except Exception as e:
        st.caption(f"Image inaccessible : {e}")


def afficher_miniatures(pages: list[bytes]) -> None:
    """Miniatures des pages en attente (max 4 par ligne pour rester lisible sur mobile)."""
    for debut in range(0, len(pages), 4):
        cols = st.columns(4)
        for i, img in enumerate(pages[debut : debut + 4]):
            with cols[i]:
                st.image(img, caption=f"Page {debut + i + 1}", use_column_width=True)
