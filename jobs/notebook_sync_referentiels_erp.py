# Databricks notebook source
# MAGIC %md
# MAGIC # Synchronisation journalière des référentiels ERP → Lakebase (solution BL V3)
# MAGIC
# MAGIC Traduction des requêtes Power Query du rapport Power BI :
# MAGIC `EDI` et `COMMANDES ACHAT` (intermédiaires) → `FOURNISSEURS`, `DESADV ACHAT`, `CLIENTS`.
# MAGIC
# MAGIC Trois étapes :
# MAGIC 1. **Préparation** (Spark SQL sur `emotors_data_platform.bronze_erp`) ;
# MAGIC 2. **Sauvegarde** dans un schéma de staging Unity Catalog (créé si inexistant) —
# MAGIC    trace auditable + réutilisable pour d'autres usages analytiques ;
# MAGIC 3. **Synchronisation** vers le Lakebase de la solution par UPSERT
# MAGIC    `ON CONFLICT DO NOTHING` : les lignes ERP nouvelles sont ajoutées, les
# MAGIC    saisies/CRUD manuels des apps sont **préservés**.
# MAGIC
# MAGIC ⚠️ Conséquence assumée du mode additif : une ligne d'origine ERP supprimée à la
# MAGIC main dans l'app sera réinsérée au prochain run (les lignes purement manuelles,
# MAGIC elles, ne sont jamais touchées). Le DESADV **vente** n'a pas de flux ERP dans le
# MAGIC rapport Power BI (EDI filtré sur `DespatchAdvice-Purchase`) : il reste alimenté
# MAGIC manuellement via l'app Administration.

# COMMAND ----------

# MAGIC %md
# MAGIC La dépendance `psycopg[binary]` est fournie par l'environnement serverless
# MAGIC du job (bloc `environments` de `job_sync_referentiels.json`) — pas de
# MAGIC `%pip install` ici (fragile sur job serverless : dépend de l'import en
# MAGIC mode notebook et du redémarrage du kernel). En exécution interactive hors
# MAGIC job, installez-la une fois avec `%pip install "psycopg[binary]==3.2.3"`.

# COMMAND ----------

# Paramètres du job (surchargés par les job parameters / widgets).
dbutils.widgets.text("catalogue_erp", "emotors_data_platform", "Catalogue ERP")
dbutils.widgets.text("schema_erp", "bronze_erp", "Schéma ERP")
dbutils.widgets.text("catalogue_staging", "emotors_data_platform", "Catalogue de staging")
dbutils.widgets.text("schema_staging", "bl_demat_staging", "Schéma de staging (créé si absent)")
dbutils.widgets.text("lakebase_endpoint", "", "Endpoint Lakebase (projects/.../branches/.../endpoints/...)")
dbutils.widgets.text("pg_host", "", "Hôte Postgres (PGHOST du projet Lakebase)")
dbutils.widgets.text("pg_database", "databricks_postgres", "Base Postgres")
dbutils.widgets.text("pg_schema", "bl_demat", "Schéma Postgres de la solution")

ERP = f"{dbutils.widgets.get('catalogue_erp')}.{dbutils.widgets.get('schema_erp')}"
STAGING = f"{dbutils.widgets.get('catalogue_staging')}.{dbutils.widgets.get('schema_staging')}"

# COMMAND ----------

# MAGIC %md ## Étape 1 — Préparation (traduction des requêtes Power Query)

# COMMAND ----------

# REQUETTE EDI : siledimessage filtré DespatchAdvice-Purchase, doublons supprimés
# sur documentreference1 (on garde le message le plus récent), renommage numero_bl.
# messagestate : état du message EDI, traduit en libellé métier
# (2 -> 'OK', 3 -> 'EDI NOK', autre/NULL -> NULL).
spark.sql(f"""
CREATE OR REPLACE TEMP VIEW edi AS
SELECT recid, issuedatetime, CAST(integrationdate AS DATE) AS integrationdate,
       numero_bl, statut_edi
FROM (
  SELECT recid, issuedatetime, integrationdate,
         documentreference1 AS numero_bl,
         CASE CAST(messagestate AS INT)
           WHEN 2 THEN 'OK'
           WHEN 3 THEN 'EDI NOK'
         END AS statut_edi,
         ROW_NUMBER() OVER (PARTITION BY documentreference1
                            ORDER BY issuedatetime DESC, recid DESC) AS rn
  FROM {ERP}.siledimessage
  WHERE messagetype = 'DespatchAdvice-Purchase'
    AND documentreference1 IS NOT NULL AND documentreference1 <> ''
)
WHERE rn = 1
""")

