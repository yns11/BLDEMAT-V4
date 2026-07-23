"""Application « Administration des BL » — V5.

Expérience « model-driven » modernisée :
  - navigation par sections, vues toujours visibles, filtrée par le RBAC ;
  - filtres en boutons (pills) avec icônes, périodes en boutons multi-
    sélection (ce mois / cette semaine / hier / aujourd'hui / personnalisé) ;
  - chips horizontales des filtres appliqués, retirables une à une ;
  - KPI sur les vues BL et DESADV ; tableau de bord enrichi (deltas) ;
  - toutes les grilles triables ; confirmation avant toute modification ou
    suppression ; visionneuse d'images plein format ;
  - RBAC : matrice bl_core/rbac.py + table roles_utilisateurs (Gestion ▸
    Rôles). Table vide = mode ouvert.
"""

import datetime

import altair as alt
import pandas as pd
import streamlit as st

from bl_core import rbac, repository, ui
from bl_core.identity import get_current_user

st.set_page_config(page_title="Administration BL", page_icon="🗂️", layout="wide")

ui.configurer_logs()
ui.injecter_style()

utilisateur = get_current_user()
CTX_RBAC = rbac.contexte_rbac(utilisateur)
TAILLE_PAGE = 50
EFFACER = "__effacer__"          # sentinelle : « retirer la clé » (défaut du widget)

VUE_DASHBOARD = "Tableau de bord"
NAVIGATION = [
    ("Général", [("📊", VUE_DASHBOARD)]),
    ("Achat", [("📥", "BL réception"), ("📡", "DESADV achat")]),
    ("Vente", [("📤", "BL expédition"), ("📡", "DESADV vente")]),
    ("Gestion", [("🏭", "Fournisseurs"), ("🤝", "Clients"), ("👤", "Gestionnaires"),
                 ("💼", "Portefeuilles"), ("🚪", "Quais"), ("📍", "Adresses"),
                 ("🏢", "Sites logistiques"), ("📋", "PLA"), ("🔐", "Rôles"),
                 ("🔔", "Notifications")]),
]
SECTION_DE_LA_VUE = {v: s for s, vues in NAVIGATION for _, v in vues}

PERIODES = ["Aujourd'hui", "Hier", "Cette semaine", "Ce mois", "Personnalisé"]
ICONES_PERIODE = {"Aujourd'hui": "📅", "Hier": "🕑", "Cette semaine": "📆",
                  "Ce mois": "🗓️", "Personnalisé": "⚙️"}


def _vider_grille(cle: str) -> None:
    st.session_state.pop(cle, None)


def _journaliser_passage_ok(numero_bl, fournisseur, quai, date_reception) -> None:
    """Journalise le passage EDI NOK -> OK dans la table notifications."""
    message = (f"BL {numero_bl} ({fournisseur or '—'}, quai {quai or '—'}, "
               f"reçu le {date_reception or '—'}) : état passé de EDI NOK à OK "
               f"par {utilisateur}.")
    repository.enregistrer_notification("EDI_NOK_OK", numero_bl, message, utilisateur)


# =====================================================================
# FILTRES : mises à jour différées, périodes en boutons, chips retirables
# =====================================================================
def _appliquer_maj_filtres() -> None:
    """Applique les modifications de filtres demandées par les chips AVANT
    l'instanciation des widgets (une valeur de widget ne peut pas être
    modifiée après coup dans le même run)."""
    for cle, valeur in st.session_state.pop("maj_filtres", {}).items():
        if isinstance(valeur, str) and valeur == EFFACER:
            st.session_state.pop(cle, None)
        else:
            st.session_state[cle] = valeur


def _demander_maj(cle: str, valeur) -> None:
    st.session_state.setdefault("maj_filtres", {})[cle] = valeur
    st.rerun()


def afficher_chips(chips: list[tuple[str, str, object]], cle_vue: str) -> None:
    """Ligne horizontale des filtres appliqués : « libellé ✕ » ; un clic
    retire le filtre (valeur EFFACER = retour au défaut du widget)."""
    if not chips:
        return
    with st.container(horizontal=True, key=f"chips_{cle_vue}", gap="small"):
        for i, (libelle, cle, valeur) in enumerate(chips):
            if st.button(f"{libelle}  ✕", key=f"chip_{cle_vue}_{i}"):
                _demander_maj(cle, valeur)


@st.dialog("🗓️ Période personnalisée")
def dialog_periode_perso(cle: str):
    ajd = repository.maintenant_local().date()
    stocke = st.session_state.get(f"perso_{cle}") or (ajd - datetime.timedelta(days=7), ajd)
    deb = st.date_input("Du", value=stocke[0], key=f"perso_deb_{cle}")
    fin = st.date_input("Au", value=stocke[1], key=f"perso_fin_{cle}")
    col_ok, col_ko = st.columns(2)
    if col_ok.button("✅ Appliquer", type="primary", use_container_width=True):
        if deb > fin:
            st.error("La date de début doit précéder la date de fin.")
            st.stop()
        st.session_state[f"perso_{cle}"] = (deb, fin)
        st.session_state.pop(f"perso_demande_{cle}", None)
        st.rerun()
    if col_ko.button("Annuler", use_container_width=True):
        sel = [o for o in st.session_state.get(f"per_{cle}", []) if o != "Personnalisé"]
        st.session_state.pop(f"perso_demande_{cle}", None)
        _demander_maj(f"per_{cle}", sel)


