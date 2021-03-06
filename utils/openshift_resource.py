import copy
import hashlib
import json
import semver
import datetime

from threading import Lock


class ResourceKeyExistsError(Exception):
    pass


class OpenshiftResource(object):
    def __init__(self, body, integration, integration_version):
        self.body = body
        self.integration = integration
        self.integration_version = integration_version

    @property
    def name(self):
        return self.body['metadata']['name']

    @property
    def kind(self):
        return self.body['kind']

    def verify_valid_k8s_object(self):
        self.name
        self.kind

    def has_qontract_annotations(self):
        try:
            annotations = self.body['metadata']['annotations']

            assert annotations['qontract.integration'] == self.integration

            integration_version = annotations['qontract.integration_version']
            assert semver.parse(integration_version)['major'] == \
                semver.parse(self.integration_version)['major']

            assert annotations['qontract.sha256sum'] is not None
        except KeyError:
            return False
        except AssertionError:
            return False
        except ValueError:
            # raised by semver.parse
            return False

        return True

    def has_valid_sha256sum(self):
        try:
            current_sha256sum = \
                self.body['metadata']['annotations']['qontract.sha256sum']
            return current_sha256sum == self.sha256sum()
        except KeyError:
            return False

    def annotate(self):
        """
        Creates a OpenshiftResource with the qontract annotations, and removes
        unneeded Openshift fields.

        Returns:
            openshift_resource: new OpenshiftResource object with
                annotations.
        """

        # calculate sha256sum of canonical body
        canonical_body = self.canonicalize(self.body)
        sha256sum = self.calculate_sha256sum(self.serialize(canonical_body))

        # create new body object
        body = copy.deepcopy(self.body)

        # create annotations if not present
        body['metadata'].setdefault('annotations', {})
        annotations = body['metadata']['annotations']

        # add qontract annotations
        annotations['qontract.integration'] = self.integration
        annotations['qontract.integration_version'] = \
            self.integration_version
        annotations['qontract.sha256sum'] = sha256sum
        now = datetime.datetime.utcnow().replace(microsecond=0).isoformat()
        annotations['qontract.update'] = now

        return OpenshiftResource(body, self.integration,
                                 self.integration_version)

    def sha256sum(self):
        body = self.annotate().body

        annotations = body['metadata']['annotations']
        return annotations['qontract.sha256sum']

    def toJSON(self):
        return self.serialize(self.body)

    @staticmethod
    def canonicalize(body):
        body = copy.deepcopy(body)

        # create annotations if not present
        body['metadata'].setdefault('annotations', {})
        annotations = body['metadata']['annotations']

        # remove openshift specific params
        body['metadata'].pop('creationTimestamp', None)
        body['metadata'].pop('resourceVersion', None)
        body['metadata'].pop('generation', None)
        body['metadata'].pop('selfLink', None)
        body['metadata'].pop('uid', None)
        body['metadata'].pop('namespace', None)
        annotations.pop('kubectl.kubernetes.io/last-applied-configuration',
                        None)

        # remove status
        body.pop('status', None)

        # Default fields for specific resource types
        # ConfigMaps and Secrets are by default Opaque
        if body['kind'] in ('ConfigMap', 'Secret') and \
                body.get('type') == 'Opaque':
            body.pop('type')

        if body['kind'] == 'Route':
            if body['spec'].get('wildcardPolicy') == 'None':
                body['spec'].pop('wildcardPolicy')
            # remove tls-acme specific params from Route
            if 'kubernetes.io/tls-acme' in annotations:
                annotations.pop(
                    'kubernetes.io/tls-acme-awaiting-authorization-owner',
                    None)
                annotations.pop(
                    'kubernetes.io/tls-acme-awaiting-authorization-at-url',
                    None)
                if 'tls' in body['spec']:
                    tls = body['spec']['tls']
                    tls.pop('key', None)
                    tls.pop('certificate', None)

        if body['kind'] == 'ServiceAccount':
            if 'imagePullSecrets' in body:
                body.pop('imagePullSecrets')
            if 'secrets' in body:
                body.pop('secrets')

        if body['kind'] == 'Role':
            for rule in body['rules']:
                if 'attributeRestrictions' in rule and \
                        not rule['attributeRestrictions']:
                    rule.pop('attributeRestrictions')

        if body['kind'] == 'RoleBinding':
            if 'groupNames' in body:
                body.pop('groupNames')
            if 'userNames' in body:
                body.pop('userNames')
            if 'roleRef' in body:
                roleRef = body['roleRef']
                if 'namespace' in roleRef:
                    roleRef.pop('namespace')
                if 'apiGroup' in roleRef and \
                        roleRef['apiGroup'] == body['apiVersion']:
                    roleRef.pop('apiGroup')
                if 'kind' in roleRef and \
                        roleRef['kind'] == 'Role':
                    roleRef.pop('kind')
            for subject in body['subjects']:
                if 'namespace' in subject:
                    subject.pop('namespace')
                if 'apiGroup' in subject and \
                        subject['apiGroup'] == '':
                    subject.pop('apiGroup')

        # remove qontract specific params
        annotations.pop('qontract.integration', None)
        annotations.pop('qontract.integration_version', None)
        annotations.pop('qontract.sha256sum', None)
        annotations.pop('qontract.update', None)

        return body

    @staticmethod
    def serialize(body):
        return json.dumps(body, sort_keys=True)

    @staticmethod
    def calculate_sha256sum(body):
        m = hashlib.sha256()
        m.update(body.encode('utf-8'))
        return m.hexdigest()


class ResourceInventory(object):
    def __init__(self):
        self._clusters = {}
        self._error_registered = False
        self._lock = Lock()

    def initialize_resource_type(self, cluster, namespace, resource_type):
        self._clusters.setdefault(cluster, {})
        self._clusters[cluster].setdefault(namespace, {})
        self._clusters[cluster][namespace].setdefault(resource_type, {
            'current': {},
            'desired': {}
        })

    def add_desired(self, cluster, namespace, resource_type, name, value):
        with self._lock:
            desired = \
                self._clusters[cluster][namespace][resource_type]['desired']
            if name in desired:
                raise ResourceKeyExistsError(name)
            desired[name] = value

    def add_current(self, cluster, namespace, resource_type, name, value):
        with self._lock:
            current = \
                self._clusters[cluster][namespace][resource_type]['current']
            current[name] = value

    def __iter__(self):
        for cluster in self._clusters.keys():
            for namespace in self._clusters[cluster].keys():
                for resource_type in self._clusters[cluster][namespace].keys():
                    data = self._clusters[cluster][namespace][resource_type]
                    yield (cluster, namespace, resource_type, data)

    def register_error(self):
        self._error_registered = True

    def has_error_registered(self):
        return self._error_registered
