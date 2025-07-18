# Copyright 2011 OpenStack Foundation
# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
# Copyright 2011 Grid Dynamics
# Copyright 2011 Eldar Nugaev, Kirill Shileev, Ilya Alekseyev
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

from oslo_log import log as logging
from oslo_utils import netutils
import webob

from nova.api.openstack.api_version_request \
    import MAX_PROXY_API_SUPPORT_VERSION
from nova.api.openstack import common
from nova.api.openstack.compute.schemas import floating_ips as schema
from nova.api.openstack import wsgi
from nova.api import validation
from nova.compute import api as compute
from nova import exception
from nova.i18n import _
from nova.network import neutron
from nova.policies import floating_ips as fi_policies


LOG = logging.getLogger(__name__)


def _translate_floating_ip_view(floating_ip):
    instance_id = None
    if floating_ip['port_details']:
        instance_id = floating_ip['port_details']['device_id']

    return {
        'floating_ip': {
            'id': floating_ip['id'],
            'ip': floating_ip['floating_ip_address'],
            'pool': floating_ip['network_details']['name'] or (
                floating_ip['network_details']['id']),
            'fixed_ip': floating_ip['fixed_ip_address'],
            'instance_id': instance_id,
        }
    }


def get_instance_by_floating_ip_addr(self, context, address):
    try:
        instance_id =\
            self.network_api.get_instance_id_by_floating_address(
                context, address)
    except exception.FloatingIpNotFoundForAddress as ex:
        raise webob.exc.HTTPNotFound(explanation=ex.format_message())
    except exception.FloatingIpMultipleFoundForAddress as ex:
        raise webob.exc.HTTPConflict(explanation=ex.format_message())

    if instance_id:
        return common.get_instance(self.compute_api, context, instance_id,
                                   expected_attrs=['flavor'])


def disassociate_floating_ip(self, context, instance, address):
    try:
        self.network_api.disassociate_floating_ip(context, instance, address)
    except exception.Forbidden:
        raise webob.exc.HTTPForbidden()


class FloatingIPController(wsgi.Controller):
    """The Floating IPs API controller for the OpenStack API."""

    def __init__(self):
        super(FloatingIPController, self).__init__()
        self.compute_api = compute.API()
        self.network_api = neutron.API()

    @wsgi.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors((400, 404))
    @validation.query_schema(schema.show_query)
    def show(self, req, id):
        """Return data about the given floating IP."""
        context = req.environ['nova.context']
        context.can(fi_policies.BASE_POLICY_NAME % 'show',
                    target={'project_id': context.project_id})

        try:
            floating_ip = self.network_api.get_floating_ip(context, id)
        except (exception.NotFound, exception.FloatingIpNotFound):
            msg = _("Floating IP not found for ID %s") % id
            raise webob.exc.HTTPNotFound(explanation=msg)
        except exception.InvalidID as e:
            raise webob.exc.HTTPBadRequest(explanation=e.format_message())

        return _translate_floating_ip_view(floating_ip)

    @wsgi.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors(())
    @validation.query_schema(schema.index_query)
    def index(self, req):
        """Return a list of floating IPs allocated to a project."""
        context = req.environ['nova.context']
        context.can(fi_policies.BASE_POLICY_NAME % 'list',
                    target={'project_id': context.project_id})

        floating_ips = self.network_api.get_floating_ips_by_project(context)

        return {'floating_ips': [_translate_floating_ip_view(ip)['floating_ip']
                                 for ip in floating_ips]}

    @wsgi.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors((400, 403, 404))
    @validation.schema(schema.create)
    def create(self, req, body=None):
        context = req.environ['nova.context']
        context.can(fi_policies.BASE_POLICY_NAME % 'create',
                    target={'project_id': context.project_id})

        pool = None
        if body and 'pool' in body:
            pool = body['pool']
        try:
            address = self.network_api.allocate_floating_ip(context, pool)
            ip = self.network_api.get_floating_ip_by_address(context, address)
        except exception.NoMoreFloatingIps:
            if pool:
                msg = _("No more floating IPs in pool %s.") % pool
            else:
                msg = _("No more floating IPs available.")
            raise webob.exc.HTTPNotFound(explanation=msg)
        except exception.FloatingIpLimitExceeded:
            if pool:
                msg = _("IP allocation over quota in pool %s.") % pool
            else:
                msg = _("IP allocation over quota.")
            raise webob.exc.HTTPForbidden(explanation=msg)
        except exception.FloatingIpPoolNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())
        except exception.FloatingIpBadRequest as e:
            raise webob.exc.HTTPBadRequest(explanation=e.format_message())

        return _translate_floating_ip_view(ip)

    @wsgi.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.response(202)
    @wsgi.expected_errors((400, 403, 404, 409))
    def delete(self, req, id):
        context = req.environ['nova.context']
        context.can(fi_policies.BASE_POLICY_NAME % 'delete',
                    target={'project_id': context.project_id})

        # get the floating ip object
        try:
            floating_ip = self.network_api.get_floating_ip(context, id)
        except (exception.NotFound, exception.FloatingIpNotFound):
            msg = _("Floating IP not found for ID %s") % id
            raise webob.exc.HTTPNotFound(explanation=msg)
        except exception.InvalidID as e:
            raise webob.exc.HTTPBadRequest(explanation=e.format_message())

        address = floating_ip['floating_ip_address']

        # get the associated instance object (if any)
        instance = get_instance_by_floating_ip_addr(self, context, address)
        try:
            self.network_api.disassociate_and_release_floating_ip(
                context, instance, floating_ip)
        except exception.Forbidden:
            raise webob.exc.HTTPForbidden()
        except exception.FloatingIpNotFoundForAddress as exc:
            raise webob.exc.HTTPNotFound(explanation=exc.format_message())


@validation.validated
class FloatingIPActionController(wsgi.Controller):
    """This API is deprecated from the Microversion '2.44'."""

    def __init__(self):
        super(FloatingIPActionController, self).__init__()
        self.compute_api = compute.API()
        self.network_api = neutron.API()

    @wsgi.api_version("2.1", "2.43")
    @wsgi.expected_errors((400, 403, 404))
    @wsgi.action('addFloatingIp')
    @validation.schema(schema.add_floating_ip)
    @validation.response_body_schema(schema.add_floating_ip_response)
    def _add_floating_ip(self, req, id, body):
        """Associate floating_ip to an instance."""
        context = req.environ['nova.context']
        instance = common.get_instance(self.compute_api, context, id,
                                       expected_attrs=['flavor'])
        context.can(fi_policies.BASE_POLICY_NAME % 'add',
                    target={'project_id': instance.project_id})

        address = body['addFloatingIp']['address']

        cached_nwinfo = instance.get_network_info()
        if not cached_nwinfo:
            LOG.warning(
                'Info cache is %r during associate with no nw_info cache',
                instance.info_cache, instance=instance)
            msg = _('Instance network is not ready yet')
            raise webob.exc.HTTPBadRequest(explanation=msg)

        fixed_ips = cached_nwinfo.fixed_ips()
        if not fixed_ips:
            msg = _('No fixed IPs associated to instance')
            raise webob.exc.HTTPBadRequest(explanation=msg)

        fixed_address = None
        if 'fixed_address' in body['addFloatingIp']:
            fixed_address = body['addFloatingIp']['fixed_address']
            for fixed in fixed_ips:
                if fixed['address'] == fixed_address:
                    break
            else:
                msg = _('Specified fixed address not assigned to instance')
                raise webob.exc.HTTPBadRequest(explanation=msg)

        if not fixed_address:
            try:
                fixed_address = next(ip['address'] for ip in fixed_ips
                                     if netutils.is_valid_ipv4(ip['address']))
            except StopIteration:
                msg = _('Unable to associate floating IP %(address)s '
                        'to any fixed IPs for instance %(id)s. '
                        'Instance has no fixed IPv4 addresses to '
                        'associate.') % (
                        {'address': address, 'id': id})
                raise webob.exc.HTTPBadRequest(explanation=msg)
            if len(fixed_ips) > 1:
                LOG.warning('multiple fixed_ips exist, using the first '
                            'IPv4 fixed_ip: %s', fixed_address)

        try:
            self.network_api.associate_floating_ip(context, instance,
                                  floating_address=address,
                                  fixed_address=fixed_address)
        except exception.FloatingIpAssociated:
            msg = _('floating IP is already associated')
            raise webob.exc.HTTPBadRequest(explanation=msg)
        except exception.FloatingIpAssociateFailed as e:
            raise webob.exc.HTTPBadRequest(explanation=e.format_message())
        except exception.NoFloatingIpInterface:
            msg = _('l3driver call to add floating IP failed')
            raise webob.exc.HTTPBadRequest(explanation=msg)
        except exception.FloatingIpNotFoundForAddress:
            msg = _('floating IP not found')
            raise webob.exc.HTTPNotFound(explanation=msg)
        except exception.Forbidden as e:
            raise webob.exc.HTTPForbidden(explanation=e.format_message())
        except Exception as e:
            msg = _('Unable to associate floating IP %(address)s to '
                    'fixed IP %(fixed_address)s for instance %(id)s. '
                    'Error: %(error)s') % (
                    {'address': address, 'fixed_address': fixed_address,
                     'id': id, 'error': e})
            LOG.exception(msg)
            raise webob.exc.HTTPBadRequest(explanation=msg)

        return webob.Response(status_int=202)

    @wsgi.api_version("2.1", "2.43")
    @wsgi.expected_errors((400, 403, 404, 409))
    @wsgi.action('removeFloatingIp')
    @validation.schema(schema.remove_floating_ip)
    @validation.response_body_schema(schema.remove_floating_ip_response)
    def _remove_floating_ip(self, req, id, body):
        """Dissociate floating_ip from an instance."""
        context = req.environ['nova.context']

        address = body['removeFloatingIp']['address']

        # get the associated instance object (if any)
        instance = get_instance_by_floating_ip_addr(self, context, address)

        target = {}
        if instance:
            target = {'project_id': instance.project_id}
        context.can(fi_policies.BASE_POLICY_NAME % 'remove',
                    target=target)

        # get the floating ip object
        try:
            floating_ip = self.network_api.get_floating_ip_by_address(context,
                                                                      address)
        except exception.FloatingIpNotFoundForAddress:
            msg = _("floating IP not found")
            raise webob.exc.HTTPNotFound(explanation=msg)

        # disassociate if associated
        if instance and floating_ip['port_id'] and instance.uuid == id:
            disassociate_floating_ip(self, context, instance, address)
            return webob.Response(status_int=202)
        else:
            msg = _("Floating IP %(address)s is not associated with instance "
                    "%(id)s.") % {'address': address, 'id': id}
            raise webob.exc.HTTPConflict(explanation=msg)