# REQUETTE COMMANDES ACHAT : purch_table, commandes CO*, libellé fournisseur
# "compte : nom" (identique à Text.Combine du rapport).
spark.sql(f"""
CREATE OR REPLACE TEMP VIEW commandes_achat AS
SELECT purchid, orderaccount, purchname,
       concat(orderaccount, ' : ', purchname) AS supplier
FROM {ERP}.purch_table
WHERE purchid LIKE 'CO%'
  AND orderaccount IS NOT NULL AND purchname IS NOT NULL
""")

# REQUETTE FOURNISSEURS : colonne supplier des commandes d'achat (dédupliquée —
# la table cible base_tiers a une clé primaire sur le nom).
df_fournisseurs = spark.sql("SELECT DISTINCT supplier AS name FROM commandes_achat")

# REQUETTE DESADV ACHAT : lignes EDI jointes au message (documentref = recid)
# puis à la commande d'achat (purchordernum = purchid) pour obtenir le fournisseur.
# On porte aussi issuedatetime (créé le) et integrationdate (date d'intégration).
# numero_bl est UNIQUE côté cible (base_desadv) : on ne garde qu'une ligne par
# BL (message le plus récent, déjà dédoublonné dans la vue edi).
df_desadv_achat = spark.sql("""
SELECT numero_bl, nom_fournisseur, issuedatetime, integrationdate, statut_edi FROM (
  SELECT e.numero_bl, c.supplier AS nom_fournisseur,
         e.issuedatetime, e.integrationdate, e.statut_edi,
         ROW_NUMBER() OVER (PARTITION BY e.numero_bl
                            ORDER BY e.issuedatetime DESC) AS rn
  FROM {erp}.siledi_item_line AS l
  JOIN edi AS e ON l.documentref = e.recid
  JOIN commandes_achat AS c ON l.purchordernum = c.purchid
)
WHERE rn = 1
""".replace("{erp}", ERP))

# REQUETTE CLIENTS : sales_table dédupliquée par compte client, libellé
# "compte : nom" (on garde la commande la plus récente par compte).
df_clients = spark.sql(f"""
SELECT concat(custaccount, ' : ', salesname) AS name
FROM (
  SELECT custaccount, salesname,
         ROW_NUMBER() OVER (PARTITION BY custaccount ORDER BY salesid DESC) AS rn
  FROM {ERP}.sales_table
  WHERE custaccount IS NOT NULL AND salesname IS NOT NULL
)
WHERE rn = 1
""")

print(f"Préparé : {df_fournisseurs.count()} fournisseurs, "
      f"{df_clients.count()} clients, {df_desadv_achat.count()} DESADV achat")

# COMMAND ----------

# MAGIC %md ## Étape 2 — Sauvegarde dans le schéma de staging Unity Catalog

# COMMAND ----------

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {STAGING} "
          "COMMENT 'Référentiels préparés pour la solution BL dématérialisés (V3)'")

df_fournisseurs.write.mode("overwrite").saveAsTable(f"{STAGING}.fournisseurs_erp")
df_clients.write.mode("overwrite").saveAsTable(f"{STAGING}.clients_erp")
df_desadv_achat.write.mode("overwrite").saveAsTable(f"{STAGING}.desadv_achat_erp")
print(f"Staging écrit dans {STAGING} (fournisseurs_erp, clients_erp, desadv_achat_erp)")

# COMMAND ----------

# MAGIC %md ## Étape 3 — Synchronisation vers Lakebase (UPSERT non destructif)

# COMMAND ----------

import psycopg
from databricks.sdk import WorkspaceClient

pg_host = dbutils.widgets.get("pg_host").strip()
endpoint = dbutils.widgets.get("lakebase_endpoint").strip()
pg_schema = dbutils.widgets.get("pg_schema").strip()
if not pg_host:
    raise ValueError("Paramètre pg_host obligatoire (hôte du projet Lakebase V3).")

w = WorkspaceClient()
identite = w.current_user.me().user_name  # le job tourne sous votre identité