def filtre_periode(cle: str, libelle: str = "Période",
                   defaut: tuple = ("Hier", "Aujourd'hui")):
    """Filtre de dates en boutons multi-sélection. Renvoie (dmin, dmax, sel) —
    l'enveloppe [min, max] des périodes cochées, None sans sélection."""
    sel = st.pills(libelle, PERIODES, selection_mode="multi", default=list(defaut),
                   key=f"per_{cle}",
                   format_func=lambda o: f"{ICONES_PERIODE[o]} {o}") or []
    ajd = repository.maintenant_local().date()
    hier = ajd - datetime.timedelta(days=1)
    bornes = []
    for o in sel:
        if o == "Aujourd'hui":
            bornes.append((ajd, ajd))
        elif o == "Hier":
            bornes.append((hier, hier))
        elif o == "Cette semaine":
            bornes.append((ajd - datetime.timedelta(days=ajd.weekday()), ajd))
        elif o == "Ce mois":
            bornes.append((ajd.replace(day=1), ajd))
        elif o == "Personnalisé":
            perso = st.session_state.get(f"perso_{cle}")
            if perso:
                bornes.append(tuple(perso))
                if st.button("✏️ Modifier la période personnalisée", key=f"editper_{cle}"):
                    dialog_periode_perso(cle)
            elif not st.session_state.get(f"perso_demande_{cle}"):
                st.session_state[f"perso_demande_{cle}"] = True
                dialog_periode_perso(cle)
            elif st.button("🗓️ Choisir les dates…", key=f"choisirper_{cle}"):
                dialog_periode_perso(cle)
    if not bornes:
        return None, None, sel
    return min(b[0] for b in bornes), max(b[1] for b in bornes), sel


def chips_periode(cle: str, sel: list) -> list[tuple[str, str, object]]:
    """Une chip par période sélectionnée (retirables une à une)."""
    chips = []
    for o in sel:
        libelle = f"{ICONES_PERIODE[o]} {o}"
        if o == "Personnalisé" and st.session_state.get(f"perso_{cle}"):
            deb, fin = st.session_state[f"perso_{cle}"]
            libelle = f"🗓️ Du {deb:%d/%m} au {fin:%d/%m}"
        chips.append((libelle, f"per_{cle}", [x for x in sel if x != o]))
    return chips


def _tri_grille(df: pd.DataFrame, cle: str,
                libelles: dict | None = None) -> tuple[pd.DataFrame, str]:
    """Tri des grilles éditables (le tri natif est désactivé quand l'ajout de
    lignes est possible) : colonne en pills + sens. Renvoie (df trié, suffixe
    de clé) — le suffixe fait recréer l'éditeur à chaque changement de tri,
    sinon les éditions en cours seraient réappliquées aux mauvaises lignes."""
    if df.empty or not len(df.columns):
        return df, ""
    libelles = libelles or {}
    with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
        col_tri = st.pills("Trier par", list(df.columns), key=f"tri_{cle}",
                           format_func=lambda c: libelles.get(c, c))
        sens = st.segmented_control("Sens", ["⬆️", "⬇️"], key=f"sens_tri_{cle}",
                                    default="⬆️", label_visibility="hidden")
    if not col_tri:
        return df, ""
    df = df.sort_values(col_tri, ascending=(sens != "⬇️"), kind="stable",
                        na_position="last").reset_index(drop=True)
    return df, f"_{col_tri}_{'d' if sens == '⬇️' else 'a'}"


# =====================================================================
# NAVIGATION LATÉRALE — sections texte + vues visibles, filtrée par le RBAC
# =====================================================================
_appliquer_maj_filtres()

NAV_VISIBLE = [(s, [(i, v) for i, v in vues
                    if rbac.niveau_vue(v, CTX_RBAC) != rbac.AUCUN])
               for s, vues in NAVIGATION]
NAV_VISIBLE = [(s, vues) for s, vues in NAV_VISIBLE if vues]
VUES_VISIBLES = [v for _, vues in NAV_VISIBLE for _, v in vues]

if not VUES_VISIBLES:
    ui.entete_app("Administration des BL")
    st.error("Aucune vue ne vous est autorisée. Demandez un rôle à l'administrateur "
             "métier (table roles_utilisateurs / vue Gestion ▸ Rôles).")
    st.stop()

st.session_state.setdefault("nav_vue", VUES_VISIBLES[0])
if st.session_state.nav_vue not in VUES_VISIBLES:
    st.session_state.nav_vue = VUES_VISIBLES[0]

