"""Application « Création de BL dématérialisés » — V4.

Wizard en 4 étapes, avec pré-remplissage assisté par IA :
  1. Type d'opération (4 types)
  2. Numérisation des pages (scan)
  3. Informations du BL : champs pré-remplis par extraction automatique de
     l'image (LLM vision) puis rapprochés des référentiels ; sans
     correspondance ou sans IA, saisie semi-manuelle
  4. Récapitulatif et enregistrement
"""

import logging
import uuid
import datetime

import streamlit as st

from bl_core import extraction, images, repository, ui
from bl_core.identity import get_current_user

logger = logging.getLogger("bl.creation")

# set_page_config doit être la 1re commande Streamlit.
st.set_page_config(page_title="Création BL", page_icon="📥", layout="centered")

ui.configurer_logs()
ui.injecter_style()

# Libellé métier du bouton de capture (« Browse files » non paramétrable).
st.markdown(
    """
    <style>
    [data-testid="stFileUploader"] section button {
        color: transparent !important;
        position: relative;
        min-width: 14rem;
    }
    [data-testid="stFileUploader"] section button::after {
        content: "📷 Scanner une page du BL";
        color: #1B2A3A;
        position: absolute;
        inset: 0;
        display: flex;
        align-items: center;
        justify-content: center;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

NB_ETAPES = 4
NOMS_ETAPES = {1: "Type d'opération", 2: "Numérisation des pages",
               3: "Informations du BL", 4: "Récapitulatif"}

# --- État du wizard ---
st.session_state.setdefault("etape", 1)
st.session_state.setdefault("donnees", {})
st.session_state.setdefault("pages", [])
st.session_state.setdefault("photo_en_cours", None)
st.session_state.setdefault("uploader_key", 0)
st.session_state.setdefault("extraction", None)
st.session_state.setdefault("extraction_statut", None)
st.session_state.setdefault("extraction_faite", False)
st.session_state.setdefault("analyse_seq", 0)
st.session_state.setdefault("enregistrement_lance", False)
st.session_state.setdefault("bl_insere", False)


def aller_a(etape) -> None:
    st.session_state.etape = etape
    st.rerun()


def reinitialiser_wizard() -> None:
    for cle in ("etape", "donnees", "pages", "photo_en_cours", "uploader_key",
                "extraction", "extraction_statut", "extraction_faite",
                "extraction_erreur", "analyse_seq", "enregistrement_lance",
                "bl_insere", "id_bl", "numero_final"):
        st.session_state.pop(cle, None)


def _parse_date(texte: str):
    try:
        return datetime.date.fromisoformat((texte or "")[:10])
    except Exception:
        return None


st.title("🗂️ Création de BL")
ui.show_flash()

etape = st.session_state.etape
if etape in NOMS_ETAPES:
    st.progress(etape / NB_ETAPES, text=f"Étape {etape}/{NB_ETAPES} — {NOMS_ETAPES[etape]}")

donnees = st.session_state.donnees

# =====================================================================
# ÉTAPE 1 — Type d'opération
# =====================================================================
if etape == 1:
    libelles_op = list(repository.LIBELLES_OPERATION.values())
    type_actuel = donnees.get("type_operation", repository.TYPE_RECEPTION)
    choix_op = st.radio(
        "Nature de l'opération *", libelles_op,
        index=libelles_op.index(repository.LIBELLES_OPERATION[type_actuel]),
    )
    type_op = next(t for t, l in repository.LIBELLES_OPERATION.items() if l == choix_op)
    st.caption("Étape suivante : scannez les pages du BL ; les informations "
               "seront pré-remplies automatiquement depuis l'image.")

    if st.button("Suivant ➡️", type="primary", use_container_width=True):
        if type_op != donnees.get("type_operation"):
            st.session_state.extraction_faite = False   # ré-analyser au besoin
        donnees["type_operation"] = type_op
        aller_a(2)

# =====================================================================
# ÉTAPE 2 — Numérisation des pages (scan)
# =====================================================================
elif etape == 2:
    st.caption(
        "Scannez chaque page du BL. Sur smartphone, le bouton ci-dessous "
        "propose directement l'appareil photo natif (qualité HD)."
    )
    photo = st.file_uploader(
        "Scanner une page du BL", type=["jpg", "jpeg", "png", "heic", "heif"],
        key=f"upl_{st.session_state.uploader_key}",
    )
    if photo is not None:
        octets = photo.getvalue()
        if octets:
            st.session_state.photo_en_cours = octets
        elif st.session_state.photo_en_cours is None:
            st.warning("La photo n'a pas été transmise (connexion interrompue ?). "
                       "Reprenez la photo.")
    photo_brute = st.session_state.photo_en_cours

    def abandonner_photo() -> None:
        st.session_state.photo_en_cours = None
        st.session_state.uploader_key += 1

    if photo_brute is not None:
        mode = st.radio("Rendu du scan", images.MODES_SCAN, index=2, horizontal=True,
                        help="La limite de taille et la compression s'appliquent "
                             "dans tous les modes.")
        cadrage_auto = st.toggle(
            "Cadrage automatique (détection du contour et redressement)", value=True,
            help="Désactivez si le cadrage automatique donne un résultat inattendu.")
        try:
            with st.spinner("Traitement de la page…"):
                page_traitee, redressee = images.scanner_document(photo_brute, mode, cadrage_auto)
            st.image(page_traitee, caption=f"Aperçu — {mode}", use_column_width=True)
            if cadrage_auto and not redressee:
                st.caption("ℹ️ Contour du document non détecté : la photo entière "
                           "est conservée, sans redressement.")
            with st.expander("Voir la photo originale"):
                try:
                    st.image(photo_brute, use_column_width=True)
                except Exception:
                    st.caption("Aperçu original indisponible pour ce format.")

            col_ajout, col_reprise = st.columns(2)
            if col_ajout.button("📎 Attacher au BL", type="primary", use_container_width=True):
                st.session_state.pages.append(page_traitee)
                st.session_state.extraction_faite = False   # nouvelle page -> ré-analyser
                abandonner_photo()
                ui.set_flash("toast", f"Page {len(st.session_state.pages)} attachée au BL")
                st.rerun()
            if col_reprise.button("🔄 Reprendre la photo", use_container_width=True):
                abandonner_photo()
                st.rerun()
        except Exception as e:
            st.error(f"Traitement impossible : {e}")
            if st.button("🔄 Reprendre la photo", use_container_width=True):
                abandonner_photo()
                st.rerun()

    if st.session_state.pages:
        st.write(f"📂 **{len(st.session_state.pages)} page(s) attachée(s) :**")
        ui.afficher_miniatures(st.session_state.pages)
        if st.button("🗑️ Détacher toutes les pages", use_container_width=True):
            st.session_state.pages = []
            st.session_state.extraction_faite = False
            st.rerun()

    col_prec, col_suiv = st.columns(2)
    if col_prec.button("⬅️ Précédent", use_container_width=True):
        aller_a(1)
    if col_suiv.button("Suivant ➡️", type="primary", use_container_width=True):
        if not st.session_state.pages:
            st.error("Attachez au moins une page avant de continuer.")
        else:
            aller_a(3)

# =====================================================================
# ÉTAPE 3 — Informations du BL (pré-remplies par l'IA + référentiel)
# =====================================================================
elif etape == 3:
    type_op = donnees.get("type_operation", repository.TYPE_RECEPTION)
    avec_plage_quai = repository.operation_avec_plage_et_quai(type_op)
    avec_statut = repository.operation_avec_statut(type_op)
    tiers = repository.libelle_tiers(type_op)
    est_vente = type_op in repository.TYPES_VENTE
    type_tiers = repository.TIERS_CLIENT if est_vente else repository.TIERS_FOURNISSEUR
    sens = repository.sens_operation(type_op)
    seq = st.session_state.analyse_seq   # suffixe de clés : bumpé par « Analyser »

    def _reset_si_absent(cle, options):
        """Évite l'erreur Streamlit quand la valeur mémorisée d'un selectbox
        n'est plus dans les options (ex. après filtrage) : on efface l'état
        pour que l'index par défaut s'applique."""
        if cle in st.session_state and st.session_state[cle] not in options:
            del st.session_state[cle]

    # Référentiel tiers : sert à la liste ET de contexte à l'IA.
    try:
        tous_tiers = repository.lister_tiers(type_tiers)
    except Exception as e:
        tous_tiers = []
        st.error(f"Impossible de charger la liste des {tiers.lower()}s : {e}")

    # --- Extraction IA (une fois) : toutes les pages, non bloquante. ---
    if not st.session_state.extraction_faite:
        if extraction.endpoint_configure() and st.session_state.pages:
            ref = extraction.Referentiel(
                tiers=tous_tiers,
                bls_pour_tiers=lambda nom: repository.bls_desadv_pour_tiers(nom, sens),
            )
            with st.spinner("Analyse du BL par l'IA (toutes les pages)…"):
                try:
                    st.session_state.extraction = extraction.extraire_infos_bl(
                        st.session_state.pages, tiers.lower(), referentiel=ref)
                    st.session_state.extraction_statut = "ok"
                except Exception as e:
                    logger.warning("Extraction IA en échec : %s", e, exc_info=True)
                    st.session_state.extraction = {}
                    st.session_state.extraction_statut = "echec"
                    st.session_state.extraction_erreur = f"{type(e).__name__} : {e}"
        else:
            st.session_state.extraction = {}
            st.session_state.extraction_statut = (
                "desactive" if not extraction.endpoint_configure() else "sans_page")
        st.session_state.extraction_faite = True

    ex = st.session_state.extraction or {}
    statut_ia = st.session_state.extraction_statut

    col_msg, col_btn = st.columns([4, 1])
    with col_msg:
        if statut_ia == "ok" and any(ex.values()):
            st.success("🔎 Champs pré-remplis par l'IA — vérifiez et corrigez si besoin.")
        elif statut_ia == "ok":
            st.info("🔎 L'IA n'a rien pu extraire des pages : saisie manuelle.")
        elif statut_ia == "echec":
            st.warning("Analyse IA momentanément indisponible : saisie manuelle.")
            detail = st.session_state.get("extraction_erreur")
            if detail:
                with st.expander("Détail technique de l'erreur"):
                    st.code(detail)
        else:
            st.caption("Analyse IA non configurée : saisie manuelle.")
    with col_btn:
        if extraction.endpoint_configure() and st.button("🔄 Analyser", use_container_width=True):
            st.session_state.analyse_seq += 1   # réinitialise les champs édités
            st.session_state.extraction_faite = False
            st.rerun()

    # --- Numéro de BL ---
    numero = st.text_input("Numéro du BL *", key=f"f_numero_{seq}",
                           value=donnees.get("numero") or ex.get("numero_bl", ""), max_chars=60)
    if ex.get("numero_bl"):
        st.caption(f"🔎 détecté : « {ex['numero_bl']} »")
    numero_pris = False
    if numero.strip():
        try:
            numero_pris = not repository.numero_bl_disponible(numero.strip())
        except Exception:
            pass
    if numero_pris:
        st.error(f"Le numéro de BL « {numero.strip()} » existe déjà.")

    # --- Date (détectée uniquement si manuscrite) ---
    date_defaut = (donnees.get("date_reception") or _parse_date(ex.get("date", ""))
                   or datetime.date.today())
    date_reception = st.date_input(
        "Date d'expédition *" if est_vente else "Date de réception *",
        value=date_defaut, key=f"f_date_{seq}")
    if ex.get("date"):
        st.caption(f"🔎 détecté (manuscrit) : « {ex['date']} »")
    # Notification si la date est éloignée d'aujourd'hui (réception/expédition
    # nouvelle) — sans bloquer le flux.
    if avec_plage_quai and date_reception:
        ecart = abs((date_reception - datetime.date.today()).days)
        if ecart > 7:
            st.warning(f"⚠️ La date retenue ({date_reception:%d/%m/%Y}) est éloignée "
                       f"d'aujourd'hui de {ecart} jours — vérifiez qu'elle est correcte.")

    # --- Plage horaire (réception/expédition) ---
    if avec_plage_quai:
        plage_defaut = (donnees["plage"] if donnees.get("plage") in repository.PLAGES_HORAIRES
                        else repository.plage_horaire_courante())
        plage = st.selectbox("Plage horaire *", options=repository.PLAGES_HORAIRES,
                             index=repository.PLAGES_HORAIRES.index(plage_defaut),
                             key=f"f_plage_{seq}")
    else:
        plage = None

    # --- Tiers : DESADV auto -> IA rapprochée (code puis nom) -> sélection ---
    frs_desadv = None
    if numero.strip() and not numero_pris:
        try:
            frs_desadv = repository.fournisseur_pour_bl(numero.strip(), sens)
        except Exception as e:
            st.warning(f"Consultation des avis d'expédition impossible : {e}")

    if frs_desadv:
        st.text_input(f"{tiers} (avis d'expédition) ✓", value=frs_desadv, disabled=True,
                      key=f"f_frsdesadv_{seq}",
                      help="Renseigné automatiquement via un avis d'expédition (DESADV).")
        fournisseur = frs_desadv
    else:
        tiers_reconnu, fiab_tiers = extraction.rapprocher_tiers(
            ex.get("code_tiers"), ex.get("tiers"), tous_tiers)
        detecte = " / ".join(x for x in (ex.get("code_tiers"), ex.get("tiers")) if x)
        if detecte:
            if tiers_reconnu:
                marque = "code ✓" if fiab_tiers == "code" else "nom ✓"
                st.caption(f"🔎 détecté : « {detecte} » — reconnu ({marque}) : {tiers_reconnu}")
            else:
                st.caption(f"🔎 détecté : « {detecte} » — non trouvé au référentiel, "
                           "choisissez manuellement.")

        filtre_frs = st.text_input("Filtrer la liste", value="", key=f"f_filtre_{seq}",
                                   placeholder="Tapez quelques lettres pour filtrer…")
        if filtre_frs.strip():
            tiers_affiches = [f for f in tous_tiers if filtre_frs.strip().lower() in f.lower()]
        else:
            tiers_affiches = tous_tiers

        pre = donnees.get("fournisseur") or tiers_reconnu
        index_frs = tiers_affiches.index(pre) if pre in tiers_affiches else (
            0 if len(tiers_affiches) == 1 else None)
        _reset_si_absent(f"f_tiers_{seq}", tiers_affiches)
        fournisseur = st.selectbox(f"{tiers} *", options=tiers_affiches,
                                   index=index_frs, placeholder="Choisir…",
                                   key=f"f_tiers_{seq}")

    # --- Quai (détecté uniquement si manuscrit) ---
    if avec_plage_quai:
        try:
            quais = repository.lister_quais()
        except Exception as e:
            quais = []
            st.error(f"Impossible de charger les quais : {e}")
        quai_reconnu = extraction.rapprocher(ex.get("quai", ""), quais)
        pre_quai = donnees.get("quai") or quai_reconnu
        index_quai = quais.index(pre_quai) if pre_quai in quais else None
        _reset_si_absent(f"f_quai_{seq}", quais)
        quai = st.selectbox("Quai *", options=quais, index=index_quai,
                            placeholder="Choisir le quai…", key=f"f_quai_{seq}")
        if ex.get("quai"):
            st.caption(f"🔎 détecté (manuscrit) : « {ex['quai']} »"
                       + (" ✓ reconnu" if quai_reconnu else ""))
    else:
        quai = None

    # --- État de réception (manuscrit ; NOK≡EDI NOK, OK≡EDI OK) ---
    if avec_statut:
        ex_nok = extraction.statut_est_nok(ex.get("statut"))
        if donnees.get("statut") is not None:
            defaut_nok = donnees.get("statut") == repository.STATUT_EDI_NOK
        else:
            defaut_nok = bool(ex_nok)
        choix = st.radio("État de réception *", ["OK", "EDI NOK"],
                         index=1 if defaut_nok else 0, horizontal=True, key=f"f_statut_{seq}")
        statut = repository.STATUT_OK if choix == "OK" else repository.STATUT_EDI_NOK
        if ex.get("statut"):
            st.caption(f"🔎 détecté (manuscrit) : « {ex['statut']} »")
    else:
        statut = repository.STATUT_OK

    # --- Commentaire ---
    if avec_plage_quai:
        commentaire = st.text_area("Commentaire (facultatif)", key=f"f_comment_{seq}",
                                   value=donnees.get("commentaire") or ex.get("commentaire", ""),
                                   max_chars=1000)
    else:
        commentaire = ""

    col_prec, col_suiv = st.columns(2)
    if col_prec.button("⬅️ Précédent", use_container_width=True):
        aller_a(2)
    if col_suiv.button("Suivant ➡️", type="primary", use_container_width=True):
        if not numero.strip():
            st.error("Le numéro de BL est obligatoire.")
        elif numero_pris:
            st.error(f"Le numéro de BL « {numero.strip()} » existe déjà.")
        elif not fournisseur:
            st.error(f"Le {tiers.lower()} est obligatoire.")
        elif avec_plage_quai and not quai:
            st.error("Le quai est obligatoire.")
        else:
            donnees.update({
                "numero": numero.strip(), "date_reception": date_reception,
                "plage": plage, "fournisseur": fournisseur,
                "fournisseur_desadv": bool(frs_desadv), "quai": quai,
                "statut": statut, "commentaire": commentaire.strip(),
            })
            aller_a(4)

# =====================================================================
# ÉTAPE 4 — Récapitulatif et enregistrement
# =====================================================================
elif etape == 4:
    st.subheader("Récapitulatif")
    type_op = donnees.get("type_operation", repository.TYPE_RECEPTION)
    avec_plage_quai = repository.operation_avec_plage_et_quai(type_op)
    origine_frs = " (avis d'expédition)" if donnees.get("fournisseur_desadv") else ""

    lignes = [
        ("Opération", repository.LIBELLES_OPERATION.get(type_op, type_op)),
        ("Numéro de BL", donnees.get("numero", "")),
        ("Date", donnees.get("date_reception", "")),
    ]
    if avec_plage_quai:
        lignes.append(("Plage horaire", donnees.get("plage") or "—"))
    lignes.append((repository.libelle_tiers(type_op),
                   f'{donnees.get("fournisseur", "")}{origine_frs}'))
    if avec_plage_quai:
        lignes.append(("Quai", donnees.get("quai", "")))
    if repository.operation_avec_statut(type_op):
        lignes.append(("État de réception",
                       ui.libelle_statut(donnees.get("statut", repository.STATUT_OK))))
    if avec_plage_quai:
        lignes.append(("Commentaire", donnees.get("commentaire") or "—"))
    lignes.append(("Pages", len(st.session_state.pages)))

    st.markdown("| | |\n|---|---|\n"
                + "\n".join(f"| **{label}** | {valeur} |" for label, valeur in lignes))

    if st.session_state.enregistrement_lance:
        with st.spinner("Enregistrement dans Lakebase…"):
            try:
                id_bl = st.session_state.setdefault("id_bl", str(uuid.uuid4()))
                utilisateur = get_current_user()

                if not st.session_state.bl_insere:
                    repository.inserer_bl(
                        id_bl=id_bl,
                        numero_bl=donnees["numero"],
                        nom_fournisseur=donnees["fournisseur"],
                        statut_bl=donnees["statut"],
                        type_operation=type_op,
                        utilisateur=utilisateur,
                        date_reception=donnees.get("date_reception"),
                        quai_reception=donnees.get("quai"),
                        comment_bl=donnees["commentaire"],
                        plage_horaire=donnees.get("plage"),
                    )
                    st.session_state.numero_final = donnees["numero"]
                    st.session_state.bl_insere = True

                deja = repository.pages_enregistrees(id_bl)
                for idx, page in enumerate(st.session_state.pages):
                    if idx not in deja:
                        repository.enregistrer_page(id_bl, idx, page)

                st.session_state.enregistrement_lance = False
                aller_a("succes")
            except ValueError as e:
                st.session_state.enregistrement_lance = False
                st.error(str(e))
                st.info("Revenez à l'étape 3 pour saisir un autre numéro de BL.")
            except Exception as e:
                st.session_state.enregistrement_lance = False
                st.error(f"Échec de l'enregistrement : {e}")
                st.info("Vos saisies sont conservées : corrigez si besoin via « Précédent ».")

    col_prec, col_val = st.columns(2)
    if col_prec.button("⬅️ Précédent", use_container_width=True, disabled=st.session_state.enregistrement_lance):
        aller_a(3)
    if col_val.button("💾 Valider", type="primary", use_container_width=True,
                      disabled=st.session_state.enregistrement_lance):
        st.session_state.enregistrement_lance = True
        st.rerun()

# =====================================================================
# ÉCRAN DE SUCCÈS
# =====================================================================
elif etape == "succes":
    st.success(f"BL n° {st.session_state.get('numero_final', '')} enregistré avec succès ✅")
    if st.button("🆕 Créer un nouveau BL", type="primary", use_container_width=True):
        reinitialiser_wizard()
        st.rerun()
