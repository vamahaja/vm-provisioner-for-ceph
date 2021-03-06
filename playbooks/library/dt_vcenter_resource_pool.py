#!/usr/bin/env python
# -*- coding: utf-8 -*-

# (c) 2017, Davis Phillips davis.phillips@gmail.com
#
# This file is part of Ansible
#
# Ansible is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Ansible is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Ansible.  If not, see <http://www.gnu.org/licenses/>.

ANSIBLE_METADATA = {
    'status': ['preview'],
    'supported_by': 'community',
    'version': '1.0',
}

DOCUMENTATION = """
---
module: dt_vcenter_resource_pool
short_description: Add/remove resource pools to/from vCenter
description:
    - This module can be used to add/remove a resource pool to/from vCenter
version_added: 2.3
author: "Davis Phillips (@dav1x)"
notes:
    - Tested on vSphere 6.5
requirements:
    - "python >= 2.6"
    - PyVmomi
options:
    hostname:
        description: ESXi hostname to manage
        required: True
    username:
        description: ESXi username
        required: True
    password:
        description: ESXi password
        required: True
    datacenter:
        description: Name of the datacenter to add the host
        required: True
    cluster:
        description: Name of the cluster to add the host
        required: True
    resource_pool:
        description: Resource pool name to manage
        required: True
    cpu_expandable_reservations:
        description:
            - In a resource pool with an expandable reservation,
              the reservation on a resource pool can grow beyond
              the specified value.
        default: True
    cpu_reservation:
        description:
            - Amount of resource that is guaranteed available to
              the virtual machine or resource pool.
        default: 0
    cpu_limit:
        description:
            - The utilization of a virtual machine/resource pool will not
              exceed this limit, even if there are available resources.
        default: -1 (No limit)
    cpu_shares:
        description: Memory shares are used in case of resource contention.
        choices:
            - high
            - custom
            - low
            - normal
        default: Normal
    mem_expandable_reservations:
        description:
            - In a resource pool with an expandable reservation,
              the reservation on a resource pool can grow beyond
              the specified value.
        default: True
    mem_reservation:
        description:
            - Amount of resource that is guaranteed available to
              the virtual machine or resource pool.
        default: 0
    mem_limit:
        description:
            - The utilization of a virtual machine/resource pool will not
              exceed this limit, even if there are available resources.
        default: -1 (No limit)
    mem_shares:
        description: Memory shares are used in case of resource contention.
        choices:
            - high
            - custom
            - low
            - normal
        default: Normal
    state:
        description: Add or remove the resource pool
        default: 'present'
        choices:
            - 'present'
            - 'absent'
extends_documentation_fragment: vcenter.documentation
EXAMPLES =
# Create a resource pool
  - name: Add resource pool to vCenter
    dt_vcenter_resource_pool:
      hostname: vcsa_host
      username: vcsa_user
      password: vcsa_pass
      datacenter: datacenter
      cluster: cluster
      resource_pool: resource_pool
      mem_shares: normal
      mem_limit: -1
      mem_reservation: 0
      mem_expandable_reservations: True
      cpu_shares: normal
      cpu_limit: -1
      cpu_reservation: 0
      cpu_expandable_reservations: True
      state: present
RETURN =
instance:
    descripton: metadata about the new resource pool
    returned: always
    type: dict
    sample: None
"""

try:
    from pyVmomi import vim, vmodl
    HAS_PYVMOMI = True
except ImportError:
    HAS_PYVMOMI = False

from ansible.module_utils import basic  # noqa
from ansible.module_utils.vmware import (  # noqa
    get_all_objs,
    connect_to_api,
    vmware_argument_spec,
    find_datacenter_by_name,
    wait_for_task,
)

def find_cluster_by_name_datacenter(datacenter, cluster_name):
    for folder in datacenter.hostFolder.childEntity:
        if folder.name == cluster_name:
            return folder
    return None


