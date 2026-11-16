from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[1]


def test_fresh_schema_bootstrap_is_stamped_at_the_current_alembic_head():
    config = Config(str(ROOT / "alembic.ini"))
    head = ScriptDirectory.from_config(config).get_current_head()
    bootstrap_version = (ROOT / "database" / "schema" / "zz_alembic_version.sql").read_text(encoding="utf-8")

    assert head is not None
    assert f"SELECT '{head}'" in bootstrap_version
