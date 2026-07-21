"""Application « Administration des BL » — V3.

Expérience structurée type « model-driven » (à la Power Apps) :
  - logo eMotors et navigation latérale : Tableau de bord, puis modules
    Achat / Vente / Gestion avec leurs vues indentées ;
  - tableau de bord interactif (KPI + graphiques filtrables) ;
  - ruban d'actions contextuel au-dessus de chaque grille ;
  - grille de données avec cases à cocher (actions de masse) ou édition
    directe (référentiels, CRUD complet) ;
  - notifications EDI NOK -> OK journalisées en base et affichées en lecture.
"""

import datetime

import altair as alt
import pandas as pd
import streamlit as st

from bl_core import repository, ui
from bl_core.identity import get_current_user

st.set_page_config(page_title="Administration BL", page_icon="🗂️", layout="wide")

ui.configurer_logs()
ui.injecter_style()

utilisateur = get_current_user()
TAILLE_PAGE = 50
boite_dialogue = getattr(st, "dialog", None) or st.experimental_dialog

ESPACE_DASHBOARD = "📊 Tableau de bord"
MODULES = {
    "Achat": ["BL réception", "DESADV achat", "Fournisseurs"],
    "Vente": ["BL expédition", "DESADV vente", "Clients"],
    "Gestion": ["Gestionnaires", "Portefeuilles", "Quais", "Notifications"],
}
ICONES = {"Achat": "🛒", "Vente": "🚚", "Gestion": "⚙️"}
LABELS_MODULE = {f"{ICONES[m]} {m}": m for m in MODULES}


def _vider_grille(cle: str) -> None:
    st.session_state.pop(cle, None)


def _journaliser_passage_ok(numero_bl, fournisseur, quai, date_reception) -> None:
    """Journalise le passage EDI NOK -> OK dans la table notifications (à la
    place de l'ancien envoi d'email — un flux Power Automate pourra l'envoyer)."""
    message = (f"BL {numero_bl} ({fournisseur or '—'}, quai {quai or '—'}, "
               f"reçu le {date_reception or '—'}) : état passé de EDI NOK à OK "
               f"par {utilisateur}.")
    repository.enregistrer_notification("EDI_NOK_OK", numero_bl, message, utilisateur)


# =====================================================================
# NAVIGATION LATÉRALE — arbre : modules, avec vues indentées sous le module
# sélectionné (chaque item est un bouton ; l'actif est surligné).
# =====================================================================
st.session_state.setdefault("nav_module", None)   # None = Tableau de bord
st.session_state.setdefault("nav_vue", None)


def _nav_bouton(label: str, actif: bool, key: str, indent: bool = False) -> bool:
    conteneur = st
    if indent:
        _, conteneur = st.columns([1, 13])
    return conteneur.button(label, key=key, use_container_width=True,
                            type="primary" if actif else "secondary")


with st.sidebar:
    ui.afficher_logo()
    st.divider()
    dash_actif = st.session_state.nav_module is None
    if _nav_bouton(f"{'●' if dash_actif else '○'}  {ESPACE_DASHBOARD}", dash_actif, "nav_dash"):
        st.session_state.nav_module = None
        st.rerun()
    for m in MODULES:
        m_actif = st.session_state.nav_module == m
        if _nav_bouton(f"{'●' if m_actif else '○'}  {ICONES[m]} {m}", m_actif, f"nav_m_{m}"):
            st.session_state.nav_module = m
            st.session_state.nav_vue = MODULES[m][0]
            st.rerun()
        if m_actif:
            for v in MODULES[m]:
                v_actif = st.session_state.nav_vue == v
                if _nav_bouton(f"{'●' if v_actif else '○'}  {v}", v_actif, f"nav_v_{m}_{v}",
                               indent=True):
                    st.session_state.nav_vue = v
                    st.rerun()
    st.divider()
    st.caption(f"👤 {utilisateur}")

