# Databricks notebook source
# MAGIC %md
# MAGIC # Envoi des notifications (email / Teams) — solution BL dématérialisés
# MAGIC
# MAGIC Consomme la table `notifications` de Lakebase (lignes `envoyee = false`,
# MAGIC écrites par l'app Administration lors des passages EDI NOK → OK) et les
# MAGIC pousse vers **deux canaux optionnels** :
# MAGIC
# MAGIC 1. **Teams** : un *incoming webhook* de canal (paramètre
# MAGIC    `teams_webhook_url`) — message posté directement dans le canal.
# MAGIC 2. **Power Automate** : l'URL d'un flux « Lorsqu'une requête HTTP est
# MAGIC    reçue » (paramètre `power_automate_url`) — le flux reçoit un JSON
# MAGIC    `{numero_bl, type_notif, message, cree_le, cree_par}` et peut alors
# MAGIC    envoyer un **email Outlook**, une carte Teams, créer une tâche, etc.
# MAGIC
# MAGIC Une notification est marquée `envoyee = true` UNIQUEMENT si tous les
# MAGIC canaux configurés ont répondu 2xx (relivraison au prochain run sinon).
# MAGIC Planifier ce job toutes les heures (voir job_envoi_notifications.json).

# COMMAND ----------

# Dépendance psycopg fournie par le bloc environments du job (pas de %pip).

# COMMAND ----------

dbutils.widgets.text("pg_host", "", "Hôte Postgres (PGHOST du projet Lakebase)")
dbutils.widgets.text("pg_database", "databricks_postgres", "Base Postgres")
dbutils.widgets.text("pg_schema", "bl_demat", "Schéma Postgres de la solution")
dbutils.widgets.text("lakebase_endpoint", "", "Endpoint Lakebase (auto si vide)")
dbutils.widgets.text("teams_webhook_url", "", "URL du webhook entrant Teams (optionnel)")
dbutils.widgets.text("power_automate_url", "", "URL du flux Power Automate HTTP (optionnel)")
dbutils.widgets.text("lot_max", "100", "Nombre max de notifications par run")

# COMMAND ----------

import json
import urllib.request

import psycopg
from databricks.sdk import WorkspaceClient

pg_host = dbutils.widgets.get("pg_host").strip()
pg_schema = dbutils.widgets.get("pg_schema").strip()
endpoint = dbutils.widgets.get("lakebase_endpoint").strip()
teams_url = dbutils.widgets.get("teams_webhook_url").strip()
flow_url = dbutils.widgets.get("power_automate_url").strip()
lot_max = int(dbutils.widgets.get("lot_max") or "100")

if not pg_host:
    raise ValueError("Paramètre pg_host obligatoire.")
if not teams_url and not flow_url:
    raise ValueError("Configurer au moins un canal : teams_webhook_url "
                     "et/ou power_automate_url.")

w = WorkspaceClient()
identite = w.current_user.me().user_name


def resoudre_endpoint() -> str:
    """Chemin de l'endpoint Lakebase (auth job : generate_database_credential)."""
    if endpoint:
        return endpoint
    for projet in w.postgres.list_projects():
        for branche in w.postgres.list_branches(parent=projet.name):
            for ep in w.postgres.list_endpoints(parent=branche.name):
                hosts = getattr(ep.status, "hosts", None) if ep.status else None
                if hosts and hosts.host == pg_host:
                    return ep.name
    raise ValueError(f"Aucun endpoint Lakebase trouvé pour l'hôte « {pg_host} ».")


mot_de_passe = w.postgres.generate_database_credential(endpoint=resoudre_endpoint()).token
conn = psycopg.connect(host=pg_host, port=5432,
                       dbname=dbutils.widgets.get("pg_database"),
                       user=identite, password=mot_de_passe, sslmode="require")

# COMMAND ----------


def poster_json(url: str, corps: dict) -> None:
    """POST JSON ; lève une exception si la réponse n'est pas 2xx."""
    requete = urllib.request.Request(
        url, data=json.dumps(corps).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(requete, timeout=30) as reponse:
        if not 200 <= reponse.status < 300:
            raise RuntimeError(f"HTTP {reponse.status} sur {url[:60]}…")


def message_teams(n: dict) -> dict:
    """MessageCard pour webhook entrant Teams."""
    return {
        "@type": "MessageCard", "@context": "http://schema.org/extensions",
        "themeColor": "43B02A",
        "summary": f"BL {n['numero_bl']} : EDI NOK -> OK",
        "sections": [{
            "activityTitle": f"✅ BL {n['numero_bl']} passé de EDI NOK à OK",
            "facts": [
                {"name": "Type", "value": n["type_notif"] or "—"},
                {"name": "Quand", "value": str(n["cree_le"])},
                {"name": "Par", "value": n["cree_par"] or "—"},
            ],
            "text": n["message"],
        }],
    }


envoyees, echecs = 0, 0
with conn:
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT id, type_notif, numero_bl, message, cree_le, cree_par "
            f"FROM {pg_schema}.notifications WHERE envoyee = false "
            "ORDER BY cree_le LIMIT %s", (lot_max,))
        lignes = [dict(zip(("id", "type_notif", "numero_bl", "message",
                            "cree_le", "cree_par"), l)) for l in cur.fetchall()]

        for n in lignes:
            try:
                if teams_url:
                    poster_json(teams_url, message_teams(n))
                if flow_url:
                    poster_json(flow_url, {
                        "numero_bl": n["numero_bl"], "type_notif": n["type_notif"],
                        "message": n["message"], "cree_le": str(n["cree_le"]),
                        "cree_par": n["cree_par"],
                    })
                cur.execute(
                    f"UPDATE {pg_schema}.notifications SET envoyee = true "
                    "WHERE id = %s", (n["id"],))
                envoyees += 1
            except Exception as e:            # relivrée au prochain run
                echecs += 1
                print(f"Échec notification id={n['id']} : {e}")

conn.close()
print(f"Notifications : {envoyees} envoyée(s), {echecs} échec(s), "
      f"{len(lignes)} lue(s).")
