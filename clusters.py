#!/bin/python3

import argparse
import os
import subprocess
import sys
import threading

import nodecmd

parser = argparse.ArgumentParser(description='Create AKS fio benchmark clusters')
parser.add_argument('action', choices=('create', 'delete', 'kata-cache-disable', 'kata-cache-enable'))
parser.add_argument('--subscription', '-s', type=str, required=True)
parser.add_argument('--resource-group', '-rg', type=str, required=True)
parser.add_argument('--location', '-l', type=str, default='CentralUS')

args = parser.parse_args()

def create_cluster(name, vm_size, enable_kata):
    res = subprocess.run(['az', 'aks', 'create',
                          '--resource-group', args.resource_group,
                          '--name', name,
                          '--node-count', '1',
                          '--generate-ssh-keys',
                          '--vm-set-type', 'Virtualmachinescalesets',
                          '--node-vm-size', vm_size,
                          '--location', args.location,
                          '--subscription', args.subscription])
    if res.returncode:
        os._exit(res.returncode)

    res = subprocess.run(['az', 'aks', 'get-credentials',
                          '--resource-group', args.resource_group,
                          '--name', name,
                          '--subscription', args.subscription,
                          '--overwrite-existing'])
    
        
    if enable_kata:
        url_common = 'https://raw.githubusercontent.com/kata-containers/kata-containers/'
        url_common += 'main/tools/packaging/kata-deploy/'

        res = subprocess.run(['kubectl', 'apply', '--context', name, '-f',
                             url_common + 'kata-rbac/base/kata-rbac.yaml'])
        if res.returncode:
            os._exit(res.returncode)

        res = subprocess.run(['kubectl', 'apply', '--context', name, '-f',
                             url_common + 'kata-deploy/base/kata-deploy-stable.yaml'])
        if res.returncode:
            os._exit(res.returncode)

        res = subprocess.run(['kubectl', '--context', name, '-n', 'kube-system', 'wait',
                              '--timeout=10m', '--for=condition=Ready',
                              '-l', 'name=kata-deploy', 'pod'])

        if res.returncode:
            os._exit(res.returncode)

        res = subprocess.run(['kubectl', 'apply', '--context', name, '-f',
                             url_common + 'runtimeclasses/kata-runtimeClasses.yaml'])

        if res.returncode:
            os._exit(res.returncode)


def delete_cluster(name):
    res = subprocess.run(['az', 'aks', 'delete', '-y',
                          '--resource-group', args.resource_group,
                          '--name', name,
                          '--subscription', args.subscription])
    if res.returncode:
        os._exit(res.returncode)

def change_cache(name, enable):
    cache_value = "auto" if enable else "none"
    nodecmd.execute_command(
        name, None, 'sed',
        '-i', 's/virtio_fs_cache\s\+=\s\+".*"/virtio_fs_cache = "%s"/' % cache_value,
        '/opt/kata/share/defaults/kata-containers/configuration-qemu.toml'
    )
    
clusters = [
    ('aks-benchmark-containerd-2', 'Standard_D2s_v3', False),
    ('aks-benchmark-containerd-4', 'Standard_D4s_v3', False),
    ('aks-benchmark-containerd-8', 'Standard_D8s_v3', False),
    ('aks-benchmark-kata-2', 'Standard_D2s_v3', True),
    ('aks-benchmark-kata-4', 'Standard_D4s_v3', True),
    ('aks-benchmark-kata-8', 'Standard_D8s_v3', True),
]

threads = []

if args.action == 'create':
    for c in clusters:
        t = threading.Thread(target=create_cluster, args=c)
        threads.append(t)
        t.start()
elif args.action == 'delete':
    for name,_, _ in clusters:
        t = threading.Thread(target=delete_cluster, args=(name,))
        threads.append(t)
        t.start()
elif args.action == 'kata-cache-disable':
    for name, _, k in clusters:
        if k:
            change_cache(name, False)
elif args.action == 'kata-cache-enable':
    for name, _, k in clusters:
        if k:
            change_cache(name, True)            
else:
    print("Unkown action %s" % args.action)
    sys.exit(1)
        
# Wait for all threads to complete
for t in threads:
    t.join()
