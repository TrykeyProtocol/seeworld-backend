import yaml
import os

conf_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'conf.yml')

with open(conf_path, 'r') as file:
    conf = yaml.safe_load(file)

# Access variables from conf.yaml under 'assets' app
ROLE_CHOICES = conf['assets']['role_choices']

