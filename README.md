# BL dématérialisés — V3 (Lakebase)

Troisième version de la solution, 100 % Lakebase (Postgres managé Databricks) :
métadonnées ET photos en base, aucune dépendance à Unity Catalog, aucun GRANT
admin requis (le créateur du projet Lakebase a tous les droits).

**À déployer sur un NOUVEAU projet Lakebase et deux NOUVELLES apps** (par
exemple `bl-creation-v3` et `bl-administration-v3`) pour ne pas écraser la V2.

## Nouveautés V7

- **Tableau de bord refondu** : activité en heatmap « contributions GitHub »
  commutable — **par jour** (année civile en cours, BL nouveaux hors
  archivages) ou **par plage horaire** (trimestre en cours, 9 plages) —
  indépendante des filtres de dates ; **courbes d'évolution % NOK**
  (RECEPTIONS NOK et DESADV NOK, réceptions uniquement, tous filtres) ;
  **top 10 des pires fournisseurs** en % NOK combiné ; cartes renommées
  RECEPTIONS NOK / DESADV NOK ; anciens graphiques retirés.
- Vues d'écarts renommées **« Rapprochement BL / DESADV »** avec les filtres
  habituels (fournisseur, gestionnaire, période).
- **Écran par défaut chargé à chaque changement de vue** (celui de
  l'utilisateur, sinon l'écran standard) — plus seulement à la reconnexion.
- Espace vertical au-dessus de l'entête réduit de 35 %.
- **Cahier des charges** rétrospectif et réutilisable :
  `docs/CAHIER_DES_CHARGES.md` (source du modèle, converti en Word via
  pandoc).

## Nouveautés V6

