# Job journalier — Référentiels ERP → Lakebase (solution BL V3)

Traduit les requêtes Power Query du rapport Power BI (EDI, COMMANDES ACHAT →
FOURNISSEURS, DESADV ACHAT, CLIENTS) en un job Databricks quotidien :

```
bronze_erp (ERP)  ──Spark SQL──▶  staging UC (bl_demat_staging)  ──psycopg──▶  Lakebase bl_demat
siledimessage                     fournisseurs_erp                              base_tiers  (FOURNISSEUR)
siledi_item_line                  clients_erp                                   base_tiers  (CLIENT)
purch_table                       desadv_achat_erp                              base_desadv (sens ACHAT)
sales_table
```

- **Upsert non destructif** (`ON CONFLICT DO NOTHING`) : les apps gardent leur
  CRUD complet ; les saisies manuelles ne sont jamais écrasées. Revers assumé :
  une ligne d'origine ERP supprimée à la main réapparaît au prochain run.
- **DESADV vente** : pas de flux ERP dans le rapport (EDI filtré
  `DespatchAdvice-Purchase`) → reste alimenté manuellement dans l'app Admin.
  Le jour où le flux vente existera, dupliquer le bloc EDI avec le bon
  `messagetype` et `sens='VENTE'`.
- **Staging UC** : trace auditable du dernier snapshot préparé, réutilisable
  pour du reporting.

## Dépendance psycopg (job serverless)

`psycopg[binary]` est déclarée dans le **bloc `environments` du job**
(`environment_key: bl_env`, `spec.client: "4"`) — c'est la plateforme qui
l'installe dans l'environnement serverless avant l'exécution. On n'utilise
**pas** `%pip install` + `%restart_python` dans le notebook : sur un job
serverless c'est fragile (l'installation dépend de l'import réel en mode
notebook et du redémarrage du kernel — d'où l'erreur
`ModuleNotFoundError: No module named 'psycopg'`).

En exécution **interactive** du notebook (hors job), installez la dépendance
une fois en tête : `%pip install "psycopg[binary]==3.2.3"` puis
`dbutils.library.restartPython()`.

## Déploiement

1. **Importer le notebook** `notebook_sync_referentiels_erp.py` dans le
   workspace (ou via votre dossier Git), par exemple sous
   `/Workspace/Users/<votre_email>/bl_v3/`.
2. **Compléter `job_sync_referentiels.json`** :
   - `notebook_path` : chemin réel du notebook importé ;
   - paramètre `pg_host` : l'hôte du projet Lakebase V3 (le `PGHOST` visible
     dans l'onglet Environment des apps, ex. `ep-super-mountain-….database.…`) —
     **seule valeur obligatoire côté connexion** ;
   - paramètre `lakebase_endpoint` : **laissé vide par défaut**, le job
     retrouve l'endpoint automatiquement à partir de `pg_host`
     (via `w.postgres.list_endpoints`). Ne le renseignez
     (`projects/…/branches/…/endpoints/…`) que si l'auto-découverte échoue
     (droits de listing des projets Lakebase insuffisants) ;
   - `catalogue_staging`/`schema_staging` si `emotors_data_platform.bl_demat_staging`
     ne convient pas (droit `CREATE SCHEMA` requis sur le catalogue choisi).
3. **Créer le job** (serverless, planifié 05h30 Europe/Paris, alerte email en échec) :
   ```powershell
   databricks jobs create --json @job_sync_referentiels.json --profile <PROFIL>
   ```
   Équivalent UI : Jobs & Pipelines → Create job → tâche Notebook (sans cluster
   = serverless), coller les paramètres, planification quotidienne, et dans
   l'onglet **Environment and Libraries** de la tâche, ajouter la dépendance
   `psycopg[binary]==3.2.3` (équivalent du bloc `environments` du JSON).
   Si le job existait déjà (créé avant ce correctif), mettez-le à jour :
   `databricks jobs reset --job-id <ID> --json @job_sync_referentiels.json`
   (en conservant l'`name`/`notebook_path` corrects), ou ajoutez la
   dépendance via l'onglet Environment de la tâche puis relancez.
4. **Premier run manuel** : `databricks jobs run-now <job_id>` (ou bouton
   « Run now »). La sortie du notebook affiche les volumes préparés et le
   nombre de lignes ajoutées dans Lakebase.

## Authentification Lakebase (runtime notebook)

Dans un runtime **notebook/job**, l'authentification n'est pas de type OAuth
client-credentials : `w.config.oauth_token()` n'y est **pas** disponible (erreur
`OAuth tokens are not available for runtime authentication` — au contraire du
runtime des Apps). Le mot de passe Postgres est donc obtenu via
`w.postgres.generate_database_credential(endpoint=…)`, avec l'endpoint résolu
automatiquement depuis `pg_host`. Le job se connecte sous **votre identité**
(`w.current_user.me()`), utilisateur Postgres = votre e-mail.

Cela requiert `databricks-sdk >= 0.81.0` (module `w.postgres`), déclaré dans le
bloc `environments` du job.

## Identité et droits

Le job s'exécute sous **votre identité** (créateur du projet Lakebase → tous
droits sur `bl_demat`, lecture `bronze_erp` déjà acquise via le rapport
Power BI). Si le job doit tourner sous un service principal un jour : créer son
rôle Postgres (attacher une ressource ou `databricks postgres create-role`),
lui fournir l'endpoint explicitement (`lakebase_endpoint`) si le SP ne peut pas
lister les projets, puis `GRANT USAGE ON SCHEMA bl_demat` + `INSERT/SELECT` sur
`base_tiers` et `base_desadv`, et `SELECT` sur `bronze_erp` + `CREATE` sur le
schéma de staging.

## Autres pistes (optionnelles, non retenues par défaut)

- **Lakebase synced tables** (UC → Postgres managé) : élégant mais les tables
  synchronisées sont **en lecture seule** côté Postgres — incompatible avec le
  CRUD demandé sur ces mêmes tables. Utilisable en sens inverse (Lakehouse
  sync : exposer `suivi_bl` en Delta pour l'analytique).
- **Trigger `table_update`** : déclencher le job sur mise à jour des tables
  bronze plutôt qu'à heure fixe (remplacer `schedule` par un `trigger`).
- **Colonne de provenance** (`source ERP/MANUEL`) si un jour il faut purger
  les lignes ERP disparues sans toucher au manuel.
