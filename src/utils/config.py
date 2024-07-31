import yaml
import os
from pathlib import Path

def load_config():
    config_path = Path(__file__).parent.parent.parent / 'config' / 'config.yaml'
    with open(config_path, 'r') as file:
        config = yaml.safe_load(file)
    
    # Replace environment variables
    for category in config:
        if isinstance(config[category], dict):
            for key, value in config[category].items():
                if isinstance(value, str) and value.startswith('${') and value.endswith('}'):
                    env_var = value[2:-1]
                    config[category][key] = os.environ.get(env_var, value)
    
    return config