module = st.session_state.nav_module
vue = st.session_state.nav_vue if module else None
espace = ESPACE_DASHBOARD if module is None else f"{ICONES[module]} {module}"

ui.entete_app("Administration des BL")
ui.show_flash()


# =====================================================================
# TABLEAU DE BORD
# =====================================================================
def render_dashboard() -> None:
    st.markdown("### 📊 Tableau de bord")
    ajd = repository.maintenant_local().date()
    c1, c2, c3 = st.columns([2, 2, 2])
    dmin = c1.date_input("Du", value=ajd - datetime.timedelta(days=30))
    dmax = c2.date_input("Au", value=ajd)
    portee = c3.selectbox("Périmètre", ["Tous", "Achat", "Vente"])
    c4, c5 = st.columns([3, 2])
    f_tiers = c4.text_input("Fournisseur / client contient", key="dash_tiers").strip()
    gest_options = [""] + repository.lister_gestionnaires()
    f_gest = c5.selectbox("Gestionnaire", gest_options,
                          format_func=lambda g: g or "Tous", key="dash_gest")

    try:
        df = repository.lire_bl_pour_dashboard(dmin, dmax).reset_index(drop=True)
    except Exception as e:
        st.error(f"Erreur de lecture de la base : {e}")
        st.stop()

    if portee == "Achat":
        df = df[df["type_operation"].isin(repository.TYPES_ACHAT)]
    elif portee == "Vente":
        df = df[df["type_operation"].isin(repository.TYPES_VENTE)]
    if f_tiers:
        df = df[df["nom_fournisseur"].fillna("").str.lower().str.contains(f_tiers.lower())]
    if f_gest:
        frs_gest = set(repository.lire_portefeuilles(gestionnaire=f_gest)["nom_fournisseur"])
        df = df[df["nom_fournisseur"].isin(frs_gest)]

    total = len(df)
    est = df["type_operation"]
    nb_rec = int((est == repository.TYPE_RECEPTION).sum())
    nb_exp = int((est == repository.TYPE_EXPEDITION).sum())
    nb_arch = int(est.isin([repository.TYPE_ARCHIVAGE_RECEPTION,
                            repository.TYPE_ARCHIVAGE_EXPEDITION]).sum())
    nb_ednok = int(((est == repository.TYPE_RECEPTION) &
                    (df["statut_bl"] == repository.STATUT_EDI_NOK)).sum())
    taux = f"{100 * nb_ednok / nb_rec:.0f} %" if nb_rec else "—"

    k = st.columns(6)
    k[0].metric("BL (total)", total)
    k[1].metric("Réceptions", nb_rec)
    k[2].metric("Expéditions", nb_exp)
    k[3].metric("Archivages", nb_arch)
    k[4].metric("EDI NOK", nb_ednok)
    k[5].metric("Taux EDI NOK", taux)

    if df.empty:
        st.info("Aucun BL sur la période sélectionnée.")
        return

    st.markdown("#### Volume par jour")
    tmp = df.dropna(subset=["date_reception"]).copy()
    tmp["Jour"] = pd.to_datetime(tmp["date_reception"]).dt.date
    tmp["Sens"] = tmp["type_operation"].map(
        lambda t: "Achat" if t in repository.TYPES_ACHAT else "Vente")
    par_jour = (tmp.groupby(["Jour", "Sens"]).size().unstack(fill_value=0)
                .reindex(columns=["Achat", "Vente"], fill_value=0).sort_index())
    st.bar_chart(par_jour, color=["#0F62A6", "#43B02A"])

    col_g, col_d = st.columns([3, 1])           # Top tiers plus large
    with col_g:
        st.markdown("#### Top fournisseurs / clients")
        top_df = (df["nom_fournisseur"].fillna("—").value_counts().head(10)
                  .rename_axis("Tiers").reset_index(name="BL"))
        # Altair : axe Y agrandi + labels non tronqués (désignations longues).
        chart = (
            alt.Chart(top_df).mark_bar(color="#0F62A6", cornerRadiusEnd=3).encode(
                x=alt.X("BL:Q", title="Nombre de BL"),
                y=alt.Y("Tiers:N", sort="-x", title=None,
                        axis=alt.Axis(labelFontSize=15, labelLimit=360)),
                tooltip=["Tiers", "BL"],
            ).properties(height=max(220, 34 * len(top_df)))
        )
        st.altair_chart(chart, use_container_width=True)
    with col_d:
        st.markdown("#### OK vs EDI NOK")
        rec = df[df["type_operation"] == repository.TYPE_RECEPTION]
        if rec.empty:
            st.caption("Aucune réception sur la période.")
        else:
            etat = (rec["statut_bl"].map({repository.STATUT_OK: "OK",
                                          repository.STATUT_EDI_NOK: "EDI NOK"})
                    .fillna("—").value_counts().rename_axis("État").rename("BL").to_frame())
            st.bar_chart(etat, horizontal=True, color="#E4572E")


