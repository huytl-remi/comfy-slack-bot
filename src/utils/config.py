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

    # Add a custom temp directory
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    config['temp_dir'] = os.path.join(base_dir, 'temp')

    # Ensure the temp directory exists
    os.makedirs(config['temp_dir'], exist_ok=True)

    return config
