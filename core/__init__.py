import os
import yaml

conf_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'conf.yml')

with open(conf_path, 'r') as file:
    conf = yaml.safe_load(file)

# ------------- global variables -----------------
# ------------- models.py variables -----------------
ROLE_CHOICES = [(role[0], role[1]) for role in conf['core']['role_choices']]
PAYMENT_STATUS_CHOICES = [(status[0], status[1]) for status in conf['core']['payment_status_choices']]
ASSET_TYPE_CHOICES = [(asset[0], asset[1]) for asset in conf['core']['asset_type_choices']]
EVENT_TYPE_CHOICES = [(event[0], event[1]) for event in conf['core']['event_type_choices']]


# ------------- views.py variables -----------------
transfer_policy_config =  conf['core']['transfer_policy_config']