# =====================================================================
# BOÎTES DE DIALOGUE (fiche BL, confirmation de suppression)
# =====================================================================
@boite_dialogue("✏️ Fiche du BL")
def dialog_modifier_bl(bl: dict, ids_photos: list[str], cle_grille: str):
    type_op = bl.get("type_operation") or repository.TYPE_RECEPTION
    avec_pq = repository.operation_avec_plage_et_quai(type_op)
    avec_st = repository.operation_avec_statut(type_op)
    tiers_lib = repository.libelle_tiers(type_op)
    type_tiers = (repository.TIERS_CLIENT if type_op in repository.TYPES_VENTE
                  else repository.TIERS_FOURNISSEUR)

    st.caption(f"{repository.LIBELLES_OPERATION.get(type_op, type_op)} · "
               f"saisi par {bl.get('saisie_par') or '?'} le {bl.get('saisie_le') or '?'}")

    with st.form("fiche_bl"):
        numero = st.text_input("Numéro de BL", value=bl["numero_bl"], max_chars=60)
        date_op = st.date_input("Date", value=bl.get("date_reception"))
        tiers_options = repository.lister_tiers(type_tiers)
        index_tiers = (tiers_options.index(bl["nom_fournisseur"])
                       if bl.get("nom_fournisseur") in tiers_options else None)
        nouveau_tiers = st.selectbox(tiers_lib, options=tiers_options, index=index_tiers,
                                     placeholder="Choisir…")
        if avec_pq:
            index_plage = (repository.PLAGES_HORAIRES.index(bl["plage_horaire"])
                           if bl.get("plage_horaire") in repository.PLAGES_HORAIRES else None)
            plage = st.selectbox("Plage horaire", options=repository.PLAGES_HORAIRES,
                                 index=index_plage, placeholder="Non renseignée")
            quais = repository.lister_quais()
            index_quai = quais.index(bl["quai_reception"]) if bl.get("quai_reception") in quais else None
            quai = st.selectbox("Quai", options=quais, index=index_quai, placeholder="Non renseigné")
            commentaire = st.text_area("Commentaire", value=bl.get("comment_bl") or "", max_chars=1000)
        if avec_st:
            statut_choix = st.radio("État de réception", ["OK", "EDI NOK"], horizontal=True,
                                    index=0 if bl.get("statut_bl") == repository.STATUT_OK else 1)

        if st.form_submit_button("💾 Enregistrer", type="primary", use_container_width=True):
            champs = {"numero_bl": numero.strip(), "date_reception": date_op,
                      "nom_fournisseur": nouveau_tiers}
            if avec_pq:
                champs["comment_bl"] = commentaire.strip()
                if plage:
                    champs["plage_horaire"] = plage
                if quai:
                    champs["quai_reception"] = quai
            passe_a_ok = False
            if avec_st:
                champs["statut_bl"] = (repository.STATUT_OK if statut_choix == "OK"
                                       else repository.STATUT_EDI_NOK)
                passe_a_ok = (bl.get("statut_bl") == repository.STATUT_EDI_NOK
                              and champs["statut_bl"] == repository.STATUT_OK)
            try:
                repository.mettre_a_jour_bl(bl["id_bl"], champs, utilisateur)
            except ValueError as e:            # numéro de BL déjà pris
                st.error(str(e))
                st.stop()
            if passe_a_ok:
                _journaliser_passage_ok(champs["numero_bl"], nouveau_tiers,
                                        champs.get("quai_reception"), date_op)
                ui.set_flash("success", f"BL {champs['numero_bl']} mis à jour — "
                                        "passage à OK journalisé (Gestion ▸ Notifications).")
            else:
                ui.set_flash("success", f"BL {champs['numero_bl']} mis à jour.")
            _vider_grille(cle_grille)
            st.rerun()

    if ids_photos:
        with st.expander(f"📎 Pages ({len(ids_photos)})"):
            for i, id_photo in enumerate(ids_photos):
                try:
                    st.image(repository.telecharger_photo(id_photo), caption=f"Page {i + 1}",
                             use_column_width=True)
                except Exception as e:
                    st.caption(f"Page {i + 1} inaccessible : {e}")


