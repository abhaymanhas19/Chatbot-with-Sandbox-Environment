"""Create a local .env with a random executor token; never overwrite an existing one."""
from pathlib import Path
import secrets

project = Path(__file__).resolve().parents[1]
target = project / ".env"
if target.exists():
    print(f"Keeping existing {target}")
else:
    template = (project / ".env.example").read_text()
    content = template.replace("replace-with-a-long-random-secret", secrets.token_urlsafe(32))
    target.write_text(content)
    target.chmod(0o600)
    print(f"Created {target} with a random executor token")
