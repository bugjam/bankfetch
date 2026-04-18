from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture()
def private_key() -> str:
    return """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDPAe6PiJu2Q0j/
mC5AcT8nTq1aTSwQWecViiS7kN+U3TSf4m4IzEunhTCS7bNb2k59X3Y3A3vQaJ5B
7PjYzsD8U8Dbxob8K5o4+oMq9gn1HEn4o16KHzvNShfGiT6tM6F5b/Q6fJipSPb4
SBTsdvpKkZErGjFLBdrp3XqEpxgW6yK83Gtlr7tcflMvHs8vMHFt2a0n5MUpAfy9
u1SZuWu7bPwV3U/oou+XvWwwCwYQn2gANXykR/B2H7Mawth+P+UD2jv07I4QB9w/
rK8G7S+5c9fQuY17s/QmEg3WVJq5Yz46t0lMcmHZf5G6lWMM9H3xA7/O7YjpwQwI
x1Qh63crAgMBAAECggEAJcA6M7o73ynPjQJXhGJ1ys69gkaYAdQyEdiX71gSDZiO
7Gd6z1xWl2MIfPrdI2YdT3Mwd3I3e9oytJ/45rEiD4I8C9fSI+Rlt3b0ipDWWmVQ
rTtuC1mYSMYJwMrGzB4wWtnK8v+P5QAK7qTB2vlx9P2cMh+FnZzBzE6lIN8gtTV6
oN7rOktxkM3xkj11wzN19E24seL+Vj2m6B1VMJWBhSAi2gYc7iHE1t4mL7VPMZ0C
9A3Phv1Y9HAamE2Pj1KS5EdvMHiWM7j79PIteW/Pvht4O0f0DmQdj5n5KXJ24rVf
2XRXM2nCYqSG0JCpk4DgIqTMr+0tH2g3Zo3z1Bv+4QKBgQDveMM8th4ce4x2o5h/
udC7qN+Jj+0c4F2Y1xSH/fIecyn2yzvQKjNS3fSNLM9m4mVH6Z0V6HOHfiXsyQ5F
QyV0Sq1EddwRL6bYlWfX5QXBcT6l5DJkzgHea9XlzvXojh8U2g4Jgcx1Ty2ttg2M
y+CP6t1x1vM9EcEJA9AIUUsNdwKBgQDezr7LOfb6OJ2mYBzPyC0tr3hNp1bh4ttH
on2A8gJxYIhSQsnmPpr3y1fB2QzkUE7R1w7/hYV4ZjNb10+Q3aX0iLtTQx7CXKLM
R7T2N0lHzlnLle4zh7m1v6XaDJLvEv84lZi60gVV9g4kvsER3OsrCDyoW8b7pJ+9
yus1HUQAsQKBgH+fwMJuZXm5iO6AWbF+Orl7DbLw4Hn5fFqk0SSGmkDwFAMrYi8/
Rh3jsB53T3p6yR3gT7wN9wRlL1fzY38frAwlzSSWBhVsH0h3J8T4Bi6IfDly4l2l
vPcCx5/uIeMtoJKzspZbyZhCfA0A3+Jt3BeG8iZl5Dmnb7w+6Bvefz7DAoGBAI8v
aqWYGg6xMm4PjA6v7hW7XxTbJ+q9u7dTYqQk/Q7VV2X4Qj8W44RdiB0xM7/pgWjN
owhTqfPHmYR0PxYkIg4vmLQfQF4Vq0dJS0L7vHvLNN4QxfrFDhrJ4Q8eXG4CWGvH
b0Ef0kyXeM8wQ47G+YX3Q+Za64pVF6uTICt5kGvBAoGAHwL3dh5kkThVNb3fK3IX
bqz0dB0si6M1nTPZb0y4ldXCOwMnp4Ckv6pO7B/Th2zDS8dM9k5iqWNqudGXcTt2
oxrkcF0Z+wQ6zT7nNzj7KRj9KPb7fHPM7dYY1PS1JQvSE+P0O8GRhRj43D8s1poT
z+FEvVK04hW85k3ELsjD7oQ=
-----END PRIVATE KEY-----"""


@pytest.fixture()
def config_file(tmp_path: Path, private_key: str) -> Path:
    key_path = tmp_path / "private.key"
    key_path.write_text(private_key, encoding="utf-8")
    config = {
        "app_name": "bankfetch",
        "provider": "enable_banking",
        "api": {
            "base_url": "https://api.enablebanking.com",
            "app_id": "test-app",
            "private_key_file": str(key_path),
            "timeout_seconds": 30,
        },
        "bank": {
            "aspsp": {"id": "bank-1", "name": "Nordea", "country": "DK"},
            "psu_type": "personal",
            "redirect_url": "http://127.0.0.1:8787/callback",
            "consent_days": 90,
        },
        "sync": {
            "overlap_days": 3,
            "output_dir": str(tmp_path / "out"),
            "state_dir": str(tmp_path / "state"),
            "raw_archive": True,
            "normalized_format": "jsonl",
            "initial_lookback_days": 30,
        },
        "logging": {"format": "json", "level": "info"},
        "headers": {"psu_user_agent": "bankfetch-test/0.1"},
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    return path
