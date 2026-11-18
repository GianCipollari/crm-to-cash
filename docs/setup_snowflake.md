# Snowflake setup (free 30-day trial)

The same dbt project runs on DuckDB (default) and on Snowflake (`--target snowflake`).

## 1. Objects (once, as ACCOUNTADMIN, in a SQL worksheet)

```sql
use role accountadmin;

create warehouse if not exists crm_to_cash_wh
  warehouse_size = 'XSMALL' auto_suspend = 60 auto_resume = true initially_suspended = true;

create resource monitor if not exists crm_to_cash_monitor
  with credit_quota = 20
  triggers on 90 percent do notify
           on 100 percent do suspend;
alter warehouse crm_to_cash_wh set resource_monitor = crm_to_cash_monitor;

create database if not exists crm_to_cash;
create role if not exists crm_to_cash_role;
grant usage on warehouse crm_to_cash_wh to role crm_to_cash_role;
grant ownership on database crm_to_cash to role crm_to_cash_role copy current grants;

set me = current_user();
grant role crm_to_cash_role to user identifier($me);
```

## 2. Service user with key-pair authentication

```bash
python -m extractor.snowflake_keys
```

Writes the private key to `out/keys/snowflake_dbt_key.p8` (never committed) and prints the
`create user dbt_service ...` statement with the public key. Run that statement in Snowflake.

## 3. Load raw data and build

```bash
python -m extractor.load_snowflake      # copies raw_* tables from DuckDB to CRM_TO_CASH.RAW
cd dbt
dbt debug --target snowflake
dbt build --target snowflake
```

Connection settings default to this project's account and objects; override them with
`SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PRIVATE_KEY_PATH`, `SNOWFLAKE_ROLE`,
`SNOWFLAKE_WAREHOUSE` and `SNOWFLAKE_DATABASE`.

## 4. Check both warehouses agree

```bash
python -m extractor.compare_warehouses
```

Runs the same summary queries on DuckDB and Snowflake (deals per reconciliation status,
issues per type, customers per match method, funnel totals) and reports any difference.
Build both targets on the same day first: statuses such as "overdue" depend on the date.
