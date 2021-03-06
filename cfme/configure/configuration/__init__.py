# -*- coding: utf-8 -*-
from navmazing import (NavigateToAttribute,
                       NavigateToSibling,
                       NavigateToObject,
                       NavigationDestinationNotFound)
from widgetastic_patternfly import CandidateNotFound

from contextlib import contextmanager
from fixtures.pytest_store import store
from functools import partial

from cfme.base.ui import Server, Region, ConfigurationView, Zone
from cfme.exceptions import (
    AuthModeUnknown,
    ConsoleNotSupported,
    ConsoleTypeNotSupported,
    ScheduleNotFound)
import cfme.fixtures.pytest_selenium as sel
import cfme.web_ui.tabstrip as tabs
import cfme.web_ui.toolbar as tb
from cfme.web_ui import (
    AngularSelect, Calendar, CheckboxSelect, CFMECheckbox, DynamicTable, Form, InfoBlock, Input,
    Region as UIRegion, Select, Table, accordion, fill, flash, form_buttons)
from cfme.web_ui.form_buttons import change_stored_password
from utils import version, conf
from utils.appliance import Navigatable, current_appliance
from utils.appliance.implementations.ui import navigator, CFMENavigateStep, navigate_to
from utils.blockers import BZ
from utils.log import logger
from utils.pretty import Pretty
from utils.timeutil import parsetime
from utils.update import Updateable
from utils.wait import wait_for, TimedOutError


access_tree = partial(accordion.tree, "Access Control")
database_tree = partial(accordion.tree, "Database")
settings_tree = partial(accordion.tree, "Settings")
diagnostics_tree = partial(accordion.tree, "Diagnostics")

replication_worker = Form(
    fields=[
        ('database', Input("replication_worker_dbname")),
        ('port', Input("replication_worker_port")),
        ('username', Input("replication_worker_username")),
        ('password', Input("replication_worker_password")),
        ('password_verify', Input("replication_worker_verify")),
        ('host', Input("replication_worker_host")),
    ]
)

replication_process = UIRegion(locators={
    "status": InfoBlock("Replication Process", "Status"),
    "current_backlog": InfoBlock("Replication Process", "Current Backlog"),
})

server_roles = Form(
    fields=[
        # TODO embedded_ansible is only present in CFME 5.8 (MIQ Fine+)
        ('embedded_ansible', CFMECheckbox("server_roles_embedded_ansible")),
        ('ems_metrics_coordinator', CFMECheckbox("server_roles_ems_metrics_coordinator")),
        ('ems_operations', CFMECheckbox("server_roles_ems_operations")),
        ('ems_metrics_collector', CFMECheckbox("server_roles_ems_metrics_collector")),
        ('reporting', CFMECheckbox("server_roles_reporting")),
        ('ems_metrics_processor', CFMECheckbox("server_roles_ems_metrics_processor")),
        ('scheduler', CFMECheckbox("server_roles_scheduler")),
        ('smartproxy', CFMECheckbox("server_roles_smartproxy")),
        ('database_operations', CFMECheckbox("server_roles_database_operations")),
        ('smartstate', CFMECheckbox("server_roles_smartstate")),
        ('event', CFMECheckbox("server_roles_event")),
        ('user_interface', CFMECheckbox("server_roles_user_interface")),
        ('web_services', CFMECheckbox("server_roles_web_services")),
        ('ems_inventory', CFMECheckbox("server_roles_ems_inventory")),
        ('notifier', CFMECheckbox("server_roles_notifier")),
        ('automate', CFMECheckbox("server_roles_automate")),
        ('rhn_mirror', CFMECheckbox("server_roles_rhn_mirror")),
        ('database_synchronization', CFMECheckbox("server_roles_database_synchronization")),
        ('git_owner', CFMECheckbox("server_roles_git_owner")),
        ('websocket', CFMECheckbox("server_roles_websocket")),
        ('cockpit_ws', CFMECheckbox("server_roles_cockpit_ws")),
        # STORAGE OPTIONS
        ("storage_metrics_processor", CFMECheckbox("server_roles_storage_metrics_processor")),
        ("storage_metrics_collector", CFMECheckbox("server_roles_storage_metrics_collector")),
        ("storage_metrics_coordinator", CFMECheckbox("server_roles_storage_metrics_coordinator")),
        ("storage_inventory", CFMECheckbox("server_roles_storage_inventory")),
        ("vmdb_storage_bridge", CFMECheckbox("server_roles_vmdb_storage_bridge")),

    ]
)

ntp_servers = Form(
    fields=[
        ('ntp_server_1', Input("ntp_server_1")),
        ('ntp_server_2', Input("ntp_server_2")),
        ('ntp_server_3', Input("ntp_server_3")),
    ]
)

depot_types = dict(
    anon_ftp="Anonymous FTP",
    ftp="FTP",
    nfs="NFS",
    smb="Samba",
    dropbox="Red Hat Dropbox",
)

db_configuration = Form(
    fields=[
        ('type', Select("select#production_dbtype")),
        ('hostname', Input("production_host")),
        ('database', Input("production_database")),
        ('username', Input("production_username")),
        ('password', Input("production_password")),
        ('password_verify', Input("production_verify")),
    ]
)

category_form = Form(
    fields=[
        ('new_tr', "//tr[@id='new_tr']"),
        ('name', Input("name")),
        ('display_name', Input("description")),
        ('description', Input("example_text")),
        ('show_in_console', CFMECheckbox("show")),
        ('single_value', CFMECheckbox("single_value")),
        ('capture_candu', CFMECheckbox("perf_by_tag"))
    ])

tag_form = Form(
    fields=[
        ('category', {
            version.LOWEST: Select("select#classification_name"),
            '5.5': AngularSelect('classification_name')}),
        ('name', Input("entry[name]")),
        ('display_name', Input("entry[description]")),
        ('add', {
            version.LOWEST: Input("accept"),
            '5.6': '//button[normalize-space(.)="Add"]'
        }),
        ('new', {
            version.LOWEST: "//span[@class='glyphicon glyphicon-plus']",
            '5.6': '//button[normalize-space(.)="Add"]'
        }),
        ('save', '//button[normalize-space(.)="Save"]'),
    ])


records_table = Table("//div[@id='records_div']/table")
category_table = Table("//div[@id='settings_co_categories']/table")
classification_table = Table("//div[@id='classification_entries_div']/table")


class AnalysisProfile(Pretty, Updateable, Navigatable):
    """Analysis profiles. Do not use this class but the derived one.

    Example:

        .. code-block:: python

            p = AnalysisProfile(name, description, profile_type='VM')
            p.files = [
                "/somefile",
                {"Name": "/some/anotherfile", "Collect Contents?": True}
            ]
            p.categories = ["check_system"]
            p.create()
            p.delete()

    """
    CREATE_LOC = None
    pretty_attrs = "name", "description", "files", "events"

    form = tabs.TabStripForm(
        fields=[
            ("name", "input#name"),
            ("description", "input#description")],
        tab_fields={
            "Category": [
                ("categories", CheckboxSelect({
                    version.LOWEST: "table#formtest",
                    "5.5":
                    "//h3[normalize-space(.)='Category Selection']/.."
                    "//div[contains(@class, 'col-md-8')]"})),
            ],
            "File": [
                ("files", {
                    "5.6": DynamicTable("//div[@id='file']/fieldset/table",
                                        default_row_item="Name"),
                    "5.7": DynamicTable("//div[@id='file']/table",
                                        default_row_item="Name")}),
            ],
            "Registry": [
                ("registry", {"5.6": DynamicTable("//div[@id='registry']/fieldset/table"),
                              "5.7": DynamicTable("//div[@id='registry']/table")}),
            ],

            "Event Log": [
                ("events", {"5.6": DynamicTable("//div[@id='event_log']/fieldset/table"),
                            "5.7": DynamicTable("//div[@id='event_log']/table")}),
            ],
        })

    def __init__(self, name, description, profile_type, files=None, events=None, categories=None,
                 registry=None, appliance=None):
        Navigatable.__init__(self, appliance=appliance)
        self.name = name
        self.description = description
        self.files = files
        self.events = events
        self.categories = categories
        self.registry = registry
        if profile_type in ('Host', 'VM'):
            self.profile_type = profile_type
        else:
            raise ValueError("Profile Type is incorrect")

    def create(self):
        navigate_to(self, 'Add')
        fill(self.form, self, action=form_buttons.add)
        flash.assert_no_errors()

    def update(self, updates=None):
        navigate_to(self, 'Edit')
        if updates is None:
            fill(self.form, self, action=form_buttons.save)
        else:
            fill(self.form, updates, action=form_buttons.save)
        flash.assert_no_errors()

    def delete(self):
        navigate_to(self, 'Details')
        tb.select("Configuration", "Delete this Analysis Profile", invokes_alert=True)
        sel.handle_alert()
        flash.assert_no_errors()

    def copy(self, name=None):
        if not name:
            name = self.name + "copy"
        navigate_to(self, 'Copy')
        new_profile = AnalysisProfile(name=name, description=self.description,
                                      profile_type=self.profile_type, files=self.files)
        fill(self.form, {'name': new_profile.name},
             action=form_buttons.add)
        flash.assert_success_message('Analysis Profile "{}" was saved'.format(new_profile.name))
        return new_profile

    @property
    def exists(self):
        try:
            navigate_to(self, 'Details')
        except (NavigationDestinationNotFound, CandidateNotFound):
            return False
        else:
            return True

    def __str__(self):
        return self.name

    def __enter__(self):
        self.create()

    def __exit__(self, type, value, traceback):
        self.delete()


@navigator.register(AnalysisProfile, 'All')
class AnalysisProfileAll(CFMENavigateStep):
    VIEW = ConfigurationView
    prerequisite = NavigateToObject(Server, 'Configuration')

    def step(self):
        server_region = self.obj.appliance.server_region_string()
        self.prerequisite_view.accordions.settings.tree.click_path(
            server_region, "Analysis Profiles")


@navigator.register(AnalysisProfile, 'Add')
class AnalysisProfileAdd(CFMENavigateStep):
    prerequisite = NavigateToSibling('All')

    def step(self):
        tb.select("Configuration", "Add {type} Analysis Profile".format(type=self.obj.profile_type))


@navigator.register(AnalysisProfile, 'Details')
class AnalysisProfileDetails(CFMENavigateStep):
    prerequisite = NavigateToSibling('All')

    def step(self):
        server_region = self.obj.appliance.server_region_string()
        self.prerequisite_view.accordions.settings.tree.click_path(
            server_region, "Analysis Profiles", str(self.obj))


@navigator.register(AnalysisProfile, 'Edit')
class AnalysisProfileEdit(CFMENavigateStep):
    prerequisite = NavigateToSibling('Details')

    def step(self):
        tb.select("Configuration", "Edit this Analysis Profile")


@navigator.register(AnalysisProfile, 'Copy')
class AnalysisProfileCopy(CFMENavigateStep):
    prerequisite = NavigateToSibling('Details')

    def step(self):
        tb.select('Configuration', 'Copy this selected Analysis Profile')


class ServerLogDepot(Pretty, Navigatable):
    """ This class represents the 'Collect logs' for the server.

    Usage:

        log_credentials = configure.ServerLogDepot("anon_ftp",
                                               depot_name=fauxfactory.gen_alphanumeric(),
                                               uri=fauxfactory.gen_alphanumeric())
        log_credentials.create()
        log_credentials.clear()

    """

    def __init__(self, depot_type, depot_name=None, uri=None, username=None, password=None,
                 zone_collect=False, second_server_collect=False, appliance=None):
        self.depot_name = depot_name
        self.uri = uri
        self.username = username
        self.password = password
        self.depot_type = depot_types[depot_type]
        self.zone_collect = zone_collect
        self.second_server_collect = second_server_collect
        Navigatable.__init__(self, appliance=appliance)

        self.obj_type = Zone(self.appliance) if self.zone_collect else self.appliance.server

    def create(self, cancel=False):
        self.clear()
        if self.second_server_collect and not self.zone_collect:
            view = navigate_to(self.appliance.server, 'DiagnosticsCollectLogsEditSlave')
        else:
            view = navigate_to(self.obj_type, 'DiagnosticsCollectLogsEdit')
        view.fill({'depot_type': self.depot_type})
        if self.depot_type != 'Red Hat Dropbox':
            view.fill({'depot_name': self.depot_name,
                       'uri': self.uri})
        if self.depot_type in ['FTP', 'Samba']:
            view.fill({'username': self.username,
                       'password': self.password,
                       'confirm_password': self.password})
            view.validate.click()
            view.flash.assert_success_message("Log Depot Settings were validated")
        if cancel:
            view.cancel.click()
            view.flash.assert_success_message("Edit Log Depot settings was cancelled by the user")
        else:
            view.save.click()
            view.flash.assert_success_message("Log Depot Settings were saved")

    @property
    def last_collection(self):
        if self.second_server_collect and not self.zone_collect:
            view = navigate_to(self.appliance.server, 'DiagnosticsCollectLogsSlave')
        else:
            view = navigate_to(self.obj_type, 'DiagnosticsCollectLogs')
        text = view.last_log_collection.text
        if text.lower() == "never":
            return None
        else:
            try:
                return parsetime.from_american_with_utc(text)
            except ValueError:
                return parsetime.from_iso_with_utc(text)

    @property
    def last_message(self):
        if self.second_server_collect:
            view = navigate_to(self.appliance.server, 'DiagnosticsCollectLogsSlave')
        else:
            view = navigate_to(self.appliance.server, 'DiagnosticsCollectLogs')
        return view.last_log_message.text

    @property
    def is_cleared(self):
        if self.second_server_collect and not self.zone_collect:
            view = navigate_to(self.appliance.server, 'DiagnosticsCollectLogsSlave')
        else:
            view = navigate_to(self.obj_type, 'DiagnosticsCollectLogs')
        return view.log_depot_uri.text == "N/A"

    def clear(self):
        """ Set depot type to "No Depot"

        """
        if not self.is_cleared:
            if self.second_server_collect and not self.zone_collect:
                view = navigate_to(self.appliance.server, 'DiagnosticsCollectLogsEditSlave')
            else:
                view = navigate_to(self.obj_type, 'DiagnosticsCollectLogsEdit')
            if BZ.bugzilla.get_bug(1436326).is_opened:
                wait_for(lambda: view.depot_type.selected_option != '<No Depot>', num_sec=5)
            view.depot_type.fill('<No Depot>')
            view.save.click()
            view.flash.assert_success_message("Log Depot Settings were saved")

    def _collect(self, selection):
        """ Initiate and wait for collection to finish.

        Args:
            selection: The item in Collect menu ('Collect all logs' or 'Collect current logs')
        """

        if self.second_server_collect and not self.zone_collect:
            view = navigate_to(self.appliance.server, 'DiagnosticsCollectLogsSlave')
        else:
            view = navigate_to(self.obj_type, 'DiagnosticsCollectLogs')
        last_collection = self.last_collection
        # Initiate the collection
        tb.select("Collect", selection)
        if self.zone_collect:
            message = "Zone {}".format(self.obj_type.name)
        elif self.second_server_collect:
            message = "MiqServer {} [{}]".format(
                self.appliance.slave_server_name(), self.appliance.slave_server_zone_id())
        else:
            message = "MiqServer {} [{}]".format(
                self.appliance.server_name(), self.appliance.server_zone_id())
        view.flash.assert_success_message(
            "Log collection for {} {} has been initiated".
            format(self.appliance.product_name, message))

        def _refresh():
            """ The page has no refresh button, so we'll switch between tabs.

            Why this? Selenium's refresh() is way too slow. This is much faster.

            """
            if self.zone_collect:
                navigate_to(self.obj_type, 'Servers')
            else:
                navigate_to(self.obj_type, 'Workers')
            if self.second_server_collect:
                navigate_to(self.appliance.server, 'DiagnosticsCollectLogsSlave')
            else:
                navigate_to(self.appliance.server, 'DiagnosticsCollectLogs')

        # Wait for start
        if last_collection is not None:
            # How does this work?
            # The time is updated just after the collection has started
            # If the Text is Never, we will not wait as there is nothing in the last message.
            wait_for(
                lambda: self.last_collection > last_collection,
                num_sec=90,
                fail_func=_refresh,
                message="wait_for_log_collection_start"
            )
        # Wait for finish
        wait_for(
            lambda: "were successfully collected" in self.last_message,
            num_sec=4 * 60,
            fail_func=_refresh,
            message="wait_for_log_collection_finish"
        )

    def collect_all(self):
        """ Initiate and wait for collection of all logs to finish.

        """
        self._collect("Collect all logs")

    def collect_current(self):
        """ Initiate and wait for collection of the current log to finish.

        """
        self._collect("Collect current logs")


class BasicInformation(Updateable, Pretty, Navigatable):
    """ This class represents the "Basic Info" section of the Configuration page.

    Args:
        company_name: Company name.
        appliance_name: Appliance name.
        appliance_zone: Appliance Zone.
        time_zone: Time Zone.

    Usage:

        basic_info = BasicInformation(company_name="ACME Inc.")
        basic_info.update()

    """
    basic_information = Form(
        fields=[
            ('company_name', Input("server_company")),
            ('appliance_name', Input("server_name")),
            ('appliance_zone', Select("select#server_zone")),
            ('time_zone', Select("select#server_timezone")),
        ]
    )
    pretty_attrs = ['company_name', 'appliance_name', 'appliance_zone', 'time_zone', 'appliance']

    def __init__(
            self, company_name=None, appliance_name=None, appliance_zone=None, time_zone=None,
            appliance=None):
        assert (company_name or appliance_name or appliance_zone or time_zone), \
            "You must provide at least one param!"
        self.company_name = company_name
        self.appliance_name = appliance_name
        self.appliance_zone = appliance_zone
        self.time_zone = time_zone
        Navigatable.__init__(self, appliance=appliance)

    def update(self):
        """ Navigate to a correct page, change details and save.

        """
        # TODO: These should move as functions of the server and don't need to be classes
        navigate_to(current_appliance.server, 'Server')
        fill(self.basic_information, self, action=form_buttons.save)
        self.appliance.server_details_changed()


class VMwareConsoleSupport(Updateable, Pretty, Navigatable):
    """
    This class represents the "VMware Console Support" section of the Configuration page.
    Note this is to support CFME 5.8 and beyond functionality.

    Args:
        console_type:  One of the following strings 'VMware VMRC Plugin', 'VNC' or 'VMware WebMKS'

    Usage:

        vmware_console_support = VMwareConsoleSupport(console_type="VNC")
        vmware_console_support.update()

    """
    vmware_console_form = Form(
        fields=[
            ('console_type', AngularSelect("console_type")),
        ]
    )
    pretty_attrs = ['console_type']

    CONSOLE_TYPES = ['VNC', 'VMware VMRC Plugin', 'VMware WebMKS']

    def __init__(self, console_type, appliance=None):
        if console_type not in VMwareConsoleSupport.CONSOLE_TYPES:
            raise ConsoleTypeNotSupported(console_type)

        if appliance.version < '5.8':
            raise ConsoleNotSupported(
                product_name=appliance.product_name,
                version=appliance.version
            )

        self.console_type = console_type
        Navigatable.__init__(self, appliance=appliance)

    def update(self):
        """ Navigate to a correct page, change details and save.

        """
        # TODO: These should move as functions of the server and don't need to be classes
        logger.info("Updating VMware Console form")
        navigate_to(current_appliance.server, 'Server')
        fill(self.vmware_console_form, self, action=form_buttons.save)
        self.appliance.server_details_changed()


class SMTPSettings(Updateable):
    """ SMTP settings on the main page.

    Args:
        host: SMTP Server host name
        port: SMTP Server port
        domain: E-mail domain
        start_tls: Whether use StartTLS
        ssl_verify: SSL Verification
        auth: Authentication type
        username: User name
        password: User password
        from_email: E-mail address to be used as the "From:"
        test_email: Destination of the test-email.

    Usage:

        smtp = SMTPSettings(
            host="smtp.acme.com",
            start_tls=True,
            auth="login",
            username="mailer",
            password="secret"
        )
        smtp.update()

    Note: TODO: send a test-email, if that will be needed.

    """
    smtp_settings = Form(
        fields=[
            ('host', Input("smtp_host")),
            ('port', Input("smtp_port")),
            ('domain', Input("smtp_domain")),
            ('start_tls', Input("smtp_enable_starttls_auto")),
            ('ssl_verify', AngularSelect("smtp_openssl_verify_mode")),
            ('auth', AngularSelect("smtp_authentication")),
            ('username', Input("smtp_user_name")),
            ('password', Input("smtp_password")),
            ('from_email', Input("smtp_from")),
            ('to_email', Input("smtp_test_to")),
        ]
    )

    buttons = UIRegion(
        locators=dict(
            test="|".join([
                "//img[@alt='Send test email']",
                "//button[@alt='Send test email']",
                "//a[@title='Send test email']",
            ])
        )
    )

    def __init__(self,
                 host=None,
                 port=None,
                 domain=None,
                 start_tls=None,
                 ssl_verify=None,
                 auth=None,
                 username=None,
                 password=None,
                 from_email=None,
                 test_email=None):
        self.details = dict(
            host=host,
            port=port,
            domain=domain,
            start_tls=start_tls,
            ssl_verify=ssl_verify,
            auth=auth,
            username=username,
            password=password,
            from_email=from_email,
            test_email=test_email
        )

    def update(self):
        navigate_to(current_appliance.server, 'Server')
        fill(self.smtp_settings, self.details, action=form_buttons.save)

    @classmethod
    def send_test_email(cls, to_address):
        """ Send a testing e-mail on specified address. Needs configured SMTP.

        Args:
            to_address: Destination address.
        """
        navigate_to(current_appliance.server, 'Server')
        fill(cls.smtp_settings, dict(to_email=to_address), action=cls.buttons.test)


class AuthSetting(Updateable, Pretty):
    form = Form(fields=[
        ("timeout_h", {
            version.LOWEST: Select("select#session_timeout_hours"),
            '5.5': AngularSelect('session_timeout_hours')}),
        ("timeout_m", {
            version.LOWEST: Select("select#session_timeout_mins"),
            '5.5': AngularSelect('session_timeout_mins')}),
    ])

    @classmethod
    def set_session_timeout(cls, hours=None, minutes=None):
        """Sets the session timeout of the appliance."""
        navigate_to(current_appliance.server, 'Authentication')
        logger.info(
            "Setting authentication timeout to %s hours and %s minutes.", hours, minutes)
        fill(cls.form, {"timeout_h": hours, "timeout_m": minutes}, action=form_buttons.save)
        flash.assert_no_errors()
        flash.assert_message_contain("Authentication settings saved")


class DatabaseAuthSetting(AuthSetting):
    """ Authentication settings for DB internal database.

    Args:
        timeout_h: Timeout in hours
        timeout_m: Timeout in minutes

    Usage:

        dbauth = DatabaseAuthSetting()
        dbauth.update()

    """

    form = Form(fields=[
        ("timeout_h", {
            version.LOWEST: Select("select#session_timeout_hours"),
            '5.5': AngularSelect('session_timeout_hours')}),
        ("timeout_m", {
            version.LOWEST: Select("select#session_timeout_mins"),
            '5.5': AngularSelect('session_timeout_mins')}),
        ("auth_mode", {
            version.LOWEST: Select("select#authentication_mode"),
            '5.5': AngularSelect('authentication_mode')})
    ])
    pretty_attrs = ['timeout_h', 'timeout_m']

    def __init__(self, timeout_h=None, timeout_m=None):
        self.timeout_h = timeout_h
        self.timeout_m = timeout_m
        self.auth_mode = "Database"

    def update(self, updates=None):
        navigate_to(current_appliance.server, 'Authentication')
        fill(self.form, updates if updates is not None else self, action=form_buttons.save)


class ExternalAuthSetting(AuthSetting):
    """ Authentication settings for authentication via httpd.

    Args:
        timeout_h: Timeout in hours
        timeout_m: Timeout in minutes
        get_groups: Get user groups from external auth source.

    Usage:

        dbauth = ExternalAuthSetting(get_groups=True)
        dbauth.update()

    """

    form = Form(fields=[
        ("timeout_h", {
            version.LOWEST: Select("select#session_timeout_hours"),
            '5.5': AngularSelect('session_timeout_hours')}),
        ("timeout_m", {
            version.LOWEST: Select("select#session_timeout_mins"),
            '5.5': AngularSelect('session_timeout_mins')}),
        ("auth_mode", {
            version.LOWEST: Select("select#authentication_mode"),
            '5.5': AngularSelect('authentication_mode')}),
        ("get_groups", Input("httpd_role")),
    ])
    pretty_attrs = ['timeout_h', 'timeout_m', 'get_groups']

    def __init__(self, get_groups=False, timeout_h="1", timeout_m="0"):
        self.timeout_h = timeout_h
        self.timeout_m = timeout_m
        self.auth_mode = "External (httpd)"
        self.get_groups = get_groups

    def setup(self):
        navigate_to(current_appliance.server, 'Authentication')
        fill(self.form, self, action=form_buttons.save)

    def update(self, updates=None):
        navigate_to(current_appliance.server, 'Authentication')
        fill(self.form, updates if updates is not None else self, action=form_buttons.save)


class AmazonAuthSetting(AuthSetting):
    """ Authentication settings via Amazon.

    Args:
        access_key: Amazon access key
        secret_key: Amazon secret key
        get_groups: Whether to get groups from the auth provider (default `False`)
        timeout_h: Timeout in hours
        timeout_m: Timeout in minutes

    Usage:

        amiauth = AmazonAuthSetting("AJSHDGVJAG", "IUBDIUWQBQW")
        amiauth.update()

    """

    form = Form(fields=[
        ("timeout_h", {
            version.LOWEST: Select("select#session_timeout_hours"),
            '5.5': AngularSelect('session_timeout_hours')}),
        ("timeout_m", {
            version.LOWEST: Select("select#session_timeout_mins"),
            '5.5': AngularSelect('session_timeout_mins')}),
        ("auth_mode", {
            version.LOWEST: Select("select#authentication_mode"),
            '5.5': AngularSelect('authentication_mode')}),
        ("access_key", Input("authentication_amazon_key")),
        ("secret_key", Input("authentication_amazon_secret")),
        ("get_groups", Input("amazon_role")),
    ])
    pretty_attrs = ['access_key', 'secret_key', 'get_groups', 'timeout_h', 'timeout_m']

    def __init__(self, access_key, secret_key, get_groups=False, timeout_h=None, timeout_m=None):
        self.access_key = access_key
        self.secret_key = secret_key
        self.get_groups = get_groups
        self.timeout_h = timeout_h
        self.timeout_m = timeout_m
        self.auth_mode = "Amazon"

    def update(self, updates=None):
        navigate_to(current_appliance.server, 'Authentication')
        fill(self.form, updates if updates is not None else self, action=form_buttons.save)


class LDAPAuthSetting(AuthSetting):
    """ Authentication via LDAP

    Args:
        hosts: List of LDAP servers (max 3).
        user_type: "userprincipalname", "mail", ...
        user_suffix: User suffix.
        base_dn: Base DN.
        bind_dn: Bind DN.
        bind_password: Bind Password.
        get_groups: Get user groups from LDAP.
        get_roles: Get roles from home forest.
        follow_referrals: Follow Referrals.
        port: LDAP connection port.
        timeout_h: Timeout in hours
        timeout_m: Timeout in minutes

    Usage:

        ldapauth = LDAPAuthSetting(
            ["host1", "host2"],
            "mail",
            "user.acme.com"
        )
        ldapauth.update()

    """
    form = Form(fields=[
        ("timeout_h", {
            version.LOWEST: Select("select#session_timeout_hours"),
            '5.5': AngularSelect('session_timeout_hours')}),
        ("timeout_m", {
            version.LOWEST: Select("select#session_timeout_mins"),
            '5.5': AngularSelect('session_timeout_mins')}),
        ("auth_mode", {
            version.LOWEST: Select("select#authentication_mode"),
            '5.5': AngularSelect('authentication_mode')}),
        ("ldaphost_1", Input("authentication_ldaphost_1")),
        ("ldaphost_2", Input("authentication_ldaphost_2")),
        ("ldaphost_3", Input("authentication_ldaphost_3")),
        ("port", Input("authentication_ldapport")),
        ("user_type", {
            version.LOWEST: Select("select#authentication_user_type"),
            "5.5": AngularSelect("authentication_user_type")}),
        ("user_suffix", Input("authentication_user_suffix")),
        ("get_groups", Input("ldap_role")),
        ("get_roles", Input("get_direct_groups")),
        ("default_groups", {
            version.LOWEST: Select("select#authentication_default_group_for_users"),
            '5.5': AngularSelect('authentication_default_group_for_users')}),
        ("get_direct_groups", Input("get_direct_groups")),
        ("follow_referrals", Input("follow_referrals")),
        ("base_dn", Input("authentication_basedn")),
        ("bind_dn", Input("authentication_bind_dn")),
        ("bind_password", Input("authentication_bind_pwd")),
    ])

    AUTH_MODE = "LDAP"
    pretty_attrs = ['hosts', 'user_type', 'user_suffix', 'base_dn', 'bind_dn', 'bind_password']

    def __init__(self,
                 hosts,
                 user_type,
                 user_suffix,
                 base_dn=None,
                 bind_dn=None,
                 bind_password=None,
                 get_groups=False,
                 get_roles=False,
                 follow_referrals=False,
                 port=None,
                 timeout_h=None,
                 timeout_m=None,
                 ):
        self.user_type = sel.ByValue(user_type)
        self.user_suffix = user_suffix
        self.base_dn = base_dn
        self.bind_dn = bind_dn
        self.bind_password = bind_password
        self.get_groups = get_groups
        self.get_roles = get_roles
        self.follow_referrals = follow_referrals
        self.port = port
        self.timeout_h = timeout_h
        self.timeout_m = timeout_m
        self.auth_mode = self.AUTH_MODE
        self.ldaphost_1 = None
        self.ldaphost_2 = None
        self.ldaphost_3 = None
        assert len(hosts) <= 3, "You can specify only 3 LDAP hosts"
        for enum, host in enumerate(hosts):
            setattr(self, "ldaphost_{}".format(enum + 1), host)

    def update(self, updates=None):
        navigate_to(current_appliance.server, 'Authentication')
        fill(self.form, updates if updates is not None else self, action=form_buttons.save)


class LDAPSAuthSetting(LDAPAuthSetting):
    """ Authentication via LDAPS

    Args:
        hosts: List of LDAPS servers (max 3).
        user_type: "userprincipalname", "mail", ...
        user_suffix: User suffix.
        base_dn: Base DN.
        bind_dn: Bind DN.
        bind_password: Bind Password.
        get_groups: Get user groups from LDAP.
        get_roles: Get roles from home forest.
        follow_referrals: Follow Referrals.
        port: LDAPS connection port.
        timeout_h: Timeout in hours
        timeout_m: Timeout in minutes

    Usage:

        ldapauth = LDAPSAuthSetting(
            ["host1", "host2"],
            "mail",
            "user.acme.com"
        )
        ldapauth.update()

    """
    AUTH_MODE = "LDAPS"


class Schedule(Pretty, Navigatable):
    """ Configure/Configuration/Region/Schedules functionality

    Create, Update, Delete functionality.

    Args:
        name: Schedule's name.
        description: Schedule description.
        active: Whether the schedule should be active (default `True`)
        action: Action type
        filter_type: Filtering type
        filter_value: If a more specific `filter_type` is selected, here is the place to choose
            hostnames, machines and so ...
        run_type: Once, Hourly, Daily, ...
        run_every: If `run_type` is not Once, then you can specify how often it should be run.
        time_zone: Time zone selection.
        start_date: Specify start date (mm/dd/yyyy or datetime.datetime()).
        start_hour: Starting hour
        start_min: Starting minute.

    Usage:

        schedule = Schedule(
            "My very schedule",
            "Some description here.",
            action="Datastore Analysis",
            filter_type="All Datastores for Host",
            filter_value="datastore.intra.acme.com",
            run_type="Hourly",
            run_every="2 Hours"
        )
        schedule.create()
        schedule.disable()
        schedule.enable()
        schedule.delete()
        # Or
        Schedule.enable_by_names("One schedule", "Other schedule")
        # And so.

    Note: TODO: Maybe the row handling might go into Table class?

    """
    tab = {"Hourly": "timer_hours",
           "Daily": "timer_days",
           "Weekly": "timer_weeks",
           "Monthly": "timer_months"}

    form = Form(fields=[
        ("name", Input("name")),
        ("description", Input("description")),
        ("active", Input("enabled")),
        ("action", {
            version.LOWEST: Select("select#action_typ"),
            '5.5': AngularSelect('action_typ')}),
        ("filter_type", {
            version.LOWEST: Select("select#filter_typ"),
            '5.5': AngularSelect('filter_typ')}),
        ("filter_value", {
            version.LOWEST: Select("select#filter_value"),
            '5.5': AngularSelect('filter_value')}),
        ("timer_type", {
            version.LOWEST: Select("select#timer_typ"),
            '5.5': AngularSelect('timer_typ')}),
        ("timer_hours", Select("select#timer_hours")),
        ("timer_days", Select("select#timer_days")),
        ("timer_weeks", Select("select#timer_weekss")),    # Not a typo!
        ("timer_months", Select("select#timer_months")),
        ("timer_value", AngularSelect('timer_value'), {"appeared_in": "5.5"}),
        ("time_zone", {
            version.LOWEST: Select("select#time_zone"),
            '5.5': AngularSelect('time_zone')}),
        ("start_date", Calendar("miq_angular_date_1")),
        ("start_hour", {
            version.LOWEST: Select("select#start_hour"),
            '5.5': AngularSelect('start_hour')}),
        ("start_min", {
            version.LOWEST: Select("select#start_min"),
            '5.5': AngularSelect('start_min')}),
    ])

    pretty_attrs = ['name', 'description', 'run_type', 'run_every',
                    'start_date', 'start_hour', 'start_min']

    def __init__(self, name, description, active=True, action=None, filter_type=None,
                 filter_value=None, run_type="Once", run_every=None, time_zone=None,
                 start_date=None, start_hour=None, start_min=None, appliance=None):
        Navigatable.__init__(self, appliance=appliance)
        self.details = dict(
            name=name,
            description=description,
            active=active,
            action=action,
            filter_type=filter_type,
            filter_value=filter_value,
            time_zone=sel.ByValue(time_zone),
            start_date=start_date,
            start_hour=start_hour,
            start_min=start_min,
        )

        if run_type == "Once":
            self.details["timer_type"] = "Once"
        else:
            field = version.pick({
                version.LOWEST: self.tab[run_type],
                '5.5': 'timer_value'})
            self.details["timer_type"] = run_type
            self.details[field] = run_every

    def create(self, cancel=False):
        """ Create a new schedule from the informations stored in the object.

        Args:
            cancel: Whether to click on the cancel button to interrupt the creation.
        """
        navigate_to(self, 'Add')

        if cancel:
            action = form_buttons.cancel
        else:
            action = form_buttons.add
        fill(
            self.form,
            self.details,
            action=action
        )

    def update(self, updates, cancel=False):
        """ Modify an existing schedule with informations from this instance.

        Args:
            updates: Dict with fields to be updated
            cancel: Whether to click on the cancel button to interrupt the editation.

        """
        navigate_to(self, 'Edit')

        if cancel:
            action = form_buttons.cancel
        else:
            action = form_buttons.save
        self.details.update(updates)
        fill(
            self.form,
            self.details,
            action=action
        )

    def delete(self, cancel=False):
        """ Delete the schedule represented by this object.

        Calls the class method with the name of the schedule taken out from the object.

        Args:
            cancel: Whether to click on the cancel button in the pop-up.
        """
        navigate_to(self, 'Details')
        tb.select("Configuration", "Delete this Schedule from the Database", invokes_alert=True)
        sel.handle_alert(cancel)

    def enable(self):
        """ Enable the schedule via table checkbox and Configuration menu.

        """
        self.select()
        tb.select("Configuration", "Enable the selected Schedules")

    def disable(self):
        """ Enable the schedule via table checkbox and Configuration menu.

        """
        self.select()
        tb.select("Configuration", "Disable the selected Schedules")

    def select(self):
        """ Select the checkbox for current schedule

        """
        navigate_to(self, 'All')
        for row in records_table.rows():
            if row.name.strip() == self.details['name']:
                checkbox = row[0].find_element_by_xpath("//input[@type='checkbox']")
                if not checkbox.is_selected():
                    sel.click(checkbox)
                break
        else:
            raise ScheduleNotFound(
                "Schedule '{}' could not be found for selection!".format(self.details['name'])
            )


@navigator.register(Schedule, 'All')
class ScheduleAll(CFMENavigateStep):
    prerequisite = NavigateToObject(Server, 'Configuration')

    def step(self):
        server_region = store.current_appliance.server_region_string()
        self.prerequisite_view.accordions.settings.tree.click_path(server_region, "Schedules")


@navigator.register(Schedule, 'Add')
class ScheduleAdd(CFMENavigateStep):
    prerequisite = NavigateToSibling('All')

    def step(self):
        tb.select("Configuration", "Add a new Schedule")


@navigator.register(Schedule, 'Details')
class ScheduleDetails(CFMENavigateStep):
    prerequisite = NavigateToSibling('All')

    def step(self):
        records_table.click_cell("name", self.obj.details["name"])


@navigator.register(Schedule, 'Edit')
class ScheduleEdit(CFMENavigateStep):
    prerequisite = NavigateToSibling('Details')

    def step(self):
        tb.select("Configuration", "Edit this Schedule")


class DatabaseBackupSchedule(Schedule):
    """ Configure/Configuration/Region/Schedules - Database Backup type

    Args:
        name: Schedule name
        description: Schedule description
        active: Whether the schedule should be active (default `True`)
        protocol: One of ``{'Samba', 'Network File System'}``
        run_type: Once, Hourly, Daily, ...
        run_every: If `run_type` is not Once, then you can specify how often it should be run
        time_zone: Time zone selection
        start_date: Specify start date (mm/dd/yyyy or datetime.datetime())
        start_hour: Starting hour
        start_min: Starting minute

    Usage:
        smb_schedule = DatabaseBackupSchedule(
            name="Bi-hourly Samba Database Backup",
            description="Everybody's favorite backup schedule",
            protocol="Samba",
            uri="samba.example.com/share_name",
            username="samba_user",
            password="secret",
            password_verify="secret",
            time_zone="UTC",
            start_date=datetime.datetime.utcnow(),
            run_type="Hourly",
            run_every="2 Hours"
        )
        smb_schedule.create()
        smb_schedule.delete()

        ... or ...

        nfs_schedule = DatabaseBackupSchedule(
            name="One-time NFS Database Backup",
            description="The other backup schedule",
            protocol="Network File System",
            uri="nfs.example.com/path/to/share",
            time_zone="Chihuahua",
            start_date="21/6/2014",
            start_hour="7",
            start_min="45"
        )
        nfs_schedule.create()
        nfs_schedule.delete()

    """
    form = Form(fields=[
        ("name", Input("name")),
        ("description", Input("description")),
        ("active", Input("enabled")),
        ("action", {
            version.LOWEST: Select("select#action_typ"),
            '5.5': AngularSelect('action_typ')}),
        ("log_protocol", {
            version.LOWEST: Select("select#log_protocol"),
            '5.5': AngularSelect('log_protocol')}),
        ("depot_name", Input("depot_name")),
        ("uri", Input("uri")),
        ("log_userid", Input("log_userid")),
        ("log_password", Input("log_password")),
        ("log_verify", Input("log_verify")),
        ("timer_type", {
            version.LOWEST: Select("select#timer_typ"),
            '5.5': AngularSelect('timer_typ')}),
        ("timer_hours", Select("select#timer_hours")),
        ("timer_days", Select("select#timer_days")),
        ("timer_weeks", Select("select#timer_weekss")),    # Not a typo!
        ("timer_months", Select("select#timer_months")),
        ("timer_value", AngularSelect('timer_value'), {"appeared_in": "5.5"}),
        ("time_zone", {
            version.LOWEST: Select("select#time_zone"),
            '5.5': AngularSelect('time_zone')}),
        ("start_date", {
            '5.4': Calendar("miq_angular_date_1"),
            '5.5': Calendar("start_date")}),
        ("start_hour", {
            version.LOWEST: Select("select#start_hour"),
            '5.5': AngularSelect('start_hour')}),
        ("start_min", {
            version.LOWEST: Select("select#start_min"),
            '5.5': AngularSelect('start_min')}),
    ])

    def __init__(self, name, description, active=True, protocol=None, depot_name=None, uri=None,
                 username=None, password=None, password_verify=None, run_type="Once",
                 run_every=None, time_zone=None, start_date=None, start_hour=None, start_min=None):

        assert protocol in {'Samba', 'Network File System'},\
            "Unknown protocol type '{}'".format(protocol)

        if protocol == 'Samba':
            self.details = dict(
                name=name,
                description=description,
                active=active,
                action='Database Backup',
                log_protocol=sel.ByValue(protocol),
                depot_name=depot_name,
                uri=uri,
                log_userid=username,
                log_password=password,
                log_verify=password_verify,
                time_zone=sel.ByValue(time_zone),
                start_date=start_date,
                start_hour=start_hour,
                start_min=start_min,
            )
        else:
            self.details = dict(
                name=name,
                description=description,
                active=active,
                action='Database Backup',
                log_protocol=sel.ByValue(protocol),
                depot_name=depot_name,
                uri=uri,
                time_zone=sel.ByValue(time_zone),
                start_date=start_date,
                start_hour=start_hour,
                start_min=start_min,
            )

        if run_type == "Once":
            self.details["timer_type"] = "Once"
        else:
            field = version.pick({
                version.LOWEST: self.tab[run_type],
                '5.5': 'timer_value'})
            self.details["timer_type"] = run_type
            self.details[field] = run_every

    def create(self, cancel=False, samba_validate=False):
        """ Create a new schedule from the informations stored in the object.

        Args:
            cancel: Whether to click on the cancel button to interrupt the creation.
            samba_validate: Samba-only option to click the `Validate` button to check
                            if entered samba credentials are valid or not
        """
        navigate_to(self, 'Add')

        fill(self.form, self.details)
        if samba_validate:
            sel.click(form_buttons.validate)
        if cancel:
            form_buttons.cancel()
        else:
            form_buttons.add()

    def update(self, updates, cancel=False, samba_validate=False):
        """ Modify an existing schedule with informations from this instance.

        Args:
            updates: Dict with fields to be updated
            cancel: Whether to click on the cancel button to interrupt the editation.
            samba_validate: Samba-only option to click the `Validate` button to check
                            if entered samba credentials are valid or not
        """
        navigate_to(self, 'Edit')

        self.details.update(updates)
        fill(self.form, self.details)
        if samba_validate:
            sel.click(form_buttons.validate)
        if cancel:
            form_buttons.cancel()
        else:
            form_buttons.save()

    @property
    def last_date(self):
        navigate_to(self, 'All')
        name = self.details["name"]
        row = records_table.find_row("Name", name)
        return row[6].text


class Category(Pretty, Navigatable):
    pretty_attrs = ['name', 'display_name', 'description', 'show_in_console',
                    'single_value', 'capture_candu']

    def __init__(self, name=None, display_name=None, description=None, show_in_console=True,
                 single_value=True, capture_candu=False, appliance=None):
        Navigatable.__init__(self, appliance=appliance)
        self.name = name
        self.display_name = display_name
        self.description = description
        self.show_in_console = show_in_console
        self.single_value = single_value
        self.capture_candu = capture_candu

    def _form_mapping(self, create=None, **kwargs):
        return {
            'name': kwargs.get('name'),
            'display_name': kwargs.get('display_name'),
            'description': kwargs.get('description'),
            'show_in_console': kwargs.get('show_in_console'),
            'single_value': kwargs.get('single_value'),
            'capture_candu': kwargs.get('capture_candu'),
        }

    def create(self, cancel=False):
        navigate_to(self, 'Add')
        fill(category_form, self._form_mapping(True, **self.__dict__))
        if cancel:
            form_buttons.cancel()
        else:
            form_buttons.add()
            flash.assert_success_message('Category "{}" was added'.format(self.display_name))

    def update(self, updates, cancel=False):
        navigate_to(self, 'Edit')
        fill(category_form, self._form_mapping(**updates))
        if cancel:
            form_buttons.cancel()
        else:
            form_buttons.save()
            flash.assert_success_message('Category "{}" was saved'.format(self.name))

    def delete(self, cancel=True):
        """
        """
        if not cancel:
            navigate_to(self, 'All')
            row = category_table.find_row_by_cells({'name': self.name})
            del_btn_fn = version.pick({
                version.LOWEST: lambda: row[0],
                '5.6': lambda: row.actions
            })
            sel.click(del_btn_fn(), wait_ajax=False)
            sel.handle_alert()
            flash.assert_success_message('Category "{}": Delete successful'.format(self.name))


@navigator.register(Category, 'All')
class CategoryAll(CFMENavigateStep):
    prerequisite = NavigateToAttribute('appliance.server.zone.region', 'Details')

    def step(self):
        tabs.select_tab("My Company Categories")


@navigator.register(Category, 'Add')
class CategoryAdd(CFMENavigateStep):
    """Unlike most other Add operations, this one requires an instance"""
    prerequisite = NavigateToSibling('All')

    def step(self):
        sel.click(category_form.new_tr)


@navigator.register(Category, 'Edit')
class CategoryEdit(CFMENavigateStep):
    prerequisite = NavigateToSibling('All')

    def step(self):
        category_table.click_cell("name", self.obj.name)


class Tag(Pretty, Navigatable):
    pretty_attrs = ['name', 'display_name', 'category']

    def __init__(self, name=None, display_name=None, category=None, appliance=None):
        Navigatable.__init__(self, appliance=appliance)
        self.name = name
        self.display_name = display_name
        self.category = category

    def _form_mapping(self, create=None, **kwargs):
        return {
            'name': kwargs.get('name'),
            'display_name': kwargs.get('display_name'),
        }

    def create(self):
        navigate_to(self, 'Add')
        sel.click(tag_form.new)
        fill(tag_form, self._form_mapping(True, **self.__dict__), action=tag_form.add)

    def update(self, updates):
        navigate_to(self, 'Edit')
        update_action = version.pick({
            version.LOWEST: tag_form.add,
            '5.6': tag_form.save
        })
        fill(tag_form, self._form_mapping(**updates), action=update_action)

    def delete(self, cancel=True):
        """
        """
        if not cancel:
            navigate_to(self, 'All')
            fill(tag_form, {'category': self.category.display_name})
            row = classification_table.find_row_by_cells({'name': self.name})
            del_btn_fn = version.pick({
                version.LOWEST: lambda: row[0],
                '5.6': lambda: row.actions
            })
            sel.click(del_btn_fn(), wait_ajax=False)
            sel.handle_alert()


@navigator.register(Tag, 'All')
class TagsAll(CFMENavigateStep):
    prerequisite = NavigateToAttribute('appliance.server.zone.region', 'Details')

    def step(self):
        tabs.select_tab("My Company Tags")


@navigator.register(Tag, 'Add')
class TagsAdd(CFMENavigateStep):
    """Unlike most other Add operations, this one requires an instance"""
    prerequisite = NavigateToSibling('All')

    def step(self):
        fill(tag_form, {'category': self.obj.category.display_name})
        sel.click(tag_form.new)


@navigator.register(Tag, 'Edit')
class TagsEdit(CFMENavigateStep):
    prerequisite = NavigateToSibling('All')

    def step(self):
        fill(tag_form, {'category': self.obj.category.display_name})
        classification_table.click_cell('name', self.obj.name)


def set_server_roles(db=True, **roles):
    """ Set server roles on Configure / Configuration pages.

    Args:
        **roles: Roles specified as in server_roles Form in this module. Set to True or False
    """
    if get_server_roles() == roles:
        logger.debug(' Roles already match, returning...')
        return
    if db:
        store.current_appliance.server_roles = roles
    else:
        navigate_to(current_appliance.server, 'Server')
        fill(server_roles, roles, action=form_buttons.save)


def get_server_roles(navigate=True, db=True):
    """ Get server roles from Configure / Configuration

    Returns: :py:class:`dict` with the roles in the same format as :py:func:`set_server_roles`
        accepts as kwargs.
    """
    if db:
        return store.current_appliance.server_roles
    else:
        if navigate:
            navigate_to(current_appliance.server, 'Server')

        role_list = {}
        for (name, locator) in server_roles.fields:
            try:
                role_list[name] = locator.is_selected()
            except:
                logger.warning("role not found, skipping, netapp storage role?  (%s)", name)
        return role_list


@contextmanager
def _server_roles_cm(enable, *roles):
    """ Context manager that takes care of setting required roles and then restoring original roles.

    Args:
        enable: Whether to enable the roles.
        *roles: Role ids to set
    """
    try:
        original_roles = get_server_roles()
        set_roles = dict(original_roles)
        for role in roles:
            if role not in set_roles:
                raise NameError("No such role {}".format(role))
            set_roles[role] = enable
        set_server_roles(**set_roles)
        yield
    finally:
        set_server_roles(**original_roles)


def server_roles_enabled(*roles):
    return _server_roles_cm(True, *roles)


def server_roles_disabled(*roles):
    return _server_roles_cm(False, *roles)


def set_ntp_servers(*servers):
    """ Set NTP servers on Configure / Configuration pages.

    Args:
        *servers: Maximum of 3 hostnames.
    """
    server_value = ["", "", ""]
    navigate_to(current_appliance.server, 'Server')
    assert len(servers) <= 3, "There is place only for 3 servers!"
    for enum, server in enumerate(servers):
        server_value[enum] = server
    fields = {}
    for enum, server in enumerate(server_value):
        fields["ntp_server_%d" % (enum + 1)] = server
    fill(ntp_servers, fields, action=form_buttons.save)
    if servers:
        flash.assert_message_match(
            "Configuration settings saved for {} Server \"{} [{}]\" in Zone \"{}\"".format(
                store.current_appliance.product_name,
                store.current_appliance.server_name(),
                store.current_appliance.server_id(),
                store.current_appliance.zone_description.partition(' ')[0].lower()))


def get_ntp_servers():
    navigate_to(current_appliance.server, 'Server')
    servers = set([])
    for i in range(3):
        value = sel.value("#ntp_server_{}".format(i + 1)).encode("utf-8").strip()
        if value:
            servers.add(value)
    return servers


def restart_workers(name, wait_time_min=1):
    """ Restarts workers by their name.

    Args:
        name: Name of the worker. Multiple workers can have the same name. Name is matched with `in`
    Returns: bool whether the restart succeeded.
    """

    navigate_to(current_appliance.server, 'DiagnosticsWorkers')

    def get_all_pids(worker_name):
        return {row.pid.text for row in records_table.rows() if worker_name in row.name.text}

    reload_func = partial(tb.select, "Reload current workers display")

    pids = get_all_pids(name)
    # Initiate the restart
    for pid in pids:
        records_table.click_cell("pid", pid)
        tb.select("Configuration", "Restart selected worker", invokes_alert=True)
        sel.handle_alert(cancel=False)
        reload_func()

    # Check they have finished
    def _check_all_workers_finished():
        for pid in pids:
            if records_table.click_cell("pid", pid):    # If could not click, no longer present
                return False                    # If clicked, it is still there so unsuccess
        return True

    # Wait for all original workers to be gone
    try:
        wait_for(
            _check_all_workers_finished,
            fail_func=reload_func,
            num_sec=wait_time_min * 60
        )
    except TimedOutError:
        return False

    # And now check whether the same number of workers is back online
    try:
        wait_for(
            lambda: len(pids) == len(get_all_pids(name)),
            fail_func=reload_func,
            num_sec=wait_time_min * 60,
            message="wait_workers_back_online"
        )
        return True
    except TimedOutError:
        return False


def get_workers_list(do_not_navigate=False, refresh=True):
    """Retrieves all workers.

    Returns a dictionary where keys are names of the workers and values are lists (because worker
    can have multiple instances) which contain dictionaries with some columns.
    """
    if do_not_navigate:
        if refresh:
            tb.select("Reload current workers display")
    else:
        navigate_to(current_appliance.server, 'Workers')
    workers = {}
    for row in records_table.rows():
        name = sel.text_sane(row.name)
        if name not in workers:
            workers[name] = []
        worker = {
            "status": sel.text_sane(row.status),
            "pid": int(sel.text_sane(row.pid)) if len(sel.text_sane(row.pid)) > 0 else None,
            "spid": int(sel.text_sane(row.spid)) if len(sel.text_sane(row.spid)) > 0 else None,
            "started": parsetime.from_american_with_utc(sel.text_sane(row.started)),

            "last_heartbeat": None,
        }
        try:
            workers["last_heartbeat"] = parsetime.from_american_with_utc(
                sel.text_sane(row.last_heartbeat))
        except ValueError:
            pass
        workers[name].append(worker)
    return workers


def setup_authmode_database():
    set_auth_mode(mode='database')


def set_auth_mode(mode, **kwargs):
    """ Set up authentication mode

    Args:
        mode: Authentication mode to set up.
        kwargs: A dict of keyword arguments used to initialize one of
                the \*AuthSetting classes - class type is mode-dependent.
    Raises:
        AuthModeUnknown: when the given mode is not valid
    """
    if mode == 'ldap':
        auth_pg = LDAPAuthSetting(**kwargs)
    elif mode == 'ldaps':
        auth_pg = LDAPSAuthSetting(**kwargs)
    elif mode == 'amazon':
        auth_pg = AmazonAuthSetting(**kwargs)
    elif mode == 'database':
        auth_pg = DatabaseAuthSetting(**kwargs)
    else:
        raise AuthModeUnknown("{} is not a valid authentication mode".format(mode))
    auth_pg.update()


def set_replication_worker_host(host, port='5432'):
    """ Set replication worker host on Configure / Configuration pages.

    Args:
        host: Address of the hostname to replicate to.
    """
    navigate_to(current_appliance.server, 'Workers')
    change_stored_password()
    fill(
        replication_worker,
        dict(host=host,
             port=port,
             username=conf.credentials['database']['username'],
             password=conf.credentials['database']['password'],
             password_verify=conf.credentials['database']['password']),
        action=form_buttons.save
    )


def get_replication_status(navigate=True):
    """ Gets replication status from Configure / Configuration pages.

    Returns: bool of whether replication is Active or Inactive.
    """
    if navigate:

        navigate_to(Region, 'Replication')
    return replication_process.status.text == "Active"


def get_replication_backlog(navigate=True):
    """ Gets replication backlog from Configure / Configuration pages.

    Returns: int representing the remaining items in the replication backlog.
    """
    if navigate:
        navigate_to(Region, 'Replication')
    return int(replication_process.current_backlog.text)
