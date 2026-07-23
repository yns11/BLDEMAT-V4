-- ============================================================================
-- V3 Lakebase — initialisation du modèle de données "BL dématérialisés"
-- Dialecte : PostgreSQL. À exécuter dans l'éditeur SQL du NOUVEAU projet
-- Lakebase V3 (moteur Postgres — pas l'éditeur Spark), en tant que créateur
-- du projet. Idempotent : ré-exécutable sans risque.
--
-- ORDRE : déployer d'abord les deux apps V3 avec leur ressource « postgres »
-- (cela crée leurs rôles Postgres), PUIS exécuter ce script en remplaçant
-- <SP_APP_CREATION> et <SP_APP_ADMINISTRATION> par les client ID des service
-- principals (page de l'app -> onglet Authorization) dans les GRANT.
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS bl_demat;

-- ----------------------------------------------------------------------------
-- Table 1 : suivi_bl — bordereaux de livraison.
-- V3 : numéro de BL UNIQUE (plus de suffixe -1/-2 : l'app refuse le doublon).
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bl_demat.suivi_bl (
  id_bl           TEXT PRIMARY KEY,          -- UUID généré par l'app
  numero_bl       TEXT NOT NULL,
  date_reception  DATE,                      -- date de réception/expédition/archivage
  plage_horaire   TEXT,                      -- réceptions et expéditions uniquement
  nom_fournisseur TEXT,                      -- fournisseur (achat) OU client (vente)
  quai_reception  TEXT,                      -- réceptions et expéditions uniquement
  statut_bl       TEXT,                      -- '1' = OK, '0' = EDI NOK (réception seulement)
  comment_bl      TEXT,
  saisie_par      TEXT,
  saisie_le       TIMESTAMPTZ,
  modifie_par     TEXT,
  modifie_le      TIMESTAMPTZ,
  type_operation  TEXT,                      -- RECEPTION, EXPEDITION,
                                             -- ARCHIVAGE_RECEPTION, ARCHIVAGE_EXPEDITION
  est_supprime    BOOLEAN DEFAULT false,
  supprime_par    TEXT,
  supprime_le     TIMESTAMPTZ
);
-- Unicité insensible à la casse : "bl-1" et "BL-1" sont le même numéro.
CREATE UNIQUE INDEX IF NOT EXISTS uniq_suivi_bl_numero ON bl_demat.suivi_bl (upper(numero_bl));
CREATE INDEX IF NOT EXISTS idx_suivi_bl_saisie ON bl_demat.suivi_bl (saisie_le DESC);
CREATE INDEX IF NOT EXISTS idx_suivi_bl_date   ON bl_demat.suivi_bl (date_reception);
CREATE INDEX IF NOT EXISTS idx_suivi_bl_type   ON bl_demat.suivi_bl (type_operation);

-- ----------------------------------------------------------------------------
-- Table 2 : pieces_jointes_bl — pages scannées, stockées en base (BYTEA).
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bl_demat.pieces_jointes_bl (
  id_photo   TEXT PRIMARY KEY,
  id_bl      TEXT NOT NULL REFERENCES bl_demat.suivi_bl (id_bl),
  contenu    BYTEA NOT NULL,
  index_page INT
);
CREATE INDEX IF NOT EXISTS idx_pieces_id_bl ON bl_demat.pieces_jointes_bl (id_bl);

-- ----------------------------------------------------------------------------
-- Table 3 : base_tiers — fournisseurs (achat) et clients (vente).
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bl_demat.base_tiers (
  name       TEXT PRIMARY KEY,
  type_tiers TEXT NOT NULL CHECK (type_tiers IN ('FOURNISSEUR', 'CLIENT'))
);

-- ----------------------------------------------------------------------------
-- Table 4 : base_desadv — avis d'expédition, séparés achat (entrant) / vente
-- (sortant). L'app Création interroge le bon sens selon le type d'opération.
-- Clé primaire (numero_bl, sens) : un numéro de BL ne peut apparaître qu'UNE
-- fois par sens (doublons interdits). issuedatetime / integrationdate viennent
-- du flux EDI (job de synchronisation).
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bl_demat.base_desadv (
  numero_bl       TEXT NOT NULL,
  nom_fournisseur TEXT NOT NULL,             -- fournisseur (ACHAT) ou client (VENTE)
  sens            TEXT NOT NULL CHECK (sens IN ('ACHAT', 'VENTE')),
  issuedatetime   TIMESTAMPTZ,               -- date de création EDI (issuedatetime)
  integrationdate DATE,                      -- date d'intégration
  statut_edi      TEXT,                      -- messagestate EDI : 'OK' (2) / 'EDI NOK' (3)
  PRIMARY KEY (numero_bl, sens)
);

-- ----------------------------------------------------------------------------
-- Table 5 : gestionnaires — approvisionneurs.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bl_demat.gestionnaires (
  code_gestionnaire TEXT PRIMARY KEY
);

-- ----------------------------------------------------------------------------
-- Table 6 : portefeuilles — fournisseurs suivis par chaque gestionnaire
-- (un gestionnaire peut avoir plusieurs fournisseurs).
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bl_demat.portefeuilles (
  code_gestionnaire TEXT NOT NULL REFERENCES bl_demat.gestionnaires (code_gestionnaire),
  nom_fournisseur   TEXT NOT NULL REFERENCES bl_demat.base_tiers (name),
  PRIMARY KEY (code_gestionnaire, nom_fournisseur)
);

-- ----------------------------------------------------------------------------
-- Table 7 : quais — quais de réception/expédition (gérés dans l'app Admin).
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bl_demat.quais (
  code_quai TEXT PRIMARY KEY
);

-- ----------------------------------------------------------------------------
-- Table 8 : adresses — référentiel des adresses de sites (gérées dans l'app
-- Admin ; pourront alimenter le rapprochement IA de l'app Création).
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bl_demat.adresses (
  adresse TEXT PRIMARY KEY
);

-- ----------------------------------------------------------------------------
-- Table 9 : sites_logistiques — adresses des sites de chaque tiers (même
-- fonctionnement que la paire gestionnaires/portefeuilles : un tiers peut
-- avoir plusieurs sites, une adresse peut servir à plusieurs tiers).
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bl_demat.sites_logistiques (
  entite  TEXT NOT NULL REFERENCES bl_demat.base_tiers (name),
  adresse TEXT NOT NULL REFERENCES bl_demat.adresses (adresse),
  PRIMARY KEY (entite, adresse)
);

-- ----------------------------------------------------------------------------
-- Table 10 : pla — protocole logistique d'achat. Un protocole par tiers
-- (clé étrangère = clé primaire). Le quai du PLA pré-remplit le champ Quai
-- de l'app Création (défaut « B15 » sans PLA).
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bl_demat.pla (
  nom_fournisseur     TEXT PRIMARY KEY REFERENCES bl_demat.base_tiers (name),
  code_quai           TEXT NOT NULL REFERENCES bl_demat.quais (code_quai),
  jours_livraison     TEXT,     -- ex. « lundi, mercredi, vendredi »
  frequence_livraison TEXT      -- ex. « quotidienne », « hebdomadaire »
);

-- ----------------------------------------------------------------------------
-- Table 11 : roles_utilisateurs — RBAC applicatif. Un utilisateur (email
-- Databricks) peut cumuler plusieurs rôles ; la matrice des droits par vue
-- est portée par bl_core/rbac.py. Table VIDE = accès complet (mode ouvert).
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bl_demat.roles_utilisateurs (
  utilisateur TEXT NOT NULL,
  role        TEXT NOT NULL CHECK (role IN
              ('LOG', 'APPROS', 'ADV', 'FINANCE', 'ADMIN_METIER')),
  PRIMARY KEY (utilisateur, role)
);

-- ----------------------------------------------------------------------------
-- Table 12 : notifications — journal des événements notifiables (ex. passage
-- d'un BL de EDI NOK à OK). Écrites par l'app Administration, affichées en
-- lecture (Gestion -> Notifications). Un flux Power Automate pourra les
-- consommer pour un envoi email ultérieur.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bl_demat.notifications (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  type_notif TEXT,                           -- ex. 'EDI_NOK_OK'
  numero_bl  TEXT,
  message    TEXT NOT NULL,
  cree_le    TIMESTAMPTZ NOT NULL DEFAULT now(),
  cree_par   TEXT,
  envoyee    BOOLEAN NOT NULL DEFAULT false   -- réservé à un futur flux d'envoi
);
CREATE INDEX IF NOT EXISTS idx_notifications_cree_le ON bl_demat.notifications (cree_le DESC);

-- ----------------------------------------------------------------------------
-- Données initiales / d'exemple — idempotent.
-- ----------------------------------------------------------------------------
INSERT INTO bl_demat.quais (code_quai)
VALUES ('B15'), ('B06EST'), ('B06NORD'), ('B02NORD'), ('AUTRE')
ON CONFLICT DO NOTHING;

INSERT INTO bl_demat.gestionnaires (code_gestionnaire)
VALUES ('appro 1'), ('appro 2'), ('appro 3'), ('appro 4'),
       ('appro 5'), ('appro 6'), ('appro 7'), ('appro 8')
ON CONFLICT DO NOTHING;

INSERT INTO bl_demat.base_tiers (name, type_tiers)
VALUES ('FRN1', 'FOURNISSEUR'), ('FRN2', 'FOURNISSEUR'),
       ('TRANSPORTS DUPONT', 'FOURNISSEUR'), ('LOGISTIQUE MARTIN', 'FOURNISSEUR'),
       ('CLIENT ALPHA', 'CLIENT'), ('CLIENT BETA', 'CLIENT')
ON CONFLICT DO NOTHING;

INSERT INTO bl_demat.base_desadv (numero_bl, nom_fournisseur, sens, issuedatetime, integrationdate, statut_edi)
VALUES ('BL-2026-0001', 'FRN1', 'ACHAT', now() - interval '2 days', (now() - interval '2 days')::date, 'OK'),
       ('BL-2026-0002', 'TRANSPORTS DUPONT', 'ACHAT', now() - interval '1 day', (now() - interval '1 day')::date, 'EDI NOK'),
       ('EXP-2026-0001', 'CLIENT ALPHA', 'VENTE', now(), now()::date, NULL)
ON CONFLICT (numero_bl, sens) DO NOTHING;

INSERT INTO bl_demat.portefeuilles (code_gestionnaire, nom_fournisseur)
VALUES ('appro 1', 'FRN1'), ('appro 1', 'FRN2'), ('appro 2', 'TRANSPORTS DUPONT')
ON CONFLICT DO NOTHING;

-- ============================================================================
-- DROITS DES APPLICATIONS — après déploiement des deux apps V3.
-- ============================================================================
-- App Création : lit les référentiels, insère BL et photos.
-- GRANT USAGE ON SCHEMA bl_demat TO "<SP_APP_CREATION>";
-- GRANT SELECT, INSERT ON bl_demat.suivi_bl, bl_demat.pieces_jointes_bl TO "<SP_APP_CREATION>";
-- GRANT SELECT ON bl_demat.base_tiers, bl_demat.base_desadv, bl_demat.quais,
--   bl_demat.adresses, bl_demat.sites_logistiques, bl_demat.pla,
--   bl_demat.roles_utilisateurs TO "<SP_APP_CREATION>";

-- App Administration : CRUD complet sur toutes les vues + notifications.
-- GRANT USAGE ON SCHEMA bl_demat TO "<SP_APP_ADMINISTRATION>";
-- GRANT SELECT, INSERT, UPDATE, DELETE ON bl_demat.suivi_bl, bl_demat.pieces_jointes_bl,
--   bl_demat.base_tiers, bl_demat.base_desadv, bl_demat.gestionnaires,
--   bl_demat.portefeuilles, bl_demat.quais, bl_demat.adresses,
--   bl_demat.sites_logistiques, bl_demat.pla, bl_demat.roles_utilisateurs,
--   bl_demat.notifications TO "<SP_APP_ADMINISTRATION>";
-- GRANT USAGE, SELECT ON SEQUENCE bl_demat.notifications_id_seq TO "<SP_APP_ADMINISTRATION>";
