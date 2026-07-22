-- ============================================================================
-- Migration V4 — environnements DÉJÀ déployés (schéma bl_demat existant).
-- À exécuter dans l'éditeur SQL du projet Lakebase (pas l'éditeur Spark).
-- Idempotent : ré-exécutable sans risque.
--
-- Contenu :
--   1. base_desadv.statut_edi — état du message EDI (messagestate) :
--      2 -> 'OK', 3 -> 'EDI NOK' (alimenté par le job de synchronisation).
--   2. Tables adresses et sites_logistiques (module Gestion).
--   3. GRANT sur les nouveaux objets (remplacer <SP_APP_CREATION> /
--      <SP_APP_ADMINISTRATION> par les client ID des service principals).
-- ============================================================================

-- 1. Colonne statut_edi sur les DESADV --------------------------------------
ALTER TABLE bl_demat.base_desadv ADD COLUMN IF NOT EXISTS statut_edi TEXT;

-- 2. Adresses et sites logistiques ------------------------------------------
CREATE TABLE IF NOT EXISTS bl_demat.adresses (
  adresse TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS bl_demat.sites_logistiques (
  entite  TEXT NOT NULL REFERENCES bl_demat.base_tiers (name),
  adresse TEXT NOT NULL REFERENCES bl_demat.adresses (adresse),
  PRIMARY KEY (entite, adresse)
);

-- 3. Droits (décommenter et remplacer les client ID) -------------------------
-- App Création : lecture des adresses/sites (contexte du rapprochement IA).
-- GRANT SELECT ON bl_demat.adresses, bl_demat.sites_logistiques TO "<SP_APP_CREATION>";

-- App Administration : CRUD sur les nouvelles vues.
-- GRANT SELECT, INSERT, UPDATE, DELETE ON bl_demat.adresses,
--   bl_demat.sites_logistiques TO "<SP_APP_ADMINISTRATION>";
