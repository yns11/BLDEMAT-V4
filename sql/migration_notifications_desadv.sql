-- ============================================================================
-- V3 Lakebase — MIGRATION : notifications + colonnes/contrainte DESADV
-- À exécuter dans l'éditeur SQL du projet Lakebase V3 SI le schéma bl_demat a
-- déjà été créé par une version antérieure d'init_lakebase.sql (apps déjà
-- déployées). Les nouveaux environnements passent directement par
-- init_lakebase.sql. Idempotent autant que possible.
-- ============================================================================

-- 1) base_desadv : colonnes issuedatetime / integrationdate (flux EDI).
ALTER TABLE bl_demat.base_desadv ADD COLUMN IF NOT EXISTS issuedatetime   TIMESTAMPTZ;
ALTER TABLE bl_demat.base_desadv ADD COLUMN IF NOT EXISTS integrationdate DATE;

-- 2) Interdire les doublons de numéro de BL par sens : clé primaire
--    (numero_bl, sens) au lieu de (numero_bl, nom_fournisseur, sens).
--    On dédoublonne d'abord (on garde une ligne par numero_bl+sens).
DELETE FROM bl_demat.base_desadv d
USING (
  SELECT ctid,
         ROW_NUMBER() OVER (PARTITION BY numero_bl, sens
                            ORDER BY issuedatetime DESC NULLS LAST, ctid) AS rn
  FROM bl_demat.base_desadv
) t
WHERE d.ctid = t.ctid AND t.rn > 1;

ALTER TABLE bl_demat.base_desadv DROP CONSTRAINT IF EXISTS base_desadv_pkey;
ALTER TABLE bl_demat.base_desadv ADD PRIMARY KEY (numero_bl, sens);

-- 3) Table notifications (journal EDI NOK -> OK, affichée en lecture dans
--    Gestion -> Notifications ; consommable ensuite par un flux Power Automate).
CREATE TABLE IF NOT EXISTS bl_demat.notifications (
  id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  type_notif TEXT,
  numero_bl  TEXT,
  message    TEXT NOT NULL,
  cree_le    TIMESTAMPTZ NOT NULL DEFAULT now(),
  cree_par   TEXT,
  envoyee    BOOLEAN NOT NULL DEFAULT false
);
CREATE INDEX IF NOT EXISTS idx_notifications_cree_le ON bl_demat.notifications (cree_le DESC);

-- 4) Droits de l'app Administration sur la nouvelle table + sa séquence.
--    Remplacer <SP_APP_ADMINISTRATION> par le client ID du service principal.
-- GRANT SELECT, INSERT, UPDATE, DELETE ON bl_demat.notifications TO "<SP_APP_ADMINISTRATION>";
-- GRANT USAGE, SELECT ON SEQUENCE bl_demat.notifications_id_seq TO "<SP_APP_ADMINISTRATION>";