@boite_dialogue("🖼️ Pages du BL")
def dialog_voir_images(numero_bl: str, ids_photos: list[str]):
    st.caption(f"BL {numero_bl} — {len(ids_photos)} page(s)")
    if not ids_photos:
        st.info("Aucune page attachée à ce BL.")
        return
    if len(ids_photos) == 1:
        _afficher_page(ids_photos[0], 1)
    else:
        onglets = st.tabs([f"Page {i + 1}" for i in range(len(ids_photos))])
        for i, (onglet, id_photo) in enumerate(zip(onglets, ids_photos)):
            with onglet:
                _afficher_page(id_photo, i + 1)


def _afficher_page(id_photo: str, numero: int) -> None:
    try:
        st.image(repository.telecharger_photo(id_photo), use_column_width=True)
    except Exception as e:
        st.caption(f"Page {numero} inaccessible : {e}")


@boite_dialogue("🗑️ Confirmation")
def dialog_supprimer_bls(ids: list[str], cle_grille: str):
    st.warning(f"Supprimer logiquement {len(ids)} BL ? Ils resteront restaurables "
               "(case « Inclure les BL supprimés »).")
    col_oui, col_non = st.columns(2)
    if col_oui.button("✅ Confirmer la suppression", type="primary", use_container_width=True):
        for id_bl in ids:
            repository.supprimer_bl(id_bl, utilisateur)
        ui.set_flash("success", f"{len(ids)} BL supprimé(s) logiquement.")
        _vider_grille(cle_grille)
        st.rerun()
    if col_non.button("Annuler", use_container_width=True):
        st.rerun()


