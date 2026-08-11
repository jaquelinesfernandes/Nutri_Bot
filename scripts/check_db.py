#!/usr/bin/env python
"""
Verifica o estado das migrations Alembic no banco de produção.

Uso:
    python scripts/check_db.py          # mostra versão atual vs. head
    python scripts/check_db.py --apply  # aplica as migrations pendentes
"""
from __future__ import annotations

import subprocess
import sys

from dotenv import load_dotenv

load_dotenv()


def run(cmd: list[str]) -> int:
    result = subprocess.run(cmd, capture_output=False)
    return result.returncode


def main() -> None:
    apply = "--apply" in sys.argv

    print("=== Versão atual no banco ===")
    run(["alembic", "current"])

    print("\n=== Histórico de migrations ===")
    run(["alembic", "history", "--verbose"])

    if apply:
        print("\n=== Aplicando migrations pendentes ===")
        rc = run(["alembic", "upgrade", "head"])
        if rc == 0:
            print("\n✅ Migrations aplicadas com sucesso!")
        else:
            print("\n❌ Falha ao aplicar migrations")
            sys.exit(rc)
    else:
        print("\nPara aplicar as migrations pendentes:")
        print("  python scripts/check_db.py --apply")
        print("  # ou diretamente:")
        print("  alembic upgrade head")


if __name__ == "__main__":
    main()