with st.sidebar:
    ui.afficher_logo()
    st.divider()
    for section, vues in NAV_VISIBLE:
        ui.section_nav(section)
        for icone, v in vues:
            actif = st.session_state.nav_vue == v
            if st.button(f"{icone}  {v}", key=f"nav_{v}", use_container_width=True,
                         type="primary" if actif else "secondary"):
                st.session_state.nav_vue = v
                st.rerun()
    st.divider()
    roles_txt = ", ".join(CTX_RBAC["roles"]) if CTX_RBAC["actif"] else "accès complet"
    st.caption(f"👤 {utilisateur}")
    st.caption(f"🔐 {roles_txt}")

vue = st.session_state.nav_vue
section = SECTION_DE_LA_VUE.get(vue, "Général")
NIVEAU = rbac.niveau_vue(vue, CTX_RBAC)
LECTURE_SEULE = NIVEAU == rbac.LECTURE

ui.entete_app("Administration des BL")
ui.show_flash()


# =====================================================================
# TABLEAU DE BORD — KPI avec deltas + graphiques
# =====================================================================
def render_dashboard() -> None:
    st.markdown("### 📊 Tableau de bord")

    dmin, dmax, sel_per = filtre_periode("dash", defaut=("Ce mois",))
    c1, c2, c3 = st.columns([2, 2, 3])
    portee_sel = c1.pills("Périmètre", ["🛒 Achat", "🚚 Vente"], key="dash_portee")
    gest_sel = c2.pills("Gestionnaire", repository.lister_gestionnaires(),
                        key="dash_gest")
    f_tiers = c3.text_input("Fournisseur / client contient", key="dash_tiers").strip()

    chips = chips_periode("dash", sel_per)
    if portee_sel:
        chips.append((portee_sel, "dash_portee", None))
    if gest_sel:
        chips.append((f"👤 {gest_sel}", "dash_gest", None))
    if f_tiers:
        chips.append((f"🔎 « {f_tiers} »", "dash_tiers", ""))
    afficher_chips(chips, "dash")

    ajd = repository.maintenant_local().date()
    dmin = dmin or ajd.replace(day=1)
    dmax = dmax or ajd

    try:
        df = repository.lire_bl_pour_dashboard(dmin, dmax).reset_index(drop=True)
        duree = (dmax - dmin).days + 1
        df_prec = repository.lire_bl_pour_dashboard(
            dmin - datetime.timedelta(days=duree), dmin - datetime.timedelta(days=1))
    except Exception as e:
        st.error(f"Erreur de lecture de la base : {e}")
        st.stop()

    def _filtrer(d: pd.DataFrame) -> pd.DataFrame:
        if portee_sel == "🛒 Achat":
            d = d[d["type_operation"].isin(repository.TYPES_ACHAT)]
        elif portee_sel == "🚚 Vente":
            d = d[d["type_operation"].isin(repository.TYPES_VENTE)]
        if f_tiers:
            d = d[d["nom_fournisseur"].fillna("").str.lower().str.contains(f_tiers.lower())]
        if gest_sel:
            frs = set(repository.lire_portefeuilles(gestionnaire=gest_sel)["nom_fournisseur"])
            d = d[d["nom_fournisseur"].isin(frs)]
        return d

    df, df_prec = _filtrer(df), _filtrer(df_prec)

    def _kpis(d: pd.DataFrame) -> dict:
        est = d["type_operation"] if not d.empty else pd.Series(dtype=object)
        rec = int((est == repository.TYPE_RECEPTION).sum())
        nok = int(((est == repository.TYPE_RECEPTION) &
                   (d["statut_bl"] == repository.STATUT_EDI_NOK)).sum()) if not d.empty else 0
        return {"total": len(d), "rec": rec,
                "exp": int((est == repository.TYPE_EXPEDITION).sum()),
                "arch": int(est.isin([repository.TYPE_ARCHIVAGE_RECEPTION,
                                      repository.TYPE_ARCHIVAGE_EXPEDITION]).sum()),
                "nok": nok}

    k, kp = _kpis(df), _kpis(df_prec)
    taux = f"{100 * k['nok'] / k['rec']:.0f} %" if k["rec"] else "—"

    try:
        desadv_nok = len(repository.lire_desadv(repository.SENS_ACHAT, statut_edi="EDI NOK"))
    except Exception:
        desadv_nok = None

    cols = st.columns(6)
    cols[0].metric("BL (période)", k["total"], delta=k["total"] - kp["total"])
    cols[1].metric("Réceptions", k["rec"], delta=k["rec"] - kp["rec"])
    cols[2].metric("Expéditions", k["exp"], delta=k["exp"] - kp["exp"])
    cols[3].metric("EDI NOK", k["nok"], delta=k["nok"] - kp["nok"],
                   delta_color="inverse")
    cols[4].metric("Taux EDI NOK", taux)
    cols[5].metric("DESADV achat EDI NOK", "—" if desadv_nok is None else desadv_nok,
                   help="Avis d'expédition achat dont le message EDI est en erreur.")
    st.caption(f"Période {dmin:%d/%m/%Y} → {dmax:%d/%m/%Y} · deltas vs période "
               "précédente de même durée.")

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

    col_g, col_m, col_d = st.columns([3, 1.4, 1.4])
    with col_g:
        st.markdown("#### Top fournisseurs / clients")
        top_df = (df["nom_fournisseur"].fillna("—").value_counts().head(10)
                  .rename_axis("Tiers").reset_index(name="BL"))
        chart = (
            alt.Chart(top_df).mark_bar(color="#0F62A6", cornerRadiusEnd=3).encode(
                x=alt.X("BL:Q", title="Nombre de BL"),
                y=alt.Y("Tiers:N", sort="-x", title=None,
                        axis=alt.Axis(labelFontSize=15, labelLimit=360)),
                tooltip=["Tiers", "BL"],
            ).properties(height=max(220, 34 * len(top_df)))
        )
        st.altair_chart(chart, use_container_width=True)
    with col_m:
        st.markdown("#### Mix des opérations")
        mix = (df["type_operation"].map(lambda t: repository.LIBELLES_OPERATION.get(t, t))
               .value_counts().rename_axis("Opération").reset_index(name="BL"))
        donut = (alt.Chart(mix).mark_arc(innerRadius=52).encode(
            theta="BL:Q",
            color=alt.Color("Opération:N", legend=alt.Legend(orient="bottom", columns=1),
                            scale=alt.Scale(range=["#0F62A6", "#43B02A", "#4FA3E3", "#F2A93B"])),
            tooltip=["Opération", "BL"]).properties(height=260))
        st.altair_chart(donut, use_container_width=True)
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
# BOÎTES DE DIALOGUE
# =====================================================================
@st.dialog("✏️ Fiche du BL", width="medium")
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
        plage = quai = None
        commentaire = ""
        if avec_pq:
            index_plage = (repository.PLAGES_HORAIRES.index(bl["plage_horaire"])
                           if bl.get("plage_horaire") in repository.PLAGES_HORAIRES else None)
            plage = st.selectbox("Plage horaire", options=repository.PLAGES_HORAIRES,
                                 index=index_plage, placeholder="Non renseignée")
            quais = repository.lister_quais()
            index_quai = quais.index(bl["quai_reception"]) if bl.get("quai_reception") in quais else None
            quai = st.selectbox("Quai", options=quais, index=index_quai, placeholder="Non renseigné")
            commentaire = st.text_area("Commentaire", value=bl.get("comment_bl") or "", max_chars=1000)
        statut_choix = None
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
            if avec_st:
                champs["statut_bl"] = (repository.STATUT_OK if statut_choix == "OK"
                                       else repository.STATUT_EDI_NOK)
            st.session_state["fiche_a_confirmer"] = champs

    # Confirmation en deux temps, dans la même boîte de dialogue.
    champs = st.session_state.get("fiche_a_confirmer")
    if champs is not None:
        st.warning(f"Enregistrer les modifications du BL « {champs['numero_bl']} » ?")
        col_ok, col_ko = st.columns(2)
        if col_ok.button("✅ Confirmer", type="primary", use_container_width=True):
            st.session_state.pop("fiche_a_confirmer", None)
            passe_a_ok = (avec_st and bl.get("statut_bl") == repository.STATUT_EDI_NOK
                          and champs.get("statut_bl") == repository.STATUT_OK)
            try:
                repository.mettre_a_jour_bl(bl["id_bl"], champs, utilisateur)
            except ValueError as e:            # numéro de BL déjà pris
                st.error(str(e))
                st.stop()
            if passe_a_ok:
                _journaliser_passage_ok(champs["numero_bl"], champs.get("nom_fournisseur"),
                                        champs.get("quai_reception"), champs.get("date_reception"))
                ui.set_flash("success", f"BL {champs['numero_bl']} mis à jour — "
                                        "passage à OK journalisé (Gestion ▸ Notifications).")
            else:
                ui.set_flash("success", f"BL {champs['numero_bl']} mis à jour.")
            _vider_grille(cle_grille)
            st.rerun()
        if col_ko.button("Annuler", use_container_width=True):
            st.session_state.pop("fiche_a_confirmer", None)

    if ids_photos:
        with st.expander(f"📎 Pages ({len(ids_photos)})"):
            for i, id_photo in enumerate(ids_photos):
                try:
                    st.image(repository.telecharger_photo(id_photo), caption=f"Page {i + 1}",
                             use_container_width=True)
                except Exception as e:
                    st.caption(f"Page {i + 1} inaccessible : {e}")