# =====================================================================
# VUES « BL » (réception / expédition) — grille + ruban d'actions
# =====================================================================
def vue_bl(nom_vue: str, types: list[str]) -> None:
    avec_statut = repository.TYPE_RECEPTION in types
    achat = types == repository.TYPES_ACHAT
    tiers_lib = "Fournisseur" if achat else "Client"

    # --- Filtres ---
    with st.expander("🔍 Filtres", expanded=False):
        c1, c2, c3 = st.columns(3)
        f_numero = c1.text_input("Numéro contient", key=f"f_num_{nom_vue}").strip()
        f_tiers = c2.text_input(f"{tiers_lib} contient", key=f"f_frs_{nom_vue}").strip()
        aujourdhui = repository.maintenant_local().date()
        f_dmin = c1.date_input("Du", value=aujourdhui - datetime.timedelta(days=1),
                               key=f"f_dmin_{nom_vue}")
        f_dmax = c2.date_input("Au", value=aujourdhui, key=f"f_dmax_{nom_vue}")
        f_statut = (c3.selectbox("État", ["EDI NOK", "OK", "Tous"], key=f"f_st_{nom_vue}")
                    if avec_statut else "Tous")
        if achat:
            gest_options = [""] + repository.lister_gestionnaires()
            f_gest = c3.selectbox("Gestionnaire", gest_options,
                                  format_func=lambda g: g or "Tous", key=f"f_gest_{nom_vue}")
        else:
            f_gest = ""
        f_suppr = c3.checkbox("Inclure les BL supprimés", key=f"f_sup_{nom_vue}")
    statut = {"OK": repository.STATUT_OK, "EDI NOK": repository.STATUT_EDI_NOK}.get(f_statut)

    # Pagination et sélection réinitialisées quand les filtres changent.
    signature = (f_numero, f_tiers, str(f_dmin), str(f_dmax), f_statut, f_gest, f_suppr)
    cle_page, cle_grille = f"page_{nom_vue}", f"grille_{nom_vue}"
    if st.session_state.get(f"sig_{nom_vue}") != signature:
        st.session_state[f"sig_{nom_vue}"] = signature
        st.session_state[cle_page] = 1
        _vider_grille(cle_grille)
    page = st.session_state.setdefault(cle_page, 1)

    try:
        df, total = repository.rechercher_bl(
            numero=f_numero, fournisseur=f_tiers, types=types,
            date_min=f_dmin, date_max=f_dmax, statut=statut, gestionnaire=f_gest,
            inclure_supprimes=f_suppr, page=page, page_size=TAILLE_PAGE,
        )
        df = df.reset_index(drop=True)
        photos = repository.photos_pour_bls(df["id_bl"].tolist() if not df.empty else [])
    except Exception as e:
        st.error(f"Erreur de lecture de la base : {e}")
        st.stop()

    ruban = st.container()                     # rempli après la grille (sélection à jour)

    # --- Grille ---
    ids_selection: list[str] = []
    if df.empty:
        st.info("Aucun BL ne correspond aux filtres.")
    else:
        colonnes = {
            "Sélection": [False] * len(df),
            "Numéro": df["numero_bl"],
            "Date": df["date_reception"],
            "Plage": df["plage_horaire"],
            tiers_lib: df["nom_fournisseur"],
            "Quai": df["quai_reception"],
        }
        if avec_statut:
            colonnes["État"] = df["statut_bl"].map(ui.libelle_statut)
        colonnes.update({
            "Opération": df["type_operation"].map(
                lambda t: repository.LIBELLES_OPERATION.get(t, t)),
            "Commentaire": df["comment_bl"],
            "Pages": df["id_bl"].map(lambda i: len(photos.get(i, []))),
            "Saisi par": df["saisie_par"],
            "Saisi le": df["saisie_le"],
            "Supprimé": df["est_supprime"].fillna(False).map(lambda x: "🗑️" if x else ""),
        })
        df_aff = pd.DataFrame(colonnes)
        edite = st.data_editor(
            df_aff, hide_index=True, use_container_width=True, key=cle_grille,
            disabled=[c for c in df_aff.columns if c != "Sélection"],
            column_config={"Sélection": st.column_config.CheckboxColumn("✔", width="small")},
        )
        masque = edite["Sélection"].fillna(False).astype(bool)
        ids_selection = df.loc[masque.values, "id_bl"].tolist()

    # --- Pagination (50 lignes par page) ---
    nb_pages = max((total + TAILLE_PAGE - 1) // TAILLE_PAGE, 1)
    if nb_pages > 1:
        col_prec, col_info, col_suiv = st.columns([1, 2, 1])
        if col_prec.button("⬅️", disabled=page <= 1, key=f"prec_{nom_vue}", use_container_width=True):
            st.session_state[cle_page] -= 1
            _vider_grille(cle_grille)
            st.rerun()
        col_info.markdown(f"<div style='text-align:center'>page {page} / {nb_pages}</div>",
                          unsafe_allow_html=True)
        if col_suiv.button("➡️", disabled=page >= nb_pages, key=f"suiv_{nom_vue}",
                           use_container_width=True):
            st.session_state[cle_page] += 1
            _vider_grille(cle_grille)
            st.rerun()

    # --- Ruban d'actions contextuel ---
    with ruban:
        n = len(ids_selection)
        specs = [
            ("🔄 Actualiser", "act", False, 1.3),
            ("✏️ Modifier", "mod", n != 1, 1.3),
            ("🖼️ Voir les images", "img", n != 1, 1.9),
        ]
        if avec_statut:
            specs.append(("✅ Passer à OK", "ok", n == 0, 1.5))
        specs += [("🗑️ Supprimer", "sup", n == 0, 1.4),
                  ("♻️ Restaurer", "res", n == 0, 1.4)]
        cols = st.columns([s[3] for s in specs] + [2.6])
        clics = {}
        for i, (label, code, disabled, _) in enumerate(specs):
            aide = ("Sélectionnez exactement un BL." if code in ("mod", "img")
                    else "Passe les BL EDI NOK sélectionnés à OK." if code == "ok" else None)
            clics[code] = cols[i].button(label, key=f"{code}_{nom_vue}", disabled=disabled,
                                         use_container_width=True, help=aide)
        cols[-1].markdown(f"**{total}** BL · **{n}** sélectionné(s)")

        if clics["act"]:
            _vider_grille(cle_grille)
            st.rerun()
        if clics["mod"]:
            ligne = df[df["id_bl"] == ids_selection[0]].iloc[0].to_dict()
            dialog_modifier_bl(ligne, photos.get(ids_selection[0], []), cle_grille)
        if clics["img"]:
            ligne = df[df["id_bl"] == ids_selection[0]].iloc[0]
            dialog_voir_images(ligne["numero_bl"], photos.get(ids_selection[0], []))
        if avec_statut and clics.get("ok"):
            bascules = 0
            for id_bl in ids_selection:
                ligne = df[df["id_bl"] == id_bl].iloc[0]
                if ligne["statut_bl"] != repository.STATUT_EDI_NOK:
                    continue
                repository.mettre_a_jour_bl(id_bl, {"statut_bl": repository.STATUT_OK}, utilisateur)
                _journaliser_passage_ok(ligne["numero_bl"], ligne["nom_fournisseur"],
                                        ligne["quai_reception"], ligne["date_reception"])
                bascules += 1
            ui.set_flash("success" if bascules else "info",
                         f"{bascules} BL passé(s) à OK — notification(s) journalisée(s)."
                         if bascules else "Aucun BL EDI NOK dans la sélection.")
            _vider_grille(cle_grille)
            st.rerun()
        if clics["sup"]:
            dialog_supprimer_bls(ids_selection, cle_grille)
        if clics["res"]:
            for id_bl in ids_selection:
                repository.restaurer_bl(id_bl, utilisateur)
            ui.set_flash("success", f"{n} BL restauré(s).")
            _vider_grille(cle_grille)
            st.rerun()


# =====================================================================
# VUES « RÉFÉRENTIEL » simples — grille éditable (CRUD complet)
# =====================================================================
def vue_referentiel(nom_ref: str, nom_vue: str, valeurs_fixes: dict | None = None,
                    config_colonnes: dict | None = None,
                    df_charge: pd.DataFrame | None = None) -> None:
    if df_charge is None:
        try:
            df = repository.lire_referentiel(nom_ref, valeurs_fixes)
        except Exception as e:
            st.error(f"Erreur de lecture de la base : {e}")
            st.stop()
        visibles = [c for c in df.columns if c not in (valeurs_fixes or {})]
        df = df[visibles]
    else:
        df = df_charge
    df = df.reset_index(drop=True)
    cle = f"ref_{nom_vue}"

    ruban = st.container()
    st.caption("Ajoutez une ligne en bas de la grille, modifiez une cellule ou supprimez des "
               "lignes (sélection + touche Suppr), puis cliquez sur **💾 Enregistrer**.")
    edite = st.data_editor(df, num_rows="dynamic", use_container_width=True,
                           key=cle, hide_index=True, column_config=config_colonnes or {})

    with ruban:
        c1, c2, c3 = st.columns([1.6, 1.4, 5])
        if c1.button("💾 Enregistrer", type="primary", key=f"save_{nom_vue}",
                     use_container_width=True):
            try:
                ajouts, suppressions = repository.sauver_referentiel(
                    nom_ref, df, edite, valeurs_fixes)
                if ajouts or suppressions:
                    ui.set_flash("success",
                                 f"{nom_vue} : {ajouts} ajout(s)/modification(s), "
                                 f"{suppressions} suppression(s).")
                else:
                    ui.set_flash("info", "Aucune modification à enregistrer.")
                _vider_grille(cle)
                st.rerun()
            except ValueError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"Échec de l'enregistrement : {e}")
        if c2.button("🔄 Actualiser", key=f"refresh_{nom_vue}", use_container_width=True):
            _vider_grille(cle)
            st.rerun()
        c3.markdown(f"**{len(df)}** enregistrement(s)")


