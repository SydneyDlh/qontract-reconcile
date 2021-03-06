import toml
import requests
import logging

import utils.vault_client as vault_client


class JenkinsApi(object):
    """Wrapper around Jenkins API calls"""

    def __init__(self, token, ssl_verify=True):
        token_path = token['path']
        token_field = token['field']
        token_config = vault_client.read(token_path, token_field)
        config = toml.loads(token_config)

        self.url = config['jenkins']['url']
        self.user = config['jenkins']['user']
        self.password = config['jenkins']['password']
        self.ssl_verify = ssl_verify
        self.should_restart = False

    def get_all_roles(self):
        url = "{}/role-strategy/strategy/getAllRoles".format(self.url)
        res = requests.get(
            url,
            verify=self.ssl_verify,
            auth=(self.user, self.password)
        )

        res.raise_for_status()
        return res.json()

    def assign_role_to_user(self, role, user):
        url = "{}/role-strategy/strategy/assignRole".format(self.url)
        data = {
            'type': 'globalRoles',
            'roleName': role,
            'sid': user
        }
        res = requests.post(
            url,
            verify=self.ssl_verify,
            data=data,
            auth=(self.user, self.password)
        )

        res.raise_for_status()

    def unassign_role_from_user(self, role, user):
        url = "{}/role-strategy/strategy/unassignRole".format(self.url)
        data = {
            'type': 'globalRoles',
            'roleName': role,
            'sid': user
        }
        res = requests.post(
            url,
            verify=self.ssl_verify,
            data=data,
            auth=(self.user, self.password)
        )

        res.raise_for_status()

    def list_plugins(self):
        url = "{}/pluginManager/api/json?depth=1".format(self.url)

        res = requests.get(
            url,
            verify=self.ssl_verify,
            auth=(self.user, self.password)
        )

        res.raise_for_status()
        return res.json()['plugins']

    def install_plugin(self, name):
        self.should_restart = True
        header = {"Content-Type": "text/xml"}
        url = "{}/pluginManager/installNecessaryPlugins".format(self.url)
        data = \
            '<jenkins><install plugin="{}@current" /></jenkins>'.format(name)
        res = requests.post(
            url,
            verify=self.ssl_verify,
            data=data,
            headers=header,
            auth=(self.user, self.password)
        )

        res.raise_for_status()

    def safe_restart(self, force_restart=False):
        url = "{}/safeRestart".format(self.url)
        if self.should_restart or force_restart:
            logging.debug('performing safe restart. ' +
                          'should_restart={}, ' +
                          'force_restart={}.'.format(self.should_restart,
                                                     force_restart))
            res = requests.post(
                url,
                verify=self.ssl_verify,
                auth=(self.user, self.password)
            )

            res.raise_for_status()
