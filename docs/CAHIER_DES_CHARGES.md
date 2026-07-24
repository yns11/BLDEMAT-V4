---
title: "Cahier des charges — Solution « BL dématérialisés »"
subtitle: "Document rétrospectif et modèle réutilisable — eMotors"
date: "Version 1.0 — Juillet 2026"
lang: fr
---

> **Mode d'emploi du modèle** — *Ce cahier des charges décrit la solution
> réellement livrée (rétrospectif). Pour l'utiliser comme modèle d'un futur
> projet : dupliquer le document, remplacer les mentions `eMotors` et les
> contenus spécifiques, et suivre les indications en italique `[À adapter]`
> présentes dans chaque section. Les identifiants d'exigences (EF-xx, ENF-xx)
> sont à conserver : ils servent de référence dans les tests et la recette.*

# 1. Suivi du document

| Version | Date | Auteur | Objet |
|---|---|---|---|
| 1.0 | Juillet 2026 | Équipe Data eMotors | Version rétrospective initiale (V6 de la solution) |
|  |  |  | *[À adapter : ajouter une ligne par évolution]* |

# 2. Contexte et objectifs

## 2.1 Contexte

Les bordereaux de livraison (BL) papier des flux de réception et d'expédition
sont archivés physiquement, difficilement consultables, et le rapprochement
avec les avis d'expédition EDI (DESADV) de l'ERP est manuel.
*[À adapter : décrire le processus actuel et ses irritants.]*

## 2.2 Objectifs

| # | Objectif | Indicateur de succès |
|---|---|---|
| O1 | Dématérialiser la saisie des BL au quai (smartphone) | 100 % des BL saisis dans l'app, ≤ 2 min par BL |
| O2 | Fiabiliser les données par l'IA (pré-remplissage) et les référentiels | Précision extraction mesurée (vue Qualité IA) |
| O3 | Rapprocher automatiquement BL ⇄ DESADV et suivre les anomalies (NOK) | Vue Rapprochement à zéro écart non expliqué |
| O4 | Donner un pilotage temps réel (KPI, tableaux de bord) | Adoption par les gestionnaires |
| O5 | Notifier les passages EDI NOK → OK (email / Teams) | Notification < 1 h après l'événement |

*[À adapter : 3 à 6 objectifs mesurables maximum.]*

# 3. Périmètre

## 3.1 Inclus