# =====================================================================
# VUE « DESADV » — filtres + grille éditable (horodatages en lecture)
# =====================================================================
def vue_desadv(sens: str) -> None:
    achat = sens == repository.SENS_ACHAT
    tiers_lib = "Fournisseur" if achat else "Client"
    type_tiers = repository.TIERS_FOURNISSEUR if achat else repository.TIERS_CLIENT
    suffixe = sens.lower()

    with st.expander("🔍 Filtres", expanded=False):
        c1, c2, c3 = st.columns(3)
        f_num = c1.text_input("Numéro de BL contient", key=f"dnum_{suffixe}").strip()
        f_frs = c2.text_input(f"{tiers_lib} contient", key=f"dfrs_{suffixe}").strip()
        if achat:
            gest_options = [""] + repository.lister_gestionnaires()
            f_gest = c3.selectbox("Gestionnaire", gest_options,
                                  format_func=lambda g: g or "Tous", key=f"dgest_{suffixe}")
        else:
            f_gest = ""
        f_dmin = c1.date_input("Intégré du", value=None, key=f"ddmin_{suffixe}")
        f_dmax = c2.date_input("Intégré au", value=None, key=f"ddmax_{suffixe}")

    try:
        df = repository.lire_desadv(sens, f_num, f_frs, f_gest, f_dmin, f_dmax).reset_index(drop=True)
    except Exception as e:
        st.error(f"Erreur de lecture de la base : {e}")
        st.stop()

    cle = f"desadv_{suffixe}"
    ruban = st.container()
    st.caption("Ajoutez / modifiez / supprimez des lignes (numéro de BL unique par sens), "
               "puis **💾 Enregistrer**. « Créé le » et « Date d'intégration » proviennent "
               "du flux EDI (lecture seule).")
    edite = st.data_editor(
        df, num_rows="dynamic", use_container_width=True, key=cle, hide_index=True,
        column_config={
            "numero_bl": st.column_config.TextColumn("Numéro de BL", required=True),
            "nom_fournisseur": st.column_config.SelectboxColumn(
                tiers_lib, options=repository.lister_tiers(type_tiers), required=True),
            "issuedatetime": st.column_config.DatetimeColumn("Créé le", disabled=True),
            "integrationdate": st.column_config.DateColumn("Date d'intégration", disabled=True),
        })

    with ruban:
        c1, c2, c3 = st.columns([1.6, 1.4, 5])
        if c1.button("💾 Enregistrer", type="primary", key=f"save_{cle}", use_container_width=True):
            try:
                ajouts, suppressions = repository.sauver_referentiel(
                    "desadv", df, edite, {"sens": sens})
                ui.set_flash("success", f"DESADV {sens} : {ajouts} ajout(s)/modification(s), "
                                        f"{suppressions} suppression(s)."
                             if (ajouts or suppressions) else "Aucune modification.")
                _vider_grille(cle)
                st.rerun()
            except ValueError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"Échec de l'enregistrement : {e}")
        if c2.button("🔄 Actualiser", key=f"refresh_{cle}", use_container_width=True):
            _vider_grille(cle)
            st.rerun()
        c3.markdown(f"**{len(df)}** avis d'expédition")


