import time
import logging

import e2e_tests.test_base as tb
import e2e_tests.dedicated_admin_test_base as dat


def run():
    oc_map = tb.get_oc_map()

    ns_to_create = tb.get_test_namespace_name()
    expected_rolebindings = dat.get_expected_rolebindings()

    for cluster, oc in oc_map.items():
        logging.info("[{}] Creating namespace '{}'".format(
            cluster, ns_to_create
        ))

        try:
            oc.new_project(ns_to_create)
            time.sleep(2) #  allow time for RoleBindings to be created
            for expected_rb in expected_rolebindings:
                rb = oc.get(ns_to_create, 'RoleBinding', expected_rb['name'])
                tb.assert_rolebinding(expected_rb, rb)
        finally:
            logging.info("[{}] Deleting namespace '{}'".format(
                cluster, ns_to_create
            ))
            oc.delete_project(ns_to_create)