class vCenterResourcePool(object):
    def __init__(self, module):
        self.module = module
        self.datacenter = module.params['datacenter']
        self.cluster = module.params['cluster']
        self.resource_pool = module.params['resource_pool']
        self.hostname = module.params['hostname']
        self.username = module.params['username']
        self.password = module.params['password']
        self.state = module.params['state']
        self.mem_shares = module.params['mem_shares']
        self.mem_limit = module.params['mem_limit']
        self.mem_reservation = module.params['mem_reservation']
        self.mem_expandable_reservations = (
            module.params['cpu_expandable_reservations'])
        self.cpu_shares = module.params['cpu_shares']
        self.cpu_limit = module.params['cpu_limit']
        self.cpu_reservation = module.params['cpu_reservation']
        self.cpu_expandable_reservations = (
            module.params['cpu_expandable_reservations'])
        self.dc_obj = None
        self.cluster_obj = None
        self.host_obj = None
        self.resource_pool_obj = None
        self.content = connect_to_api(module)

    def find_host_by_cluster_datacenter(self):
        self.dc_obj = find_datacenter_by_name(
            self.content, self.datacenter)
        self.cluster_obj = find_cluster_by_name_datacenter(
            self.dc_obj, self.cluster)

        for host in self.cluster_obj.host:
            if host.name == self.hostname:
                return host, self.cluster

        return None, self.cluster

    def select_resource_pool(self, host):
        pool_obj = None

        resource_pools = get_all_objs(self.content, [vim.ResourcePool])

        pool_selections = self.get_obj(
            [vim.ResourcePool], self.resource_pool, return_all=True)
        if pool_selections:
            for p in pool_selections:
                if p in resource_pools:
                    pool_obj = p
                    break
        return pool_obj

    def get_obj(self, vimtype, name, return_all=False):
        obj = []
        container = self.content.viewManager.CreateContainerView(
            self.content.rootFolder, vimtype, True)

        for c in container.view:
            if name in [c.name, c._GetMoId()]:
                if return_all is False:
                    return c
                else:
                    obj.append(c)

        return obj if len(obj) > 0 else None

    def process_state(self):
        try:
            rp_states = {
                'absent': {
                    'present': self.state_remove_rp,
                    'absent': self.state_exit_unchanged,
                },
                'present': {
                    'present': self.state_exit_unchanged,
                    'absent': self.state_add_rp,
                }
            }

            rp_states[self.state][self.check_rp_state()]()
        except vmodl.RuntimeFault as runtime_fault:
            self.module.fail_json(msg=runtime_fault.msg)
        except vmodl.MethodFault as method_fault:
            self.module.fail_json(msg=method_fault.msg)
        except Exception as e:
            self.module.fail_json(msg=str(e))

    def state_exit_unchanged(self):
        self.module.exit_json(changed=False)

    def state_remove_rp(self):
        changed = True
        result = None
        resource_pool = self.select_resource_pool(self.host_obj)
        try:
            task = self.resource_pool_obj.Destroy()
            success, result = wait_for_task(task)
        except Exception:
            self.module.fail_json(
                msg="Failed to remove resource pool '%s' '%s'" % (
                    self.resource_pool, resource_pool))
        self.module.exit_json(changed=changed, result=str(result))

    def state_add_rp(self):
        changed = True

        rp_spec = vim.ResourceConfigSpec()
        cpu_alloc = vim.ResourceAllocationInfo()
        cpu_alloc.expandableReservation = self.cpu_expandable_reservations
        cpu_alloc.limit = int(self.cpu_limit)
        cpu_alloc.reservation = int(self.cpu_reservation)
        cpu_alloc_shares = vim.SharesInfo()
        cpu_alloc_shares.level = self.cpu_shares
        cpu_alloc.shares = cpu_alloc_shares
        rp_spec.cpuAllocation = cpu_alloc
        mem_alloc = vim.ResourceAllocationInfo()
        mem_alloc.limit = int(self.mem_limit)
        mem_alloc.expandableReservation = self.mem_expandable_reservations
        mem_alloc.reservation = int(self.mem_reservation)
        mem_alloc_shares = vim.SharesInfo()
        mem_alloc_shares.level = self.mem_shares
        mem_alloc.shares = mem_alloc_shares
        rp_spec.memoryAllocation = mem_alloc

        self.dc_obj = find_datacenter_by_name(
            self.content, self.datacenter)
        self.cluster_obj = find_cluster_by_name_datacenter(
            self.dc_obj, self.cluster)
        rootResourcePool = self.cluster_obj.resourcePool
        rootResourcePool.CreateResourcePool(self.resource_pool, rp_spec)

        self.module.exit_json(changed=changed)

    def check_rp_state(self):
        self.host_obj, self.cluster_obj = (
            self.find_host_by_cluster_datacenter())
        self.resource_pool_obj = self.select_resource_pool(self.host_obj)
        return 'absent' if self.resource_pool_obj is None else 'present'


def main():
    argument_spec = vmware_argument_spec()
    argument_spec.update({
        "hostname": {"required": True, "type": "str"},
        "username": {"required": True, "type": "str"},
        "password": {"required": True, "type": "str", "no_log": True},
        "datacenter": {"required": True, "type": "str"},
        "cluster": {"required": True, "type": "str"},
        "resource_pool": {"required": True, "type": "str"},
        "mem_shares": {
            "type": "str", "default": "normal",
            "choices": ["high", "custom", "normal", "low"],
        },
        "mem_limit": {"type": "int", "default": "-1"},
        "mem_reservation": {"type": "int", "default": "0"},
        "mem_expandable_reservations": {"type": "bool", "default": "True"},
        "cpu_shares": {
            "type": "str", "default": "normal",
            "choices": ["high", "custom", "normal", "low"]
        },
        "cpu_limit": {"type": "int", "default": "-1"},
        "cpu_reservation": {"type": "int", "default": "0"},
        "cpu_expandable_reservations": {"type": "bool", "default": "True"},
        "state": {
            "default": "present",
            "choices": ["present", "absent"],
            "type": "str",
        },
    })

    module = basic.AnsibleModule(
        argument_spec=argument_spec, supports_check_mode=True)

    if not HAS_PYVMOMI:
        module.fail_json(msg='pyvmomi is required for this module')

    vcenter_rp = vCenterResourcePool(module)
    vcenter_rp.process_state()


if __name__ == '__main__':
    main()