# =====================================================================
# VUE « PORTEFEUILLES » — filtres + grille éditable
# =====================================================================
def vue_portefeuilles() -> None:
    with st.expander("🔍 Filtres", expanded=False):
        c1, c2 = st.columns(2)
        gest_options = [""] + repository.lister_gestionnaires()
        f_gest = c1.selectbox("Gestionnaire", gest_options,
                              format_func=lambda g: g or "Tous", key="pf_gest")
        f_frs = c2.text_input("Fournisseur contient", key="pf_frs").strip()
    try:
        df = repository.lire_portefeuilles(f_gest, f_frs)
    except Exception as e:
        st.error(f"Erreur de lecture de la base : {e}")
        st.stop()
    vue_referentiel(
        "portefeuilles", "Portefeuilles", df_charge=df,
        config_colonnes={
            "code_gestionnaire": st.column_config.SelectboxColumn(
                "Gestionnaire", options=repository.lister_gestionnaires(), required=True),
            "nom_fournisseur": st.column_config.SelectboxColumn(
                "Fournisseur", options=repository.lister_tiers(repository.TIERS_FOURNISSEUR),
                required=True),
        })


# =====================================================================
# VUE « NOTIFICATIONS » (lecture seule)
# =====================================================================
def vue_notifications() -> None:
    try:
        df = repository.lister_notifications()
    except Exception as e:
        st.error(f"Erreur de lecture de la base : {e}")
        st.stop()
    if st.button("🔄 Actualiser", key="notif_refresh"):
        st.rerun()
    if df is None or df.empty:
        st.info("Aucune notification pour l'instant.")
        return
    st.dataframe(
        df, hide_index=True, use_container_width=True,
        column_config={
            "cree_le": st.column_config.DatetimeColumn("Date"),
            "type_notif": st.column_config.TextColumn("Type"),
            "numero_bl": st.column_config.TextColumn("N° BL"),
            "message": st.column_config.TextColumn("Message", width="large"),
            "cree_par": st.column_config.TextColumn("Par"),
            "envoyee": st.column_config.CheckboxColumn("Envoyée"),
        })
    st.caption("Journal en lecture seule. Un flux Power Automate pourra envoyer ces "
               "notifications par email ultérieurement.")