def resoudre_endpoint() -> str:
    """Chemin de ressource de l'endpoint Lakebase.

    Dans un runtime notebook/job, l'authentification n'est pas de type OAuth
    client-credentials : w.config.oauth_token() n'y est PAS disponible. On passe
    donc obligatoirement par w.postgres.generate_database_credential(endpoint=…),
    qui exige le chemin de l'endpoint. Si le paramètre lakebase_endpoint n'est
    pas fourni, on le retrouve automatiquement à partir de pg_host."""
    if endpoint:
        return endpoint
    for projet in w.postgres.list_projects():
        for branche in w.postgres.list_branches(parent=projet.name):
            for ep in w.postgres.list_endpoints(parent=branche.name):
                hosts = getattr(ep.status, "hosts", None) if ep.status else None
                if hosts and hosts.host == pg_host:
                    return ep.name
    raise ValueError(
        f"Aucun endpoint Lakebase trouvé pour l'hôte « {pg_host} ». "
        "Renseignez le paramètre lakebase_endpoint "
        "(projects/<id>/branches/<b>/endpoints/<ep>, via `databricks postgres list-endpoints`)."
    )


endpoint_resolu = resoudre_endpoint()
mot_de_passe = w.postgres.generate_database_credential(endpoint=endpoint_resolu).token

conn = psycopg.connect(
    host=pg_host, port=5432, dbname=dbutils.widgets.get("pg_database"),
    user=identite, password=mot_de_passe, sslmode="require",
)

fournisseurs = [r["name"] for r in df_fournisseurs.collect()]
clients = [r["name"] for r in df_clients.collect()]
desadv = [(r["numero_bl"], r["nom_fournisseur"], r["issuedatetime"],
           r["integrationdate"], r["statut_edi"])
          for r in df_desadv_achat.collect()]

with conn:
    with conn.cursor() as cur:
        # base_tiers : ajout des nouveaux tiers ERP, sans toucher aux existants
        # (ni aux tiers créés manuellement dans l'app Administration).
        cur.executemany(
            f"INSERT INTO {pg_schema}.base_tiers (name, type_tiers) "
            "VALUES (%s, 'FOURNISSEUR') ON CONFLICT (name) DO NOTHING",
            [(n,) for n in fournisseurs],
        )
        nb_frs = cur.rowcount
        cur.executemany(
            f"INSERT INTO {pg_schema}.base_tiers (name, type_tiers) "
            "VALUES (%s, 'CLIENT') ON CONFLICT (name) DO NOTHING",
            [(n,) for n in clients],
        )
        nb_cli = cur.rowcount
        # base_desadv (sens ACHAT) : additif sur les lignes (préserve les
        # corrections manuelles ; pas de doublon de numéro de BL), MAIS
        # statut_edi est rafraîchi à chaque run : l'état d'un message EDI
        # évolue dans le temps (2 = OK, 3 = EDI NOK) et l'ERP fait foi.
        cur.executemany(
            f"INSERT INTO {pg_schema}.base_desadv "
            "(numero_bl, nom_fournisseur, sens, issuedatetime, integrationdate, statut_edi) "
            "VALUES (%s, %s, 'ACHAT', %s, %s, %s) "
            "ON CONFLICT (numero_bl, sens) "
            "DO UPDATE SET statut_edi = EXCLUDED.statut_edi",
            desadv,
        )
        nb_desadv = cur.rowcount

        # Rapprochement BL <-> DESADV : marque les BL (réception <-> ACHAT,
        # expédition <-> VENTE) dont le numéro correspond à un avis intégré.
        # La vue « Écarts » de l'app Administration montre le reste.
        cur.execute(f"""
            UPDATE {pg_schema}.suivi_bl b
            SET desadv_rapproche = TRUE, desadv_rapproche_le = now()
            WHERE b.desadv_rapproche IS DISTINCT FROM TRUE
              AND EXISTS (
                SELECT 1 FROM {pg_schema}.base_desadv d
                WHERE upper(d.numero_bl) = upper(b.numero_bl)
                  AND d.sens = CASE
                        WHEN b.type_operation IN ('RECEPTION', 'ARCHIVAGE_RECEPTION')
                          THEN 'ACHAT' ELSE 'VENTE' END)
        """)
        nb_rappro = cur.rowcount
conn.close()

print(f"Lakebase synchronisé : +{nb_frs} fournisseur(s), +{nb_cli} client(s), "
      f"+{nb_desadv} DESADV achat, {nb_rappro} BL nouvellement rapproché(s).")