@st.dialog("🖼️ Pages du BL", width="large")
def dialog_voir_images(numero_bl: str, ids_photos: list[str]):
    if not ids_photos:
        st.info("Aucune page attachée à ce BL.")
        return
    pages, erreurs = [], 0
    for id_photo in ids_photos:
        try:
            pages.append(repository.telecharger_photo(id_photo))
        except Exception:
            erreurs += 1
    if erreurs:
        st.warning(f"{erreurs} page(s) inaccessible(s).")
    if pages:
        ui.visionneuse_images(pages, f"BL {numero_bl}")


@st.dialog("🗑️ Confirmation")
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


@st.dialog("✅ Confirmation")
def dialog_confirmer_grille(nom_ref: str, nom_vue: str, df_avant: pd.DataFrame,
                            df_apres: pd.DataFrame, valeurs_fixes: dict | None,
                            cle_grille: str):
    st.warning(f"Appliquer les modifications de la grille « {nom_vue} » ? "
               "Les lignes supprimées le seront définitivement.")
    col_oui, col_non = st.columns(2)
    if col_oui.button("✅ Confirmer", type="primary", use_container_width=True):
        try:
            ajouts, suppressions = repository.sauver_referentiel(
                nom_ref, df_avant, df_apres, valeurs_fixes)
            if ajouts or suppressions:
                ui.set_flash("success", f"{nom_vue} : {ajouts} ajout(s)/modification(s), "
                                        f"{suppressions} suppression(s).")
            else:
                ui.set_flash("info", "Aucune modification à enregistrer.")
        except ValueError as e:
            st.error(str(e))
            st.stop()
        except Exception as e:
            st.error(f"Échec de l'enregistrement : {e}")
            st.stop()
        _vider_grille(cle_grille)
        st.rerun()
    if col_non.button("Annuler", use_container_width=True):
        st.rerun()