- Application **Création de BL** (opérateurs au quai, mobile d'abord) :
  4 opérations — nouvelle réception, nouvelle expédition, archivage d'un
  ancien BL réception, archivage d'un ancien BL expédition.
- Application **Administration des BL** (gestionnaires / ADV / finance /
  administrateurs) : tableau de bord, vues BL, DESADV, rapprochement,
  référentiels, RBAC.
- **Jobs** : synchronisation des référentiels ERP, rapprochement BL ⇄ DESADV,
  envoi des notifications (Teams / Power Automate).
- Stockage des métadonnées **et des images** dans Lakebase (Postgres managé).

## 3.2 Exclus

- Signature électronique des BL ; portail fournisseur externe ; DESADV vente
  automatique (alimenté manuellement) ; envoi d'emails direct par SMTP.
  *[À adapter : liste explicite des exclusions, pour éviter toute ambiguïté.]*

# 4. Acteurs et rôles (RBAC)

| Rôle | Population | App Création | App Administration |
|---|---|---|---|
| LOG | Opérateurs logistiques | Nouvelle réception, nouvelle expédition | — |
| APPROS | Approvisionneurs | Archivage réception | BL réception (modification), DESADV & Rapprochement achat (lecture), Notifications (lecture) |
| ADV | Administration des ventes | Archivage expédition | BL expédition (modification), DESADV & Rapprochement vente (lecture), Notifications (lecture) |
| FINANCE | Contrôle / finance | — | BL réception & expédition (lecture), Rapprochements (lecture) |
| ADMIN_METIER | Administrateurs métier | Tout | Tout (y compris module Gestion et Rôles) |

Principes : les rôles sont stockés en base (`roles_utilisateurs`, un
utilisateur peut cumuler) ; la matrice des droits par vue est **versionnée
dans le code** (`bl_core/rbac.py`) ; table vide = mode ouvert (recette) ;
les vues sans droit sont **masquées**, le niveau lecture retire toute action
d'écriture. *[À adapter : la matrice détaillée est dans rbac.py.]*

# 5. Architecture

## 5.1 Composants

| Composant | Technologie | Rôle |
|---|---|---|
| App Création | Databricks Apps — Streamlit 1.49 (Python 3.11) | Saisie des BL au quai, extraction IA, mode hors-ligne |
| App Administration | Databricks Apps — Streamlit 1.49 | Pilotage, CRUD, RBAC, exports |
| Base de données | Lakebase (Postgres managé, scale-to-zero) | Métadonnées + images (BYTEA) + référentiels |
| Extraction IA | Model serving Databricks (`databricks-claude-opus-4-8`) | Lecture des BL scannés (vision multimodale) |
| Jobs | Lakeflow Jobs serverless (notebooks Python) | Sync ERP, rapprochement, notifications |
| Notifications | Webhook Teams + flux Power Automate | Email / carte Teams sur passage NOK → OK |
| Code partagé | `shared/bl_core` (copié dans chaque app par `tools/sync_shared`) | Repository, UI, extraction, RBAC, PDF |

## 5.2 Flux principaux

1. **Saisie** : photo → correction de perspective (OpenCV) → compression
   (≤ 2 Mo/page) → extraction IA multi-passes → rapprochement référentiels →
   enregistrement Lakebase (BL + pages + audit + qualité IA).
2. **EDI** : ERP (`siledimessage`, `siledi_item_line`, `purch_table`,
   `sales_table`) → job quotidien → staging Unity Catalog → upsert Lakebase
   (`base_tiers`, `base_desadv` avec `statut_edi`) → marquage
   `desadv_rapproche` des BL.
3. **Notifications** : passage EDI NOK → OK journalisé (`notifications`) →
   job horaire → Teams / Power Automate → `envoyee = true`.

## 5.3 Sécurité et authentification

- Accès aux apps : **SSO Databricks (OAuth)**, permission « Can use » par
  app ; identité (email) transmise à l'app par en-têtes ; **RBAC applicatif**
  en second niveau.
- Accès aux données : chaque app se connecte à Lakebase avec le **jeton OAuth
  de son service principal** (renouvelé avant expiration ~45 min) ; GRANT
  Postgres par app (moindre privilège) ; requêtes 100 % paramétrées.
- Aucun secret en dur ; l'appel au LLM utilise l'authentification runtime.

# 6. Exigences fonctionnelles

## 6.1 Application « Création de BL »

| ID | Exigence |
|---|---|
| EF-C-01 | Assistant en 4 étapes : type d'opération → numérisation → informations pré-remplies → récapitulatif/validation. |
| EF-C-02 | Les opérations proposées à l'étape 1 sont filtrées par les rôles RBAC de l'utilisateur. |
| EF-C-03 | Capture photo native smartphone ; formats JPG/PNG/HEIC ; cadrage automatique débrayable ; aperçu et reprise. |
| EF-C-04 | Pages compressées ≤ 2 Mo, stockées en base ; multi-pages ; miniatures ; détachement possible. |
| EF-C-05 | Extraction IA (si endpoint configuré) : toutes les pages (max 4), numéro, code tiers (S-/C-000000), raison sociale, statut/date manuscrits, commentaire ; rapprochement itératif avec les référentiels (code prioritaire, DESADV du tiers, adresses de sites) ; repli manuel non bloquant. |
| EF-C-06 | Statuts manuscrits : « NOK » ≡ « EDI NOK », « OK » ≡ « EDI OK » ; date éloignée (> 7 j) signalée sans bloquer. |
| EF-C-07 | Quai pré-rempli depuis le PLA du tiers, défaut « B15 » ; jamais demandé à l'IA. |
| EF-C-08 | Numéro de BL unique (insensible à la casse), vérifié à la saisie ET par contrainte en base ; tiers auto-rempli par le DESADV correspondant s'il existe. |
| EF-C-09 | Bouton « Analyser » : relance l'extraction et réinitialise les champs, y compris édités. |
| EF-C-10 | Journal qualité IA : « valeur IA vs valeur validée » champ par champ au passage de l'étape 3. |
| EF-C-11 | Mode hors-ligne : pages répliquées en localStorage, restaurées après coupure réseau, purgées après enregistrement (limite : quota navigateur ~5 Mo). |
| EF-C-12 | Enregistrement idempotent (reprise sur échec sans doublon de pages) ; audit de création. |

## 6.2 Application « Administration des BL »

| ID | Exigence |
|---|---|
| EF-A-01 | Navigation latérale par sections (Général / Achat / Vente / Gestion), toutes vues visibles, filtrée par le RBAC ; logo eMotors. |
| EF-A-02 | Tableau de bord : KPI (BL, réceptions, expéditions, RECEPTIONS NOK, taux, DESADV NOK) avec deltas vs période précédente ; activité en heatmap type « contributions GitHub » commutable — par jour (année civile, BL nouveaux) ou par plage horaire (trimestre, 9 plages) — indépendante des filtres de dates ; courbes d'évolution % RECEPTIONS NOK et % DESADV NOK (réceptions, tous filtres) ; top 10 des pires fournisseurs en % NOK combiné. |
| EF-A-03 | Vues BL réception/expédition : KPI, filtres en boutons (périodes multi-sélection : aujourd'hui/hier/semaine/mois/personnalisé ; état ; gestionnaire), chips retirables une à une + « Effacer les filtres », défaut hier+aujourd'hui+EDI NOK, pagination 50, sélection au clic de ligne ou cases à cocher. |
| EF-A-04 | Ruban contextuel : Actualiser, Modifier (fiche), Voir les images (visionneuse zoom/rotation/impression/téléchargement), Export PDF (métadonnées + pages), Historique (audit imprimable), Passer à OK, Supprimer (logique) / Restaurer. |
| EF-A-05 | Toute modification ou suppression passe par une **boîte de confirmation**. |
| EF-A-06 | Vues DESADV achat/vente : colonne/filtre/KPI « État EDI » (OK / EDI NOK), fraîcheur du flux EDI affichée, grille CRUD (numéro unique par sens), horodatages EDI en lecture seule. |
| EF-A-07 | Vues « Rapprochement BL / DESADV » (achat et vente) : BL sans DESADV et DESADV sans BL, filtres fournisseur/gestionnaire/dates. |
| EF-A-08 | Référentiels en CRUD (grilles éditables + confirmation) : Fournisseurs, Clients, Gestionnaires, Portefeuilles, Quais, Adresses, Sites logistiques, PLA, Rôles ; toutes les grilles triables. |
| EF-A-09 | Écrans utilisateur : sauvegarde nommée des filtres/tri/colonnes par vue, rappel en un clic, **écran par défaut appliqué à chaque changement de vue** et à la reconnexion. |
| EF-A-10 | Passage EDI NOK → OK : journalisé dans `notifications` (consommé par le job d'envoi) ; vue Notifications en lecture. |
| EF-A-11 | Vue Qualité IA : taux de précision par champ + journal détaillé. |

## 6.3 Jobs et intégrations

| ID | Exigence |
|---|---|
| EF-J-01 | Job quotidien de synchronisation ERP : fournisseurs, clients, DESADV achat (avec `messagestate` → OK / EDI NOK rafraîchi à chaque run) ; upsert non destructif (saisies manuelles préservées). |
| EF-J-02 | Le même job marque `desadv_rapproche` sur les BL dont le numéro correspond à un DESADV du bon sens (insensible à la casse). |
| EF-J-03 | Job horaire d'envoi des notifications : webhook Teams et/ou flux Power Automate (HTTP → email Outlook) ; `envoyee = true` seulement après succès de tous les canaux configurés ; relivraison sinon. |
| EF-J-04 | Les jobs utilisent l'environnement serverless (dépendances déclarées) et l'authentification `generate_database_credential`. |

# 7. Exigences non fonctionnelles

| ID | Exigence |
|---|---|
| ENF-01 | **Mobile d'abord** (app Création) : utilisable à une main au quai, appareil photo natif, libellés métier. |
| ENF-02 | **Performance** : affichage des vues < 2 s en usage courant ; référentiels en cache (TTL 5 min) ; photos en cache ; requêtes paginées et agrégées côté base. |
| ENF-03 | **Résilience** : reconnexion automatique à Lakebase (réveil scale-to-zero), jeton renouvelé avant expiration, enregistrement idempotent, extraction IA non bloquante, audit/qualité en best-effort (n'interrompent jamais le métier). |
| ENF-04 | **Sécurité** : SSO + RBAC + moindre privilège SQL par service principal ; aucune donnée sensible en clair dans le code ; traçabilité complète (audit_bl). |
| ENF-05 | **Maintenabilité** : code partagé unique (`bl_core`), design system en jetons CSS, migrations SQL idempotentes et versionnées, tests AppTest automatisés, versions épinglées. |
| ENF-06 | **Observabilité** : logs structurés JSON (stdout) ; échecs de jobs notifiés par email ; fraîcheur EDI visible. |
| ENF-07 | **Langue** : interface et documentation 100 % en français. |
| ENF-08 | **Conservation** : suppression logique des BL (restaurables) ; images conservées ; *[À adapter : politique de rétention/purge]*. |

# 8. Modèle de données (schéma `bl_demat`)

| Table | Rôle | Clé |
|---|---|---|
| suivi_bl | BL (métadonnées, statut, rapprochement, suppression logique) | id_bl ; numero_bl unique (casse ignorée) |
| pieces_jointes_bl | Pages scannées (BYTEA) | id_photo → id_bl |
| base_tiers | Fournisseurs et clients (`code : raison sociale`) | name |
| base_desadv | Avis d'expédition EDI, `statut_edi`, horodatages | (numero_bl, sens) |
| gestionnaires / portefeuilles | Approvisionneurs et leurs fournisseurs | code ; (code, fournisseur) |
| quais / adresses / sites_logistiques | Référentiels logistiques | code_quai ; adresse ; (entite, adresse) |
| pla | Protocole logistique (quai, jours, fréquence) par tiers | nom_fournisseur |
| roles_utilisateurs | RBAC (utilisateur × rôle) | (utilisateur, role) |
| audit_bl | Historique : qui a changé quoi, quand | id (identity) |
| qualite_extraction | Valeur IA vs valeur validée, par champ | id (identity) |
| ecrans_utilisateur | Écrans sauvegardés (filtres/tri/colonnes) | (utilisateur, vue, nom) |
| notifications | Événements notifiables + statut d'envoi | id (identity) |

Scripts : `sql/init_lakebase.sql` (environnement neuf) ; migrations
incrémentales `migration_*.sql` (idempotentes) ; `seed_fake_bl.sql` (données
de démonstration).

# 9. Déploiement

1. Créer le projet **Lakebase** ; exécuter `init_lakebase.sql` (ou les
   migrations sur un environnement existant) dans l'éditeur SQL du projet.
2. Créer les **deux apps** ; attacher la ressource Database (clé `postgres`)
   et, pour la Création, la ressource **Serving endpoint** (Can query) ;
   variable `BL_LLM_ENDPOINT`.
3. Renseigner les **GRANT** avec les client ID des service principals ;
   donner « Can use » aux utilisateurs ; affecter les **rôles** (s'attribuer
   ADMIN_METIER en premier).
4. Créer les **jobs** (`jobs/*.json`) : sync quotidienne, envoi horaire des
   notifications (webhook Teams / URL Power Automate en paramètres).
5. Recette : jeux d'exemple (`BL-2026-0001`…), vue Qualité IA, écrans.

*[À adapter : environnements DEV/PROD, noms des apps et du projet.]*

# 10. Tests et recette

- **Tests automatisés** (Streamlit AppTest + pytest, sans base ni LLM
  réels) : extraction (parsing, rapprochements, orchestration multi-passes),
  wizard Création (pré-remplissage, replis, PLA), app Administration
  (navigation, KPI, vues, RBAC lecture/masquage).
- **Recette métier** : un scénario par exigence EF-xx, tracé dans un PV de
  recette. *[À adapter : tableau de cas de tests avec résultat attendu.]*
- Critères d'acceptation : toutes les EF couvertes, aucune anomalie
  bloquante, RBAC vérifié pour chaque rôle.

# 11. Glossaire

| Terme | Définition |
|---|---|
| BL | Bordereau de livraison (réception ou expédition) |
| DESADV | Avis d'expédition EDI (DESpatch ADVice) annonçant une livraison |
| EDI NOK / OK | État du message EDI (`messagestate` 3 / 2) ou état manuscrit d'une réception |
| PLA | Protocole logistique d'achat (quai, jours, fréquence par tiers) |
| RBAC | Contrôle d'accès basé sur les rôles |
| Lakebase | Postgres managé Databricks (scale-to-zero) |
| DESADV rapproché | BL dont le numéro correspond à un DESADV intégré |

---

*Document généré à partir de la solution en production (V6). Les sources —
code, SQL, jobs, tests — font foi pour le détail d'implémentation.*
