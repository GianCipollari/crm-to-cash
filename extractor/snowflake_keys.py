"""Creates the key pair dbt and the loader use to log in to Snowflake.

    python -m extractor.snowflake_keys

Writes the private key to out/keys/snowflake_dbt_key.p8 (out/ is never committed)
and prints the SQL that creates the service user with the public key. Snowflake
requires key-pair authentication for service users: there is no password to leak.
"""

from __future__ import annotations

from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ROOT = Path(__file__).resolve().parent.parent
KEY_PATH = ROOT / "out" / "keys" / "snowflake_dbt_key.p8"

USER_SQL = """use role accountadmin;
create user if not exists dbt_service
  type = service
  default_role = crm_to_cash_role
  default_warehouse = crm_to_cash_wh
  rsa_public_key = '{public_key}';
grant role crm_to_cash_role to user dbt_service;"""


def public_key_body(private_key) -> str:
    pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return "".join(line for line in pem.splitlines() if "-----" not in line)


def main() -> None:
    if KEY_PATH.exists():
        key = serialization.load_pem_private_key(KEY_PATH.read_bytes(), password=None)
        print(f"Using the existing key at {KEY_PATH}")
    else:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        KEY_PATH.write_bytes(key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        print(f"Private key written to {KEY_PATH} (keep it private; it is ignored by Git)")
    print("\nRun this in a Snowflake SQL worksheet:\n")
    print(USER_SQL.format(public_key=public_key_body(key)))


if __name__ == "__main__":
    main()
