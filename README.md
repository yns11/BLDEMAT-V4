# BL dématérialisés — V3 (Lakebase)

Troisième version de la solution, 100 % Lakebase (Postgres managé Databricks) :
métadonnées ET photos en base, aucune dépendance à Unity Catalog, aucun GRANT
admin requis (le créateur du projet Lakebase a tous les droits).

**À déployer sur un NOUVEAU projet Lakebase et deux NOUVELLES apps** (par
exemple `bl-creation-v3` et `bl-administration-v3`) pour ne pas écraser la V2.

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
     colonnes/contrainte DESADV) avec les GRANT correspondants.
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

## Notes d'exploitation

- Jeton OAuth renouvelé avant expiration (45 min) ; requêtes rejouées sur
  coupure (réveil scale-to-zero compris).
- Photos ≤ 2 Mo/page (compression automatique, HEIC accepté, correction de
  perspective débrayable).
- `shared/bl_core` est la source de vérité du code partagé : après
  modification, exécuter `tools/sync_shared.ps1`.
