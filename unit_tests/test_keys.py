import json
import os
import stat
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from pylti1p3.tool_config import ToolConfJsonFile

from app.config import keys

REPO_ROOT = os.path.join(os.path.dirname(__file__), '..')


@pytest.fixture(scope="module")
def pair():
    return keys.generate_key_pair(bits=2048)   # 4096 is the real default; 2048 keeps tests quick


def test_pem_formats_match_what_the_old_script_wrote(pair):
    private_pem, public_pem = pair
    assert private_pem.startswith(b"-----BEGIN RSA PRIVATE KEY-----")
    assert public_pem.startswith(b"-----BEGIN PUBLIC KEY-----")


def test_the_two_halves_belong_together(pair):
    private_pem, public_pem = pair
    private = serialization.load_pem_private_key(private_pem, password=None)
    public = serialization.load_pem_public_key(public_pem)
    signature = private.sign(b"hello", padding.PKCS1v15(), hashes.SHA256())
    public.verify(signature, b"hello", padding.PKCS1v15(), hashes.SHA256())   # raises if they don't match


def test_each_generation_is_a_new_key():
    assert keys.generate_key_pair(2048)[0] != keys.generate_key_pair(2048)[0]


def test_private_key_is_written_owner_only(tmp_path, pair):
    private_path, public_path = keys.write_key_pair(str(tmp_path), *pair)
    assert stat.S_IMODE(os.stat(private_path).st_mode) == 0o600
    assert open(private_path, "rb").read() == pair[0]
    assert open(public_path, "rb").read() == pair[1]


def test_existing_keys_are_not_overwritten_by_default(tmp_path, pair):
    """Replacing the key silently breaks the Canvas registration."""
    keys.write_key_pair(str(tmp_path), *pair)
    other = keys.generate_key_pair(2048)
    with pytest.raises(FileExistsError, match="--force"):
        keys.write_key_pair(str(tmp_path), *other)
    assert open(tmp_path / keys.PRIVATE_NAME, "rb").read() == pair[0]


def test_force_replaces_and_tightens_permissions_of_a_loose_existing_file(tmp_path, pair):
    loose = tmp_path / keys.PRIVATE_NAME
    loose.write_bytes(b"old")
    os.chmod(loose, 0o644)
    other = keys.generate_key_pair(2048)
    keys.write_key_pair(str(tmp_path), *other, force=True)
    assert loose.read_bytes() == other[0]
    assert stat.S_IMODE(os.stat(loose).st_mode) == 0o600


def test_cli_creates_refuses_then_forces(tmp_path, capsys):
    assert keys.main(["--out", str(tmp_path), "--bits", "2048"]) == 0
    first = (tmp_path / keys.PRIVATE_NAME).read_bytes()

    assert keys.main(["--out", str(tmp_path), "--bits", "2048"]) == 1
    assert "Refusing to overwrite" in capsys.readouterr().err
    assert (tmp_path / keys.PRIVATE_NAME).read_bytes() == first

    assert keys.main(["--out", str(tmp_path), "--bits", "2048", "--force"]) == 0
    assert (tmp_path / keys.PRIVATE_NAME).read_bytes() != first


def test_cli_creates_the_output_directory(tmp_path):
    target = tmp_path / "does" / "not" / "exist"
    assert keys.main(["--out", str(target), "--bits", "2048"]) == 0
    assert (target / keys.PUBLIC_NAME).exists()


def test_generated_keys_work_with_pylti1p3(tmp_path, pair):
    """The point of the script: the LTI library must be able to load what it writes."""
    private_path, public_path = keys.write_key_pair(str(tmp_path), *pair)
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"https://canvas.example.com": [{
        "client_id": "123",
        "auth_login_url": "https://canvas.example.com/api/lti/authorize_redirect",
        "auth_token_url": "https://canvas.example.com/login/oauth2/token",
        "key_set_url": "https://canvas.example.com/api/lti/security/jwks",
        "private_key_file": private_path,
        "public_key_file": public_path,
        "deployment_ids": ["1:abc"],
    }]}))

    jwks = ToolConfJsonFile(str(config)).get_jwks()
    assert len(jwks["keys"]) == 1
    assert jwks["keys"][0]["kty"] == "RSA"
    assert "d" not in jwks["keys"][0], "the JWKS endpoint must publish only the public half"


def test_importing_the_module_has_no_side_effects(tmp_path):
    """It used to generate a 4096-bit key and write files into the CWD on import."""
    result = subprocess.run(
        [sys.executable, "-I", "-c", "import sys; sys.path.insert(0, sys.argv[1]); import app.config.keys", os.path.abspath(REPO_ROOT)],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []
