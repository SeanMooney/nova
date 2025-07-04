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

from webob import exc

from nova.api.openstack import common
from nova.api.openstack.compute.schemas import ips as schema
from nova.api.openstack.compute.views import ips as views
from nova.api.openstack import wsgi
from nova.api import validation
from nova.compute import api as compute
from nova.i18n import _
from nova.policies import ips as ips_policies


@validation.validated
class IPsController(wsgi.Controller):
    """The servers addresses API controller for the OpenStack API."""
    _view_builder_class = views.ViewBuilder

    def __init__(self):
        super(IPsController, self).__init__()
        self._compute_api = compute.API()

    @wsgi.expected_errors(404)
    @validation.query_schema(schema.index_query)
    @validation.response_body_schema(schema.index_response)
    def index(self, req, server_id):
        context = req.environ["nova.context"]
        instance = common.get_instance(self._compute_api, context, server_id)
        context.can(ips_policies.POLICY_ROOT % 'index',
                    target={'project_id': instance.project_id})
        networks = common.get_networks_for_instance(context, instance)
        return self._view_builder.index(req, networks)

    @wsgi.expected_errors(404)
    @validation.query_schema(schema.show_query)
    @validation.response_body_schema(schema.show_response)
    def show(self, req, server_id, id):
        context = req.environ["nova.context"]
        instance = common.get_instance(self._compute_api, context, server_id)
        context.can(ips_policies.POLICY_ROOT % 'show',
                    target={'project_id': instance.project_id})
        networks = common.get_networks_for_instance(context, instance)
        if id not in networks:
            msg = _("Instance is not a member of specified network")
            raise exc.HTTPNotFound(explanation=msg)

        return self._view_builder.show(req, networks[id], id)