@st.dialog("✅ Confirmation")
def dialog_confirmer_ok(df: pd.DataFrame, ids: list[str], cle_grille: str):
    nb_nok = int((df[df["id_bl"].isin(ids)]["statut_bl"]
                  == repository.STATUT_EDI_NOK).sum())
    st.warning(f"Passer à OK les BL EDI NOK sélectionnés ({nb_nok} concerné(s) "
               f"sur {len(ids)}) ? Chaque passage est journalisé.")
    col_oui, col_non = st.columns(2)
    if col_oui.button("✅ Confirmer", type="primary", use_container_width=True):
        bascules = 0
        for id_bl in ids:
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
    if col_non.button("Annuler", use_container_width=True):
        st.rerun()


@st.dialog("♻️ Confirmation")
def dialog_confirmer_restauration(ids: list[str], cle_grille: str):
    st.warning(f"Restaurer {len(ids)} BL supprimé(s) ?")
    col_oui, col_non = st.columns(2)
    if col_oui.button("✅ Confirmer", type="primary", use_container_width=True):
        for id_bl in ids:
            repository.restaurer_bl(id_bl, utilisateur)
        ui.set_flash("success", f"{len(ids)} BL restauré(s).")
        _vider_grille(cle_grille)
        st.rerun()
    if col_non.button("Annuler", use_container_width=True):
        st.rerun()


