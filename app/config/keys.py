"""Generate this tool's RSA key pair for LTI 1.3 (private.key + public.key).

    python -m app.config.keys                 # writes into app/config/
    python -m app.config.keys --out some/dir
    python -m app.config.keys --force         # replace an existing pair

The private key never leaves the machine; register the public half with Canvas (or let
Canvas fetch it from the tool's /jwks/ endpoint). This used to be an unguarded script
that imported pycryptodome (never listed in requirements.txt), ran on import, wrote into
the current directory with default permissions, and silently overwrote existing keys.
It now uses `cryptography` (already a dependency), writes the private key owner-only
(0600), and refuses to replace keys unless asked.
"""
import argparse
import os
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

DEFAULT_BITS = 4096
PRIVATE_NAME = "private.key"
PUBLIC_NAME = "public.key"


def generate_key_pair(bits=DEFAULT_BITS):
    """Return (private_pem, public_pem) as bytes. Same PEM formats the pycryptodome version wrote."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=bits)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,   # "-----BEGIN RSA PRIVATE KEY-----"
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,  # "-----BEGIN PUBLIC KEY-----"
    )
    return private_pem, public_pem


def write_key_pair(out_dir, private_pem, public_pem, force=False):
    """Write the pair into `out_dir`; return the two paths. Refuses to overwrite unless `force`."""
    private_path = os.path.join(out_dir, PRIVATE_NAME)
    public_path = os.path.join(out_dir, PUBLIC_NAME)

    existing = [p for p in (private_path, public_path) if os.path.exists(p)]
    if existing and not force:
        raise FileExistsError(
            "Refusing to overwrite existing key file(s): " + ", ".join(existing) +
            ". Replacing a key breaks the Canvas registration; pass --force if that is intended."
        )

    os.makedirs(out_dir, exist_ok=True)
    # 0600 from the moment the file exists, not chmod'd afterwards.
    fd = os.open(private_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(private_pem)
    os.chmod(private_path, 0o600)  # os.open's mode doesn't apply when the file already existed
    with open(public_path, "wb") as f:
        f.write(public_pem)
    return private_path, public_path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate the tool's LTI 1.3 RSA key pair.")
    parser.add_argument("--out", default=os.path.dirname(os.path.abspath(__file__)),
                        help="directory to write private.key and public.key into (default: app/config)")
    parser.add_argument("--bits", type=int, default=DEFAULT_BITS, help=f"RSA key size (default {DEFAULT_BITS})")
    parser.add_argument("--force", action="store_true", help="overwrite existing keys")
    args = parser.parse_args(argv)

    try:
        private_pem, public_pem = generate_key_pair(args.bits)
        private_path, public_path = write_key_pair(args.out, private_pem, public_pem, force=args.force)
    except FileExistsError as e:
        print(e, file=sys.stderr)
        return 1

    print(f"Wrote {private_path} (keep secret) and {public_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
