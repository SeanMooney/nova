# Copyright 2011 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""The multinic extension."""

from webob import exc

from nova.api.openstack import common
from nova.api.openstack.compute.schemas import multinic as schema
from nova.api.openstack import wsgi
from nova.api import validation
from nova.compute import api as compute
from nova import exception
from nova.policies import multinic as multinic_policies


@validation.validated
class MultinicController(wsgi.Controller):
    """This API is deprecated from Microversion '2.44'."""

    def __init__(self):
        super(MultinicController, self).__init__()
        self.compute_api = compute.API()

    @wsgi.api_version("2.1", "2.43")
    @wsgi.response(202)
    @wsgi.action('addFixedIp')
    @wsgi.expected_errors((400, 404))
    @validation.schema(schema.add_fixed_ip)
    @validation.response_body_schema(schema.add_fixed_ip_response)
    def _add_fixed_ip(self, req, id, body):
        """Adds an IP on a given network to an instance."""
        context = req.environ['nova.context']
        instance = common.get_instance(self.compute_api, context, id)
        context.can(multinic_policies.BASE_POLICY_NAME % 'add',
                    target={'project_id': instance.project_id})

        network_id = body['addFixedIp']['networkId']
        try:
            self.compute_api.add_fixed_ip(context, instance, network_id)
        except exception.NoMoreFixedIps as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())

    @wsgi.api_version("2.1", "2.43")
    @wsgi.response(202)
    @wsgi.action('removeFixedIp')
    @wsgi.expected_errors((400, 404))
    @validation.schema(schema.remove_fixed_ip)
    @validation.response_body_schema(schema.remove_fixed_ip_response)
    def _remove_fixed_ip(self, req, id, body):
        """Removes an IP from an instance."""
        context = req.environ['nova.context']
        instance = common.get_instance(self.compute_api, context, id)
        context.can(multinic_policies.BASE_POLICY_NAME % 'remove',
                    target={'project_id': instance.project_id})

        address = body['removeFixedIp']['address']

        try:
            self.compute_api.remove_fixed_ip(context, instance, address)
        except exception.FixedIpNotFoundForInstance as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())
