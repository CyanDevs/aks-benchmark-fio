#!/bin/python3
# Copyright (c) Open Enclave SDK contributors.
# Licensed under the MIT License

import argparse
import os
import subprocess
import sys
import threading

import nodecmd

lock = threading.Lock()

def create_cluster(name, vm_size, enable_kata, args):
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

    with lock:
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


def delete_cluster(name, args):
    res = subprocess.run(['az', 'aks', 'delete', '-y',
                          '--resource-group', args.resource_group,
                          '--name', name,
                          '--subscription', args.subscription])
    if res.returncode:
        os._exit(res.returncode)

def _set_virtio_fs_buffering(name, enable):
    cache_value = "auto" if enable else "none"
    nodecmd.execute_command(
        name, None, 'sed',
        '-i', 's/virtio_fs_cache\s\+=\s\+".*"/virtio_fs_cache = "%s"/' % cache_value,
        '/opt/kata/share/defaults/kata-containers/configuration-qemu.toml'
    )

    # Replace existing direct option
    nodecmd.execute_command(
        name, None, 'sed',
        '-i', 's/"-o"\s*,\s*"\(no_\)\{0,1\}allow_direct_io"\s*,\{0,1\}//g',
        '/opt/kata/share/defaults/kata-containers/configuration-qemu.toml'
    )

    # Set direct option correctly
    direct_value = "allow_direct_io" if not enable else "no_allow_direct_io"
    nodecmd.execute_command(
        name, None, 'sed',
        '-i', 's/virtio_fs_extra_args\s*=\s*\[/virtio_fs_extra_args = [ "-o", "%s", /g' % direct_value,
        '/opt/kata/share/defaults/kata-containers/configuration-qemu.toml'
    )


clusters = [
    ('runc-2', 'Standard_D2s_v3', False),
    ('runc-4', 'Standard_D4s_v3', False),
    ('runc-8', 'Standard_D8s_v3', False),
    ('kata-qemu-2', 'Standard_D2s_v3', True),
    ('kata-qemu-4', 'Standard_D4s_v3', True),
    ('kata-qemu-8', 'Standard_D8s_v3', True),
]


def join_all(threads):
    for t in threads:
        t.join()


def create_clusters(args):
    threads = []
    for c in clusters:
        t = threading.Thread(target=create_cluster, args=(*c, args))
        threads.append(t)
        t.start()
    join_all(threads)

def delete_clusters(args):
    threads = []
    for name,_, _ in clusters:
        t = threading.Thread(target=delete_cluster, args=(name, args))
        threads.append(t)
        t.start()
    join_all(threads)

def set_virtio_fs_buffering(enable):
    for name, _, k in clusters:
        if k:
            _set_virtio_fs_buffering(name, enable)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Create AKS fio benchmark clusters')
    parser.add_argument('action', choices=('create', 'delete', 'virtio-fs-cache-none', 'virtio-fs-cache-auto'))
    parser.add_argument('--subscription', '-s', type=str, required=True)
    parser.add_argument('--resource-group', '-rg', type=str, required=True)
    parser.add_argument('--location', '-l', type=str, default='CentralUS')

    args = parser.parse_args()

    if args.action == 'create':
        create_clusters(args)
    elif args.action == 'delete':
        delete_clusters(args)
    elif args.action == 'virtio-fs-cache-auto':
        change_virito_fs_caches(True)
    elif args.action == 'virtio-fs-cache-none':
        change_virtio_fs_caches(False)
    else:
        print("Unkown action %s" % args.action)
        sys.exit(1)