# =====================================================================
# ROUTAGE
# =====================================================================
if module:
    st.markdown(f"### {ICONES[module]} {module} › {vue}")

if espace == ESPACE_DASHBOARD:
    render_dashboard()
elif vue == "BL réception":
    vue_bl(vue, repository.TYPES_ACHAT)
elif vue == "BL expédition":
    vue_bl(vue, repository.TYPES_VENTE)
elif vue == "DESADV achat":
    vue_desadv(repository.SENS_ACHAT)
elif vue == "DESADV vente":
    vue_desadv(repository.SENS_VENTE)
elif vue == "Fournisseurs":
    vue_referentiel("tiers", vue, valeurs_fixes={"type_tiers": repository.TIERS_FOURNISSEUR},
                    config_colonnes={"name": st.column_config.TextColumn("Fournisseur", required=True)})
elif vue == "Clients":
    vue_referentiel("tiers", vue, valeurs_fixes={"type_tiers": repository.TIERS_CLIENT},
                    config_colonnes={"name": st.column_config.TextColumn("Client", required=True)})
elif vue == "Gestionnaires":
    vue_referentiel("gestionnaires", vue,
                    config_colonnes={"code_gestionnaire":
                                     st.column_config.TextColumn("Code gestionnaire", required=True)})
elif vue == "Portefeuilles":
    vue_portefeuilles()
elif vue == "Quais":
    vue_referentiel("quais", vue,
                    config_colonnes={"code_quai": st.column_config.TextColumn("Code quai", required=True)})
elif vue == "Notifications":
    vue_notifications()
