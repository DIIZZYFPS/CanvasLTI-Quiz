import atexit
import json
import os
import shutil
import tempfile
import threading
from flask import current_app
from pylti1p3.contrib.flask import FlaskCacheDataStorage

# State for the env-var key path below. Built once per process (and again only if the
# inputs change) rather than on every request.
_ephemeral_lock = threading.Lock()
_ephemeral = {"signature": None, "config_path": None}


def get_lti_config_path():
    base_path = current_app.root_path
    config_path = os.path.join(base_path, 'config', 'config.json')

    # Normal deployments keep config/private.key on disk and use config.json as-is.
    # Only when that file is absent and the key is supplied via the LTI_PRIVATE_KEY
    # environment variable (e.g. a container/serverless setup with no key file) do we
    # materialise the key into a private temp directory.
    private_key_path = os.path.join(base_path, 'config', 'private.key')

    if not os.path.exists(private_key_path):
        env_key = os.environ.get("LTI_PRIVATE_KEY")
        if env_key:
            return _ephemeral_config_path(base_path, config_path, env_key)

    return config_path


def _write_private_file(path, content):
    """Create `path` readable/writable by the owner only (0600), never wider."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(content)


def _ephemeral_config_path(base_path, config_path, env_key):
    """Write the env-supplied key and a rewired config into a private temp dir, once.

    This used to rewrite /tmp/private.key and /tmp/config.json on *every* request.
    That was racy (a concurrent request could read a half-written, truncated key),
    left the private key with default permissions in the shared /tmp (readable by
    other local users, and at a predictable name another user could pre-create), and
    did needless disk writes on a hot path. Now the files live in a mkdtemp()
    directory (0700, unpredictable name), are written 0600, and are reused until the
    inputs change.
    """
    signature = (env_key, os.getenv('CANVAS_DOMAIN'), os.stat(config_path).st_mtime_ns)

    with _ephemeral_lock:
        cached = _ephemeral["config_path"]
        if _ephemeral["signature"] == signature and cached and os.path.exists(cached):
            return cached

        out_dir = tempfile.mkdtemp(prefix="lti-config-")
        atexit.register(shutil.rmtree, out_dir, ignore_errors=True)

        priv_path = os.path.join(out_dir, 'private.key')
        pub_path = os.path.join(out_dir, 'public.key')
        _write_private_file(priv_path, env_key)

        src_pub_path = os.path.join(base_path, 'config', 'public.key')
        if os.path.exists(src_pub_path):
            shutil.copyfile(src_pub_path, pub_path)

        new_path = create_ephemeral_config(config_path, priv_path, pub_path, out_dir)
        _ephemeral["signature"] = signature
        _ephemeral["config_path"] = new_path
        return new_path


def create_ephemeral_config(original_path, actual_priv_path, actual_pub_path, out_dir):
    with open(original_path, 'r') as f:
        config_data = json.load(f)

    target_domain = os.getenv('CANVAS_DOMAIN', 'http://canvas.docker:8081').rstrip('/')

    new_config = {}
    for issuer, entries in config_data.items():
        updated_entries = []
        for entry in entries:
            # Inject key paths
            entry["private_key_file"] = actual_priv_path
            entry["public_key_file"] = actual_pub_path

            # RE-WIRE HOSTNAMES: Swap 'canvas.docker:8081' with your public CANVAS_DOMAIN
            for key in ["auth_login_url", "auth_token_url", "key_set_url"]:
                if key in entry and "canvas.docker" in entry[key]:
                    entry[key] = entry[key].replace("http://canvas.docker:8081", target_domain)

            updated_entries.append(entry)

        new_config[issuer] = updated_entries
        if target_domain not in new_config:
            new_config[target_domain] = updated_entries

    tmp_config_path = os.path.join(out_dir, 'config.json')
    _write_private_file(tmp_config_path, json.dumps(new_config))

    return tmp_config_path

def get_launch_data_storage():
    from .. import cache
    return FlaskCacheDataStorage(cache)
