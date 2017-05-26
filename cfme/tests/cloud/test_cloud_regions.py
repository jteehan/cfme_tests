import pytest

import cfme.fixtures.pytest_selenium as sel
from cfme import test_requirements
from cfme.cloud.provider.azure import AzureProvider
from cfme.cloud.provider.ec2 import EC2Provider
from cfme.web_ui import flash, form_buttons
from utils import testgen, error
from utils.conf import cfme_data
from utils.log import logger
from utils.appliance.implementations.ui import navigate_to

pytestmark = [
    pytest.mark.tier(1),
    test_requirements.proxy,
    pytest.mark.usefixtures('setup_provider_modscope')
]
pytest_generate_tests = testgen.generate([AzureProvider, EC2Provider],
                                         scope="module")

def test_regions_disable(appliance, provider, request):
    """Configures settings cloud provider :disable_regions: settings

    Args:
        None - Uses only the build in objects
    """
    logger.info("Begin Test Valid Default Proxy for Provider {}".format(provider.type))

    @request.addfinalizer
    def _cleanup_proxy():
        reset_region(appliance, provider)

    logger.info("Test to disable first")
    settings_local(appliance, provider.type, False)
    appliance.restart_evm_service(wait_for_web_ui=True)
    with error.expected('Credential validation was not successful:'):
        validate_provider(appliance, provider)
        flash.assert_message_match('Credential validation was successful')


def settings_local(appliance, provider):
    """Creates the file string and sends it to the appliance.  If more than one provider,
        It loops through each item in proxy_type

        Args: provider_type - is  provider.type and/or 'default'
              enable - determines if we want the region to be disabled or not.

    """
    region_info = cfme_data['regions_disable'][provider.type]
    if provider.type == 'azure':
        yml_header = ":ems_azure: \n  "
    elif provider.type == 'ec2':
        yml_header = ":ems_amazon: \n  "
    yml_setting = ":disabled_regions: \n    - {setting} ".format(region=region_info['setting'])
    config_yml = yml_header + yml_setting
    appliance.ssh_client.run_command(
        "echo \'{config}\' > /var/www/miq/vmdb/config/settings.local.yml".format(config=config_yml))


def reset_region(appliance, provider):
    """Clears the file string and sends it to the appliance

        Args: proxy_type - is a list that is either or more provider.type and/or 'default'
              We have to explicity clear each change as the values are cached at restart.
    """
    if provider.type == 'azure':
        yml_header = ":ems_azure: \n  "
    elif provider.type == 'ec2':
        yml_header = ":ems_amazon: \n  "
    yml_setting = ":disabled_regions: []")
    config_yml = yml_header + yml_setting
    appliance.ssh_client.run_command(
        "echo \'{}\' > /var/www/miq/vmdb/config/settings.local.yml".format(config_yml))
    appliance.restart_evm_service(wait_for_web_ui=True)
    validate_provider(appliance, provider)


def validate_provider(appliance, provider):
    """Navigates to the provider and clicks the validate button for immediate response"""
    navigate_to(provider, 'EditFromDetails')
    sel.click(form_buttons.validate)