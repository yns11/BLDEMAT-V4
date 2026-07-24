-- ============================================================================
-- Migration V6 — audit des BL, qualité d'extraction IA, écrans utilisateur,
-- rapprochement BL ⇄ DESADV. À exécuter dans l'éditeur SQL du projet Lakebase.
-- Idempotent. Pour un NOUVEL environnement, init_lakebase.sql suffit.
-- ============================================================================

-- 1. Rapprochement BL ⇄ DESADV (marqué par le job de synchronisation) --------
ALTER TABLE bl_demat.suivi_bl ADD COLUMN IF NOT EXISTS desadv_rapproche BOOLEAN;
ALTER TABLE bl_demat.suivi_bl ADD COLUMN IF NOT EXISTS desadv_rapproche_le TIMESTAMPTZ;

-- 2. Audit des BL : qui a changé quoi, quand ---------------------------------
CREATE TABLE IF NOT EXISTS bl_demat.audit_bl (
  id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  id_bl         TEXT NOT NULL,
  evenement     TEXT NOT NULL,     -- CREATION / MODIFICATION / SUPPRESSION / RESTAURATION
  champ         TEXT,              -- champ modifié (MODIFICATION uniquement)
  valeur_avant  TEXT,
  valeur_apres  TEXT,
  modifie_par   TEXT,
  modifie_le    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_bl_id ON bl_demat.audit_bl (id_bl, modifie_le DESC);

-- 3. Qualité de l'extraction IA : valeur IA vs valeur validée ----------------
CREATE TABLE IF NOT EXISTS bl_demat.qualite_extraction (
  id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  cree_le        TIMESTAMPTZ NOT NULL DEFAULT now(),
  utilisateur    TEXT,
  numero_bl      TEXT,
  champ          TEXT NOT NULL,    -- numero_bl / tiers / statut / date / commentaire
  valeur_ia      TEXT,
  valeur_validee TEXT,
  identique      BOOLEAN NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_qualite_champ ON bl_demat.qualite_extraction (champ);

-- 4. Écrans utilisateur : filtres/tri/colonnes sauvegardés par vue -----------
CREATE TABLE IF NOT EXISTS bl_demat.ecrans_utilisateur (
  utilisateur TEXT NOT NULL,
  vue         TEXT NOT NULL,
  nom         TEXT NOT NULL,
  est_defaut  BOOLEAN NOT NULL DEFAULT false,
  etat        TEXT NOT NULL,       -- JSON des clés de filtres/tri/colonnes
  PRIMARY KEY (utilisateur, vue, nom)
);

-- 5. Droits (décommenter et remplacer les client ID) -------------------------
-- App Création : journalise l'audit (création) et la qualité IA.
-- GRANT SELECT, INSERT ON bl_demat.audit_bl, bl_demat.qualite_extraction TO "<SP_APP_CREATION>";
-- GRANT USAGE, SELECT ON SEQUENCE bl_demat.audit_bl_id_seq,
--   bl_demat.qualite_extraction_id_seq TO "<SP_APP_CREATION>";

-- App Administration : audit complet, qualité en lecture, écrans en CRUD.
-- GRANT SELECT, INSERT ON bl_demat.audit_bl TO "<SP_APP_ADMINISTRATION>";
-- GRANT SELECT ON bl_demat.qualite_extraction TO "<SP_APP_ADMINISTRATION>";
-- GRANT SELECT, INSERT, UPDATE, DELETE ON bl_demat.ecrans_utilisateur TO "<SP_APP_ADMINISTRATION>";
-- GRANT USAGE, SELECT ON SEQUENCE bl_demat.audit_bl_id_seq TO "<SP_APP_ADMINISTRATION>";
