# Copyright 2010 OpenStack Foundation
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

import webob

from nova.api.openstack import api_version_request
from nova.api.openstack import common
from nova.api.openstack.compute.schemas import flavors_extraspecs as schema
from nova.api.openstack import wsgi
from nova.api import validation
from nova.api.validation.extra_specs import validators
from nova import exception
from nova.i18n import _
from nova.policies import flavor_extra_specs as fes_policies
from nova import utils


@validation.validated
class FlavorExtraSpecsController(wsgi.Controller):
    """The flavor extra specs API controller for the OpenStack API."""

    def _get_extra_specs(self, context, flavor_id):
        flavor = common.get_flavor(context, flavor_id)
        return dict(extra_specs=flavor.extra_specs)

    def _check_extra_specs_value(self, req, specs):
        validation_supported = api_version_request.is_supported(req, '2.86')

        for name, value in specs.items():
            # NOTE(gmann): Max length for numeric value is being checked
            # explicitly as json schema cannot have max length check for
            # numeric value
            if isinstance(value, (int, float)):
                value = str(value)
                try:
                    utils.check_string_length(value, 'extra_specs value',
                                              max_length=255)
                except exception.InvalidInput as error:
                    raise webob.exc.HTTPBadRequest(
                              explanation=error.format_message())

            if validation_supported:
                validators.validate(name, value)

    @wsgi.expected_errors(404)
    @validation.query_schema(schema.index_query)
    @validation.response_body_schema(schema.index_response)
    def index(self, req, flavor_id):
        """Returns the list of extra specs for a given flavor."""
        context = req.environ['nova.context']
        context.can(fes_policies.POLICY_ROOT % 'index',
                    target={'project_id': context.project_id})
        return self._get_extra_specs(context, flavor_id)

    # NOTE(gmann): Here should be 201 instead of 200 by v2.1
    # +microversions because the flavor extra specs has been created
    # completely when returning a response.
    @wsgi.expected_errors((400, 404, 409))
    @validation.schema(schema.create)
    @validation.response_body_schema(schema.create_response)
    def create(self, req, flavor_id, body):
        context = req.environ['nova.context']
        context.can(fes_policies.POLICY_ROOT % 'create', target={})

        specs = body['extra_specs']
        self._check_extra_specs_value(req, specs)
        flavor = common.get_flavor(context, flavor_id)
        try:
            flavor.extra_specs = dict(flavor.extra_specs, **specs)
            flavor.save()
        except exception.FlavorExtraSpecUpdateCreateFailed as e:
            raise webob.exc.HTTPConflict(explanation=e.format_message())
        except exception.FlavorNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())
        return body

    @wsgi.expected_errors((400, 404, 409))
    @validation.schema(schema.update)
    @validation.response_body_schema(schema.update_response)
    def update(self, req, flavor_id, id, body):
        context = req.environ['nova.context']
        context.can(fes_policies.POLICY_ROOT % 'update', target={})

        self._check_extra_specs_value(req, body)
        if id not in body:
            expl = _('Request body and URI mismatch')
            raise webob.exc.HTTPBadRequest(explanation=expl)
        flavor = common.get_flavor(context, flavor_id)
        try:
            flavor.extra_specs = dict(flavor.extra_specs, **body)
            flavor.save()
        except exception.FlavorExtraSpecUpdateCreateFailed as e:
            raise webob.exc.HTTPConflict(explanation=e.format_message())
        except exception.FlavorNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())
        return body

    @wsgi.expected_errors(404)
    @validation.query_schema(schema.show_query)
    @validation.response_body_schema(schema.show_response)
    def show(self, req, flavor_id, id):
        """Return a single extra spec item."""
        context = req.environ['nova.context']
        context.can(fes_policies.POLICY_ROOT % 'show',
                    target={'project_id': context.project_id})
        flavor = common.get_flavor(context, flavor_id)
        try:
            return {id: flavor.extra_specs[id]}
        except KeyError:
            msg = _("Flavor %(flavor_id)s has no extra specs with "
                    "key %(key)s.") % dict(flavor_id=flavor_id,
                                           key=id)
            raise webob.exc.HTTPNotFound(explanation=msg)

    # NOTE(gmann): Here should be 204(No Content) instead of 200 by v2.1
    # +microversions because the flavor extra specs has been deleted
    # completely when returning a response.
    @wsgi.expected_errors(404)
    @validation.response_body_schema(schema.delete_response)
    def delete(self, req, flavor_id, id):
        """Deletes an existing extra spec."""
        context = req.environ['nova.context']
        context.can(fes_policies.POLICY_ROOT % 'delete', target={})
        flavor = common.get_flavor(context, flavor_id)
        try:
            del flavor.extra_specs[id]
            flavor.save()
        except (exception.FlavorExtraSpecsNotFound,
                exception.FlavorNotFound) as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())
        except KeyError:
            msg = _("Flavor %(flavor_id)s has no extra specs with "
                    "key %(key)s.") % dict(flavor_id=flavor_id,
                                           key=id)
            raise webob.exc.HTTPNotFound(explanation=msg)