# =====================================================================
# VUES « BL » (réception / expédition) — KPI + grille + ruban d'actions
# =====================================================================
def vue_bl(nom_vue: str, types: list[str]) -> None:
    avec_statut = repository.TYPE_RECEPTION in types
    achat = types == repository.TYPES_ACHAT
    tiers_lib = "Fournisseur" if achat else "Client"
    lecture = LECTURE_SEULE

    # --- Filtres (boutons + saisies) ---
    with st.expander("🔍 Filtres", expanded=False):
        dmin, dmax, sel_per = filtre_periode(f"bl_{nom_vue}")
        c1, c2 = st.columns(2)
        f_numero = c1.text_input("Numéro contient", key=f"f_num_{nom_vue}").strip()
        f_tiers = c2.text_input(f"{tiers_lib} contient", key=f"f_frs_{nom_vue}").strip()
        if avec_statut:
            f_statut = st.pills("État", ["🟥 EDI NOK", "✅ OK"], key=f"f_st_{nom_vue}",
                                default="🟥 EDI NOK")
        else:
            f_statut = None
        if achat:
            f_gest = st.pills("Gestionnaire", repository.lister_gestionnaires(),
                              key=f"f_gest_{nom_vue}") or ""
        else:
            f_gest = ""
        f_suppr = st.checkbox("Inclure les BL supprimés", key=f"f_sup_{nom_vue}")
    statut = {"✅ OK": repository.STATUT_OK,
              "🟥 EDI NOK": repository.STATUT_EDI_NOK}.get(f_statut)

    # --- Chips des filtres appliqués (retirables) ---
    chips = chips_periode(f"bl_{nom_vue}", sel_per)
    if f_numero:
        chips.append((f"N° « {f_numero} »", f"f_num_{nom_vue}", ""))
    if f_tiers:
        chips.append((f"{tiers_lib} « {f_tiers} »", f"f_frs_{nom_vue}", ""))
    if f_statut:
        chips.append((f_statut, f"f_st_{nom_vue}", None))
    if f_gest:
        chips.append((f"👤 {f_gest}", f"f_gest_{nom_vue}", None))
    if f_suppr:
        chips.append(("🗑️ Supprimés inclus", f"f_sup_{nom_vue}", False))
    afficher_chips(chips, f"blc_{nom_vue}")

    # Pagination et sélection réinitialisées quand les filtres changent.
    signature = (f_numero, f_tiers, str(dmin), str(dmax), f_statut, f_gest, f_suppr)
    cle_page, cle_grille = f"page_{nom_vue}", f"grille_{nom_vue}"
    if st.session_state.get(f"sig_{nom_vue}") != signature:
        st.session_state[f"sig_{nom_vue}"] = signature
        st.session_state[cle_page] = 1
        _vider_grille(cle_grille)
    page = st.session_state.setdefault(cle_page, 1)

    try:
        df, total = repository.rechercher_bl(
            numero=f_numero, fournisseur=f_tiers, types=types,
            date_min=dmin, date_max=dmax, statut=statut, gestionnaire=f_gest,
            inclure_supprimes=f_suppr, page=page, page_size=TAILLE_PAGE,
        )
        df = df.reset_index(drop=True)
        photos = repository.photos_pour_bls(df["id_bl"].tolist() if not df.empty else [])
        stats = repository.stats_bl(numero=f_numero, fournisseur=f_tiers, types=types,
                                    date_min=dmin, date_max=dmax, gestionnaire=f_gest,
                                    inclure_supprimes=f_suppr)
    except Exception as e:
        st.error(f"Erreur de lecture de la base : {e}")
        st.stop()

    # --- KPI du périmètre filtré (hors filtre d'état) ---
    if avec_statut:
        taux = f"{100 * stats['nok'] / stats['total']:.0f} %" if stats["total"] else "—"
        k = st.columns(5)
        k[0].metric("BL (périmètre)", stats["total"])
        k[1].metric("EDI NOK", stats["nok"])
        k[2].metric("OK", stats["ok"])
        k[3].metric("Taux EDI NOK", taux)
        k[4].metric("Pages jointes", stats["pages"])
    else:
        k = st.columns(2)
        k[0].metric("BL (périmètre)", stats["total"])
        k[1].metric("Pages jointes", stats["pages"])

    ruban = st.container()                     # rempli après la grille (sélection à jour)

    # --- Grille : un clic sur une ligne (cellule) la sélectionne ; cases à
    # cocher pour la sélection multiple. Tri natif par en-tête de colonne. ---
    ids_selection: list[str] = []
    if df.empty:
        st.info("Aucun BL ne correspond aux filtres.")
    else:
        colonnes = {
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
        evenement = st.dataframe(
            df_aff, hide_index=True, use_container_width=True, key=cle_grille,
            on_select="rerun", selection_mode=["multi-row", "multi-cell"],
        )
        lignes = set(evenement.selection.rows)
        lignes.update(r for r, _ in evenement.selection.cells)
        lignes = {r for r in lignes if 0 <= r < len(df)}   # sélection périmée
        ids_selection = df.loc[sorted(lignes), "id_bl"].tolist()

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

    # --- Ruban d'actions contextuel (réduit en lecture seule) ---
    with ruban:
        n = len(ids_selection)
        specs = [
            ("🔄 Actualiser", "act", False, 1.3),
            ("🖼️ Voir les images", "img", n != 1, 1.9),
        ]
        if not lecture:
            specs.insert(1, ("✏️ Modifier", "mod", n != 1, 1.3))
            if avec_statut:
                specs.append(("✅ Passer à OK", "ok", n == 0, 1.5))
            specs += [("🗑️ Supprimer", "sup", n == 0, 1.4),
                      ("♻️ Restaurer", "res", n == 0, 1.4)]
        cols = st.columns([s[3] for s in specs] + [2.6])
        clics = {}
        for i, (label, code, disabled, _) in enumerate(specs):
            aide = ("Cliquez sur une ligne pour la sélectionner." if code in ("mod", "img")
                    else "Passe les BL EDI NOK sélectionnés à OK." if code == "ok" else None)
            clics[code] = cols[i].button(label, key=f"{code}_{nom_vue}", disabled=disabled,
                                         use_container_width=True, help=aide)
        etat_droits = " · 🔒 lecture seule" if lecture else ""
        cols[-1].markdown(f"**{total}** BL · **{n}** sélectionné(s){etat_droits}")

        if clics["act"]:
            _vider_grille(cle_grille)
            st.rerun()
        if clics.get("mod"):
            ligne = df[df["id_bl"] == ids_selection[0]].iloc[0].to_dict()
            dialog_modifier_bl(ligne, photos.get(ids_selection[0], []), cle_grille)
        if clics["img"]:
            ligne = df[df["id_bl"] == ids_selection[0]].iloc[0]
            dialog_voir_images(ligne["numero_bl"], photos.get(ids_selection[0], []))
        if clics.get("ok"):
            dialog_confirmer_ok(df, ids_selection, cle_grille)
        if clics.get("sup"):
            dialog_supprimer_bls(ids_selection, cle_grille)
        if clics.get("res"):
            dialog_confirmer_restauration(ids_selection, cle_grille)


# =====================================================================
# VUES « RÉFÉRENTIEL » — grille éditable triable (CRUD avec confirmation)
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
    libelles_tri = {c: (cfg.get("label") if isinstance(cfg, dict) else None) or c
                    for c, cfg in (config_colonnes or {}).items()}

    if LECTURE_SEULE:
        st.caption("🔒 Lecture seule (vos rôles ne permettent pas la modification).")
        st.dataframe(df, hide_index=True, use_container_width=True,
                     column_config=config_colonnes or {})
        st.markdown(f"**{len(df)}** enregistrement(s)")
        return

    ruban = st.container()
    df, suffixe_tri = _tri_grille(df, cle, libelles_tri)
    st.caption("Ajoutez une ligne en bas de la grille, modifiez une cellule ou supprimez des "
               "lignes (sélection + touche Suppr), puis cliquez sur **💾 Enregistrer**.")
    edite = st.data_editor(df, num_rows="dynamic", use_container_width=True,
                           key=f"{cle}{suffixe_tri}", hide_index=True,
                           column_config=config_colonnes or {})

    with ruban:
        c1, c2, c3 = st.columns([1.6, 1.4, 5])
        if c1.button("💾 Enregistrer", type="primary", key=f"save_{nom_vue}",
                     use_container_width=True):
            dialog_confirmer_grille(nom_ref, nom_vue, df, edite, valeurs_fixes, cle)
        if c2.button("🔄 Actualiser", key=f"refresh_{nom_vue}", use_container_width=True):
            _vider_grille(cle)
            st.rerun()
        c3.markdown(f"**{len(df)}** enregistrement(s)")


# =====================================================================
# VUE « DESADV » — filtres boutons + chips + KPI EDI + grille triable
# =====================================================================
def vue_desadv(sens: str) -> None:
    achat = sens == repository.SENS_ACHAT
    tiers_lib = "Fournisseur" if achat else "Client"
    type_tiers = repository.TIERS_FOURNISSEUR if achat else repository.TIERS_CLIENT
    suffixe = sens.lower()
    lecture = LECTURE_SEULE

    with st.expander("🔍 Filtres", expanded=False):
        dmin, dmax, sel_per = filtre_periode(f"dsd_{suffixe}", "Période d'intégration")
        c1, c2 = st.columns(2)
        f_num = c1.text_input("Numéro de BL contient", key=f"dnum_{suffixe}").strip()
        f_frs = c2.text_input(f"{tiers_lib} contient", key=f"dfrs_{suffixe}").strip()
        f_sedi = st.pills("État EDI", ["🟥 EDI NOK", "✅ OK"], key=f"dsedi_{suffixe}",
                          default="🟥 EDI NOK")
        if achat:
            f_gest = st.pills("Gestionnaire", repository.lister_gestionnaires(),
                              key=f"dgest_{suffixe}") or ""
        else:
            f_gest = ""
    statut_edi = {"✅ OK": "OK", "🟥 EDI NOK": "EDI NOK"}.get(f_sedi, "")

    chips = chips_periode(f"dsd_{suffixe}", sel_per)
    if f_num:
        chips.append((f"N° « {f_num} »", f"dnum_{suffixe}", ""))
    if f_frs:
        chips.append((f"{tiers_lib} « {f_frs} »", f"dfrs_{suffixe}", ""))
    if f_sedi:
        chips.append((f_sedi, f"dsedi_{suffixe}", None))
    if f_gest:
        chips.append((f"👤 {f_gest}", f"dgest_{suffixe}", None))
    afficher_chips(chips, f"dsdc_{suffixe}")

    try:
        df = repository.lire_desadv(sens, f_num, f_frs, f_gest, dmin, dmax,
                                    statut_edi=statut_edi).reset_index(drop=True)
    except Exception as e:
        st.error(f"Erreur de lecture de la base : {e}")
        st.stop()

    # KPI de l'état des messages EDI (sur le périmètre filtré).
    nb_ok = int((df["statut_edi"] == "OK").sum())
    nb_nok = int((df["statut_edi"] == "EDI NOK").sum())
    taux_nok = f"{100 * nb_nok / len(df):.0f} %" if len(df) else "—"
    k = st.columns(4)
    k[0].metric("Avis (filtrés)", len(df))
    k[1].metric("EDI OK", nb_ok)
    k[2].metric("EDI NOK", nb_nok)
    k[3].metric("Taux EDI NOK", taux_nok)

    cle = f"desadv_{suffixe}"
    config = {
        "numero_bl": st.column_config.TextColumn("Numéro de BL", required=True),
        "nom_fournisseur": st.column_config.SelectboxColumn(
            tiers_lib, options=repository.lister_tiers(type_tiers), required=True),
        "issuedatetime": st.column_config.DatetimeColumn("Créé le", disabled=True),
        "integrationdate": st.column_config.DateColumn("Date d'intégration", disabled=True),
        "statut_edi": st.column_config.TextColumn("État EDI", disabled=True),
    }

    if lecture:
        st.caption("🔒 Lecture seule (vos rôles ne permettent pas la modification).")
        st.dataframe(df, hide_index=True, use_container_width=True, column_config=config)
        st.markdown(f"**{len(df)}** avis d'expédition")
        return

    ruban = st.container()
    df, suffixe_tri = _tri_grille(df, cle, {"numero_bl": "Numéro de BL",
                                            "nom_fournisseur": tiers_lib,
                                            "issuedatetime": "Créé le",
                                            "integrationdate": "Date d'intégration",
                                            "statut_edi": "État EDI"})
    st.caption("Ajoutez / modifiez / supprimez des lignes (numéro de BL unique par sens), "
               "puis **💾 Enregistrer**. « Créé le », « Date d'intégration » et « État EDI » "
               "proviennent du flux EDI (lecture seule, rafraîchis par le job).")
    edite = st.data_editor(df, num_rows="dynamic", use_container_width=True,
                           key=f"{cle}{suffixe_tri}", hide_index=True, column_config=config)

    with ruban:
        c1, c2, c3 = st.columns([1.6, 1.4, 5])
        if c1.button("💾 Enregistrer", type="primary", key=f"save_{cle}", use_container_width=True):
            dialog_confirmer_grille("desadv", f"DESADV {sens}", df, edite, {"sens": sens}, cle)
        if c2.button("🔄 Actualiser", key=f"refresh_{cle}", use_container_width=True):
            _vider_grille(cle)
            st.rerun()
        c3.markdown(f"**{len(df)}** avis d'expédition")


# =====================================================================
# VUES filtrées du module Gestion (portefeuilles, sites, PLA, rôles)
# =====================================================================
def vue_portefeuilles() -> None:
    with st.expander("🔍 Filtres", expanded=False):
        f_gest = st.pills("Gestionnaire", repository.lister_gestionnaires(),
                          key="pf_gest") or ""
        f_frs = st.text_input("Fournisseur contient", key="pf_frs").strip()
    chips = []
    if f_gest:
        chips.append((f"👤 {f_gest}", "pf_gest", None))
    if f_frs:
        chips.append((f"🔎 « {f_frs} »", "pf_frs", ""))
    afficher_chips(chips, "pf")
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


def vue_sites_logistiques() -> None:
    with st.expander("🔍 Filtres", expanded=False):
        c1, c2 = st.columns(2)
        tiers_options = [""] + repository.lister_tous_tiers()
        f_ent = c1.selectbox("Entité (fournisseur ou client)", tiers_options,
                             format_func=lambda t: t or "Toutes", key="sl_ent")
        f_adr = c2.text_input("Adresse contient", key="sl_adr").strip()
    chips = []
    if f_ent:
        chips.append((f"🏢 {f_ent}", "sl_ent", ""))
    if f_adr:
        chips.append((f"🔎 « {f_adr} »", "sl_adr", ""))
    afficher_chips(chips, "sl")
    try:
        df = repository.lire_sites_logistiques(f_ent, f_adr)
    except Exception as e:
        st.error(f"Erreur de lecture de la base : {e}")
        st.stop()
    vue_referentiel(
        "sites_logistiques", "Sites logistiques", df_charge=df,
        config_colonnes={
            "entite": st.column_config.SelectboxColumn(
                "Entité", options=repository.lister_tous_tiers(), required=True),
            "adresse": st.column_config.SelectboxColumn(
                "Adresse", options=repository.lister_adresses(), required=True,
                help="Les adresses se gèrent dans la vue Adresses."),
        })


def vue_pla() -> None:
    st.caption("Protocole logistique d'achat : un protocole par tiers. Le quai du "
               "PLA pré-remplit automatiquement le champ Quai de l'app Création "
               f"(défaut « {repository.QUAI_DEFAUT} » pour un tiers sans PLA).")
    vue_referentiel(
        "pla", "PLA",
        config_colonnes={
            "nom_fournisseur": st.column_config.SelectboxColumn(
                "Tiers (fournisseur / client)", options=repository.lister_tous_tiers(),
                required=True),
            "code_quai": st.column_config.SelectboxColumn(
                "Quai", options=repository.lister_quais(), required=True),
            "jours_livraison": st.column_config.TextColumn(
                "Jours de livraison", help="Ex. « lundi, mercredi, vendredi »"),
            "frequence_livraison": st.column_config.TextColumn(
                "Fréquence de livraison", help="Ex. « quotidienne », « 2x/semaine »"),
        })


def vue_roles() -> None:
    st.caption("RBAC : rôles applicatifs par utilisateur (email Databricks). "
               "Tant que cette table est vide, les deux apps sont en accès complet ; "
               "le contrôle s'active à la première ligne. La matrice des droits par "
               "vue est portée par le code (bl_core/rbac.py).")
    vue_referentiel(
        "roles", "Rôles",
        config_colonnes={
            "utilisateur": st.column_config.TextColumn(
                "Utilisateur (email)", required=True),
            "role": st.column_config.SelectboxColumn(
                "Rôle", options=rbac.ROLES, required=True),
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
if vue != VUE_DASHBOARD:
    st.markdown(f"### {section} › {vue}")

if vue == VUE_DASHBOARD:
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
elif vue == "Adresses":
    vue_referentiel("adresses", vue,
                    config_colonnes={"adresse": st.column_config.TextColumn("Adresse", required=True)})
elif vue == "Sites logistiques":
    vue_sites_logistiques()
elif vue == "PLA":
    vue_pla()
elif vue == "Rôles":
    vue_roles()
elif vue == "Notifications":
    vue_notifications()