**Notifications réellement envoyées** — nouveau job `bl-v3-envoi-notifications`
(`jobs/notebook_envoi_notifications.py`, planifié toutes les heures) : lit les
notifications `envoyee = false` et les pousse vers un **webhook Teams** et/ou
un **flux Power Automate** (URL « requête HTTP reçue » → email Outlook, etc.),
puis marque `envoyee = true` (relivraison au prochain run en cas d'échec).
Flux Power Automate à créer : déclencheur *« Lorsqu'une requête HTTP est
reçue »* (schéma JSON : numero_bl, type_notif, message, cree_le, cree_par) →
action *« Envoyer un email (V2) »* ; coller l'URL du flux dans le paramètre
`power_automate_url` du job.

**Rapprochement BL ⇄ DESADV** — le job de synchronisation marque les BL dont
le numéro correspond à un DESADV intégré (colonne « DESADV 🔗 ✓ » des vues
BL) ; nouvelles vues **Écarts achat / Écarts vente** (BL sans DESADV,
DESADV sans BL).

**Vues BL enrichies** — **📄 Export PDF** du BL (page de garde métadonnées +
pages scannées, pour archivage/litiges) et **🕘 Historique** (table
`audit_bl` : qui a changé quoi, quand — créations, modifications champ par
champ, suppressions, restaurations — **imprimable**).

**Qualité de l'extraction IA** — l'app Création journalise « valeur IA vs
valeur validée » champ par champ au passage de l'étape 3 ; vue **Gestion ▸
Qualité IA** : taux de précision par champ + journal (pour améliorer le
prompt).

**File d'attente hors-ligne (smartphone)** — les pages scannées sont copiées
dans le navigateur (localStorage) : si le réseau coupe en quai, elles sont
**restaurées automatiquement** au retour sur l'étape 2 et l'enregistrement
peut être rejoué (limite : quota navigateur ~5 Mo ; nettoyé après succès).

**Confort** — fraîcheur du flux EDI affichée en haut à droite des vues
DESADV ; **🖥️ Écrans** : sauvegarde nommée des filtres/tri/colonnes d'une
vue, rappel en un clic, **écran par défaut** appliqué à chaque reconnexion ;
bouton **🧹 Effacer les filtres** à côté des chips ; sélecteur de
**colonnes affichées** ; tableau de bord : heatmap d'activité façon
« contributions GitHub ».

## Nouveautés V5

**PLA (protocole logistique d'achat)** — table `pla` (un protocole par tiers :
quai, jours de livraison, fréquence) et vue CRUD dans Gestion. Dans l'app
Création, le **quai est pré-rempli automatiquement** depuis le PLA du tiers
détecté/saisi (défaut « B15 » sans PLA) — l'IA ne cherche plus le quai.

**Filtres modernisés (app Administration)**
- Listes déroulantes remplacées par des **boutons (pills)** avec icônes
  (état, période, périmètre) ; gestionnaires en boutons sans icônes.
- **Périodes en boutons multi-sélection** : Aujourd'hui / Hier / Cette
  semaine / Ce mois / **Personnalisé** (fenêtre de choix des dates). Défaut
  des vues BL et DESADV : **Hier + Aujourd'hui**, et état **EDI NOK**.
- **Chips horizontales** des filtres appliqués, retirables une à une (✕).

**Vues et grilles**
- **KPI** en tête des vues BL (périmètre, EDI NOK, OK, taux, pages jointes).
- **Toutes les grilles sont triables** (en-têtes des tableaux ; « Trier
  par » en pills pour les grilles éditables à lignes dynamiques).
- **Fournisseurs et Clients déplacés dans Gestion.**
- **Confirmation systématique** (boîte de dialogue) avant toute modification
  ou suppression : grilles référentiels/DESADV, fiche BL, passage à OK,
  restauration, suppression.
- **Tableau de bord enrichi** : KPI avec **deltas vs période précédente**,
  compteur DESADV EDI NOK, donut du mix d'opérations.

**RBAC (contrôle d'accès basé sur les rôles)** — voir la section dédiée :
rôles LOG / APPROS / ADV / FINANCE / ADMIN_METIER, matrice portée par
`bl_core/rbac.py`, affectations dans la table `roles_utilisateurs`
(vue Gestion ▸ Rôles). Les vues sans droit sont **masquées** ; le niveau
« lecture » retire toutes les actions d'écriture.

## Nouveautés V4

**Extraction assistée par IA (app Création)** — le wizard passe à **4 étapes** :
1. **Type d'opération** (les 4 opérations) ;
2. **Numérisation** des pages (scan) ;
3. **Informations du BL** : les champs sont **pré-remplis automatiquement** par
   un modèle de vision (LLM) appelé via un **endpoint de model serving**
   Databricks, puis **rapprochés des référentiels** ; sans correspondance — ou
   si l'IA est indisponible/non configurée — l'utilisateur reprend la **saisie
   semi-manuelle** (rien de bloquant). Détails :
   - **toutes les pages** du BL sont analysées ensemble ;
   - le **numéro**, le **code tiers** (S-000000 / C-000000) et la **raison
     sociale** sont lus sur le texte imprimé ; le **statut** (OK/NOK, où
     « EDI NOK » ≡ « NOK »), la **date** et le **quai** ne sont retenus que
     s'ils sont **manuscrits** ;
   - rapprochement du tiers **par code d'abord** (fiable), puis par raison
     sociale ; du numéro de BL par inclusion préfixe/suffixe avec les DESADV
     du tiers ;
   - **rapprochement itératif** : si le premier appel ne suffit pas, l'IA est
     relancée en lui fournissant la liste des tiers, puis les BL du tiers
     reconnu (contexte ciblé pour limiter les tokens) ;
   - une **date éloignée** d'aujourd'hui est signalée (sans bloquer) ; le
     bouton **🔄 Analyser** relance l'analyse et réinitialise les champs ;
4. **Récapitulatif** et validation.

L'appel LLM utilise l'authentification runtime de l'app (aucun jeton en dur).
Il est **optionnel** : activé uniquement si la variable `BL_LLM_ENDPOINT`
est renseignée (voir `sql`/`app.yaml`) et si la ressource *Serving endpoint*
est ajoutée à l'app. Voir `shared/bl_core/extraction.py`.

**État des messages EDI (DESADV)**
- Le job ERP remonte `messagestate` (2 → **OK**, 3 → **EDI NOK**) dans la
  colonne `statut_edi` de `base_desadv`, **rafraîchie à chaque run** (l'état
  d'un message évolue). Les vues DESADV l'affichent en colonne (lecture
  seule), en **filtre** et en **KPI** (avis, EDI OK, EDI NOK, taux).

**Adresses et sites logistiques (module Gestion)**
- Nouvelles tables `adresses` (référentiel d'adresses) et `sites_logistiques`
  (entité tiers → adresse, même fonctionnement que gestionnaires/
  portefeuilles), avec leurs vues CRUD. Quand des sites sont renseignés,
  leurs adresses sont injectées dans le contexte du rapprochement IA.

**Interface refondue (streamlit 1.49)**
- **Navigation latérale** : sections (Général / Achat / Vente / Gestion) en
  intitulés, **toutes les vues visibles** en permanence, item actif surligné.
- **Vues BL** : le ruban s'active **dès le clic sur une ligne** (n'importe
  quelle cellule) ; les cases à cocher restent disponibles pour les actions
  de masse.
- **Visionneuse d'images** plein format (fenêtre large) : zoom +/-,
  ajustement, rotation, **impression** et **téléchargement** page par page.
- **Design system** : jetons CSS (couleurs, rayons, ombres) et échelle
  typographique (ratio 1,25) dans `bl_core/ui.py` ; KPI en cartes.

## Nouveautés V3

**Modèle de données**
- Numéro de BL **unique** (insensible à la casse) : plus de suffixe -1/-2,
  l'application refuse le doublon avec un message clair.
- Nouvelles tables : `gestionnaires` (préremplie appro 1 → appro 8),
  `portefeuilles` (gestionnaire → fournisseurs, N par gestionnaire),
  `quais` (référentiel géré dans l'app Admin), `base_tiers` (fournisseurs ET
  clients), `base_desadv` avec un sens ACHAT / VENTE.

**App Création**
- Quatre opérations : Nouvelle réception, Nouvelle expédition, Archivage d'un
  ancien BL réception, Archivage d'un ancien BL expédition.
  - Nouvelle expédition : date, plage horaire, quai et commentaire comme une
    réception (sans l'état OK/EDI NOK).
  - Archivages : numéro, date et tiers uniquement.
- DESADV consulté dans le bon sens (achat pour les réceptions, vente pour les
  expéditions) ; libellé Client/Fournisseur selon l'opération.
- Libellés : bouton de capture « 📷 Scanner une page du BL », action
  « 📎 Attacher au BL ».

**App Administration — expérience « model-driven »**
- **Logo eMotors** en haut de la barre latérale (navigation plus grande et
  aérée, vues indentées sous le module sélectionné).
- **Tableau de bord** interactif (entrée en haut, avant les modules) : KPI
  (BL total, réceptions, expéditions, archivages, EDI NOK, taux) et
  graphiques (volume/jour achat vs vente, top tiers, OK vs EDI NOK),
  filtrables par plage de dates et périmètre.
- Navigation latérale par modules : **Achat** (BL réception, DESADV achat,
  Fournisseurs), **Vente** (BL expédition, DESADV vente, Clients),
  **Gestion** (Gestionnaires, Portefeuilles, Quais, **Notifications**).
- Vues BL : grille avec cases à cocher pour les actions de masse (passer à OK,
  supprimer, restaurer), fiche de modification en boîte de dialogue. 50 lignes
  par page. **BL réception** filtrable par **gestionnaire**.
- **DESADV** : colonnes « Créé le » et « Date d'intégration » (flux EDI) ;
  filtres numéro de BL, tiers, gestionnaire et dates ; numéro de BL **unique**
  par sens (doublons interdits).
- **Portefeuilles** filtrables par gestionnaire et fournisseur.
- **Notifications** : journal en lecture seule des passages EDI NOK → OK
  (l'email a été remplacé par cet enregistrement en base ; un flux Power
  Automate pourra les envoyer ultérieurement).
- Vues référentiels : grille éditable (ajout / modification / suppression) +
  bouton Enregistrer — CRUD complet.

## Déploiement pas à pas

1. **Créer un nouveau projet Lakebase** (UI Databricks → section base de
   données/OLTP → Create project), par exemple `demat-bl-v3`.
2. **Créer les deux apps** : `bl-creation-v3` et `bl-administration-v3`
   (Compute → Apps → Create app, app personnalisée). Sur chacune :
   **Edit → Resources → + Add resource → Database (Lakebase/Postgres)** :
   projet V3, branche `production`, base `databricks_postgres`, permission
   **Can connect and create**, clé `postgres`.
3. **Déployer le code** : dossier Git (ou upload) puis Deploy en pointant
   `src/app_creation` / `src/app_administration` de CE dossier (`v3`).
   Les variables PG* sont injectées par la ressource ; le mot de passe est le
   jeton OAuth du service principal, généré par le code.
4. **Créer les tables et les droits** : récupérer le client ID du service
   principal de chaque app (onglet Authorization), remplacer
   `<SP_APP_CREATION>` / `<SP_APP_ADMINISTRATION>` dans
   `sql/init_lakebase.sql`, décommenter les GRANT, puis exécuter le script
   dans l'**éditeur SQL du projet Lakebase V3** (pas l'éditeur Spark).
   - **Environnement déjà déployé** (schéma bl_demat antérieur) : exécuter
     aussi `sql/migration_notifications_desadv.sql` (table notifications,
     colonnes/contrainte DESADV), `sql/migration_v4_edi_adresses.sql`
     (colonne statut_edi, tables adresses et sites_logistiques) et
     `sql/migration_v5_pla_rbac.sql` (tables pla et roles_utilisateurs) et
     `sql/migration_v6_audit_qualite_ecrans.sql` (audit_bl,
     qualite_extraction, ecrans_utilisateur, colonnes de rapprochement)
     avec les GRANT correspondants.
5. **(Optionnel) Extraction IA** : sur l'app Création, **Edit → Resources →
   + Add resource → Serving endpoint** (un modèle vision, ex.
   `databricks-claude-sonnet-4`), permission **Can query** ; puis décommenter
   `BL_LLM_ENDPOINT` dans `src/app_creation/app.yaml` avec le nom de
   l'endpoint. Sans cette étape, l'app Création reste en saisie manuelle.
6. **Tester** : `BL-2026-0001` auto-remplit le fournisseur FRN1 (DESADV achat
   d'exemple), `EXP-2026-0001` auto-remplit CLIENT ALPHA en expédition.
   Optionnel : `sql/seed_fake_bl.sql` insère 30 BL fictifs avec photos.
7. **Référentiels ERP** : le job `jobs/` synchronise fournisseurs, clients et
   DESADV achat depuis l'ERP (voir `jobs/README.md`). Les notifications
   EDI NOK → OK sont journalisées dans la table `notifications` (Gestion ▸
   Notifications) ; un flux Power Automate pourra les envoyer par email.

## Contrôle d'accès (RBAC) — procédure de mise en service

Rôles : **LOG** (création réceptions/expéditions), **APPROS** (archivage
réception ; réceptions en modification ; DESADV achat et notifications en
lecture), **ADV** (miroir vente), **FINANCE** (BL en lecture),
**ADMIN_METIER** (tout). La matrice détaillée par vue est dans
`shared/bl_core/rbac.py` — la faire évoluer = modifier ce fichier et
redéployer (elle est versionnée avec la solution).

1. **Créer les objets** : exécuter `sql/migration_v5_pla_rbac.sql` (ou
   `init_lakebase.sql` pour un environnement neuf) dans l'éditeur SQL du
   projet Lakebase, **avec les GRANT** des deux apps sur
   `roles_utilisateurs` (SELECT pour Création, CRUD pour Administration).
2. **Donner l'accès aux apps** : page de chaque app → **Permissions** →
   ajouter les utilisateurs ou groupes Databricks (« Can use »). C'est le
   1er niveau (qui peut OUVRIR l'app) ; le RBAC est le 2e niveau (ce qu'on
   voit dans l'app).
3. **Affecter les rôles** : ouvrir l'app Administration avec le compte du
   déployeur → Gestion ▸ **Rôles** → ajouter une ligne par utilisateur
   (email Databricks exact, en minuscules) et par rôle. Un utilisateur peut
   cumuler plusieurs rôles.
   ⚠️ Commencer par **s'attribuer ADMIN_METIER** : dès la première ligne
   insérée, le RBAC s'active pour tout le monde.
4. **Vérifier** : le pied de la barre latérale affiche l'email et les rôles
   de l'utilisateur connecté. Vues sans droit = masquées ; niveau lecture =
   « 🔒 lecture seule » (aucune action d'écriture). Dans l'app Création,
   seules les opérations du rôle sont proposées.
5. **Mode ouvert** : tant que la table est vide, aucune restriction (utile
   pour la recette). Les rôles sont mis en cache 2 minutes — un changement
   de rôle est visible au plus tard 2 minutes après (ou immédiatement via
   « Actualiser »).

## Connexion aux apps (authentification)

En bref : la connexion est **automatique via le SSO Databricks** (OAuth) —
pas de mot de passe applicatif. L'utilisateur doit simplement avoir un compte
dans l'espace Databricks et la permission « Can use » sur l'app. L'app
reçoit l'identité (email) dans les en-têtes de chaque requête
(`bl_core/identity.py`) et l'utilise pour la traçabilité et le RBAC.
Côté données, l'app se connecte à Lakebase avec le jeton OAuth de **son
service principal** (renouvelé automatiquement avant expiration, ~45 min) :
les utilisateurs n'ont jamais besoin d'un accès direct à la base.

## Notes d'exploitation

- Jeton OAuth renouvelé avant expiration (45 min) ; requêtes rejouées sur
  coupure (réveil scale-to-zero compris).
- Photos ≤ 2 Mo/page (compression automatique, HEIC accepté, correction de
  perspective débrayable).
- `shared/bl_core` est la source de vérité du code partagé : après
  modification, exécuter `tools/sync_shared.ps1` (Windows) ou
  `tools/sync_shared.sh` (macOS/Linux).
