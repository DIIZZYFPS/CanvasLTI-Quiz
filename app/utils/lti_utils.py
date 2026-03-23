import os
import tempfile
import json
import shutil
from flask import current_app
from pylti1p3.contrib.flask import FlaskMessageLaunch, FlaskCacheDataStorage
from pylti1p3.registration import Registration

class ExtendedFlaskMessageLaunch(FlaskMessageLaunch):
    def validate_nonce(self):
        """
        Probably it is bug on "https://lti-ri.imsglobal.org":
        site passes invalid "nonce" value during deep links launch.
        Because of this in case of iss == http://imsglobal.org just skip nonce validation.
        """
        iss = self.get_iss()
        deep_link_launch = self.is_deep_link_launch()
        if iss == "http://imsglobal.org" and deep_link_launch:
            return self
        return super().validate_nonce()

def get_lti_config_path():
    base_path = current_app.root_path
    config_path = os.path.join(base_path, 'config', 'config.json')
    
    # Check if we are in a serverless/Vercel env (missing private key on disk)
    private_key_path = os.path.join(base_path, 'config', 'private.key')
    
    if not os.path.exists(private_key_path):
        env_key = os.environ.get("LTI_PRIVATE_KEY")
        if env_key:
            tmp_dir = tempfile.gettempdir()
            tmp_priv_path = os.path.join(tmp_dir, 'private.key')
            tmp_pub_path = os.path.join(tmp_dir, 'public.key')
            
            # 1. Write Keys to /tmp
            with open(tmp_priv_path, 'w') as f: f.write(env_key)
            src_pub_path = os.path.join(base_path, 'config', 'public.key')
            if os.path.exists(src_pub_path):
                shutil.copy2(src_pub_path, tmp_pub_path)
            
            # 2. Return transformed config
            return create_ephemeral_config(config_path, tmp_priv_path, tmp_pub_path)

    return config_path

def create_ephemeral_config(original_path, actual_priv_path, actual_pub_path):
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
            
    tmp_config_path = os.path.join(tempfile.gettempdir(), 'config.json')
    with open(tmp_config_path, 'w') as f:
        json.dump(new_config, f)
        
    return tmp_config_path

def get_launch_data_storage():
    from .. import cache
    return FlaskCacheDataStorage(cache)

def get_jwk_from_public_key(key_name):
    key_path = os.path.join(current_app.root_path, 'config', key_name)
    with open(key_path, 'rb') as key_file:
        public_key = key_file.read()
        jwk = Registration.get_jwk(public_key)
        return jwk
