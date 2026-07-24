-- ============================================================================
-- Migration V5 — PLA (protocole logistique d'achat) et RBAC.
-- À exécuter dans l'éditeur SQL du projet Lakebase (pas l'éditeur Spark).
-- Idempotent : ré-exécutable sans risque. Pour un NOUVEL environnement,
-- init_lakebase.sql contient déjà ces objets.
-- ============================================================================

-- 1. PLA : protocole logistique d'achat -------------------------------------
-- Un protocole par tiers (la clé étrangère tiers est aussi la clé primaire).
-- Le quai du PLA pré-remplit automatiquement le champ Quai de l'app Création
-- (défaut « B15 » si le tiers n'a pas de PLA).
CREATE TABLE IF NOT EXISTS bl_demat.pla (
  nom_fournisseur     TEXT PRIMARY KEY REFERENCES bl_demat.base_tiers (name),
  code_quai           TEXT NOT NULL REFERENCES bl_demat.quais (code_quai),
  jours_livraison     TEXT,     -- ex. « lundi, mercredi, vendredi »
  frequence_livraison TEXT      -- ex. « quotidienne », « hebdomadaire », « 2x/sem »
);

-- 2. RBAC : rôles applicatifs des utilisateurs ------------------------------
-- Un utilisateur (email Databricks) peut cumuler plusieurs rôles.
-- La matrice des droits par vue est portée par le code (bl_core/rbac.py).
-- Tant que cette table est VIDE, les apps fonctionnent en accès complet
-- (mode ouvert) : le RBAC s'active dès la première ligne insérée.
CREATE TABLE IF NOT EXISTS bl_demat.roles_utilisateurs (
  utilisateur TEXT NOT NULL,   -- email Databricks (insensible à la casse)
  role        TEXT NOT NULL CHECK (role IN
              ('LOG', 'APPROS', 'ADV', 'FINANCE', 'ADMIN_METIER')),
  PRIMARY KEY (utilisateur, role)
);

-- Exemples (décommenter et adapter) :
-- INSERT INTO bl_demat.roles_utilisateurs (utilisateur, role) VALUES
--   ('prenom.nom@emotors.fr',  'LOG'),
--   ('appro1@emotors.fr',      'APPROS'),
--   ('adv1@emotors.fr',        'ADV'),
--   ('finance@emotors.fr',     'FINANCE'),
--   ('admin.blm@emotors.fr',   'ADMIN_METIER')
-- ON CONFLICT DO NOTHING;

-- 3. Droits (décommenter et remplacer les client ID) -------------------------
-- App Création : lecture du PLA (quai automatique) et des rôles.
-- GRANT SELECT ON bl_demat.pla, bl_demat.roles_utilisateurs TO "<SP_APP_CREATION>";

-- App Administration : CRUD sur le PLA et les rôles (vues Gestion).
-- GRANT SELECT, INSERT, UPDATE, DELETE ON bl_demat.pla,
--   bl_demat.roles_utilisateurs TO "<SP_APP_ADMINISTRATION>";
