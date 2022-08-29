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

cluster_template = """
    apiVersion: v1
    kind: PersistentVolumeClaim
    metadata:
    name: dbench-%(id)s
    spec:
    storageClassName: local-storage
    accessModes:
        - ReadWriteOnce
    resources:
        requests:
        storage: 100Gi
    ---
    apiVersion: v1
    kind: PersistentVolumeClaim
    metadata:
    name: azure-disk-%(id)s
    spec:
    accessModes:
    - ReadWriteOnce
    # storageClassName: default
    storageClassName: managed-csi-premium
    resources:
        requests:
        storage: 100Gi
    ---
    apiVersion: v1
    kind: PersistentVolumeClaim
    metadata:
    name: azure-file-%(id)s
    spec:
    accessModes:
        - ReadWriteMany
    storageClassName: azurefile
    # azurefile-csi-premium
    resources:
        requests:
        storage: 100Gi
    ---
    apiVersion: rbac.authorization.k8s.io/v1
    kind: ClusterRoleBinding
    metadata:
    name: local-storage-provisioner-pv-binding
    subjects:
    - kind: ServiceAccount
    name: local-storage-admin
    namespace: kube-system
    roleRef:
    kind: ClusterRole
    name: system:persistent-volume-provisioner
    apiGroup: rbac.authorization.k8s.io
    ---
    apiVersion: rbac.authorization.k8s.io/v1
    kind: ClusterRole
    metadata:
    name: local-storage-provisioner-node-clusterrole
    rules:
    - apiGroups: [""]
    resources: ["nodes"]
    verbs: ["get"]
    ---
    apiVersion: rbac.authorization.k8s.io/v1
    kind: ClusterRoleBinding
    metadata:
    name: local-storage-provisioner-node-binding
    subjects:
    - kind: ServiceAccount
    name: local-storage-admin
    namespace: kube-system
    roleRef:
    kind: ClusterRole
    name: local-storage-provisioner-node-clusterrole
    apiGroup: rbac.authorization.k8s.io
    ---
    apiVersion: v1
    kind: ServiceAccount
    metadata:
    name: local-storage-admin
    namespace: kube-system
    ---
    apiVersion: v1
    kind: ConfigMap
    metadata:
    name: local-provisioner-config
    namespace: kube-system
    data:
    setPVOwnerRef: "true"
    useNodeNameOnly: "true"
    storageClassMap: |
        local-storage:
        hostDir: /pv-disks
        mountDir: /pv-disks
    ---
    apiVersion: apps/v1
    kind: DaemonSet
    metadata:
    name: local-volume-provisioner
    namespace: kube-system
    labels:
        app: local-volume-provisioner
    spec:
    selector:
        matchLabels:
        app: local-volume-provisioner
    template:
        metadata:
        labels:
            app: local-volume-provisioner
        spec:
        serviceAccountName: local-storage-admin
        nodeSelector:
            kubernetes.azure.com/aks-local-ssd: "true"
        initContainers:
            - name: aks-nvme-ssd-provisioner
            image: ams0/aks-nvme-ssd-provisioner:v1.0.2
            imagePullPolicy: Always
            securityContext:
                privileged: true
            volumeMounts:
                - mountPath: /pv-disks
                name: local-storage
                mountPropagation: "Bidirectional"
        volumes:
            - name: pv-disks
            hostPath:
                path: /pv-disks
        containers:
            - image: "quay.io/external_storage/local-volume-provisioner:v2.3.3"
            name: provisioner
            securityContext:
                privileged: true
            resources:
                limits:
                cpu: 100m
                memory: 200Mi
                requests:
                cpu: 50m
                memory: 100Mi
            env:
            - name: MY_NODE_NAME
                valueFrom:
                fieldRef:
                    fieldPath: spec.nodeName
            - name: MY_NAMESPACE
                valueFrom:
                fieldRef:
                    fieldPath: metadata.namespace
            - name: JOB_CONTAINER_IMAGE
                value: "quay.io/external_storage/local-volume-provisioner:canary"
            volumeMounts:
                - mountPath: /etc/provisioner/config
                name: provisioner-config
                readOnly: true
                - mountPath: /dev
                name: provisioner-dev
                - mountPath: /pv-disks
                name: local-storage
                mountPropagation: "HostToContainer"
        volumes:
            - name: provisioner-config
            configMap:
                name: local-provisioner-config
            - name: provisioner-dev
            hostPath:
                path: /dev
            - name: local-storage
            hostPath:
                path: /pv-disks
    ---
    apiVersion: storage.k8s.io/v1
    kind: StorageClass
    metadata:
    name: local-storage
    provisioner: kubernetes.io/no-provisioner
    volumeBindingMode: WaitForFirstConsumer
    reclaimPolicy: Delete
"""

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

    with open(f'cluster_{name}.yaml', 'w') as f:
        f.write(cluster_template % {'id': name})

    res = subprocess.run(['kubectl', 'apply', '-f', f'cluster_{name}.yaml'])

    if res.returncode:
        os._exit(res.returncode)

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

    # Label NVME nodes
    if 'Standard_L' in vm_size:
        node = subprocess.run(['kubectl', 'get', 'nodes', '--output=name'], capture_output=True)

        if node.returncode:
            os._exit(node.returncode)

        res = subprocess.run(['kubectl', 'label', '--overwrite', node.stdout.decode('utf-8').strip(), 'kubernetes.azure.com/aks-local-ssd=true'])
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
    # ('cluster-2-1', 'Standard_D2s_v4'),
    # ('cluster-2-2', 'Standard_D2s_v4'),
    # ('cluster-2-3', 'Standard_D2s_v4'),

    # ('cluster-4-1', 'Standard_D4s_v4'),
    # ('cluster-4-2', 'Standard_D4s_v4'),
    # ('cluster-4-3', 'Standard_D4s_v4'),

    # ('cluster-8-1', 'Standard_D8s_v4'),
    # ('cluster-8-2', 'Standard_D8s_v4'),
    # ('cluster-8-3', 'Standard_D8s_v4'),

    ('cluster-L8-1', 'Standard_L8s_v3'),
    ('cluster-L8-2', 'Standard_L8s_v3'),
    ('cluster-L8-3', 'Standard_L8s_v3'),
]


def join_all(threads):
    for t in threads:
        t.join()


def create_clusters(args):
    threads = []
    enable_kata = True
    for c in clusters:
        t = threading.Thread(target=create_cluster, args=(*c, enable_kata, args))
        threads.append(t)
        t.start()
    join_all(threads)

def delete_clusters(args):
    threads = []
    for name,_ in clusters:
        t = threading.Thread(target=delete_cluster, args=(name, args))
        threads.append(t)
        t.start()
    join_all(threads)

def set_virtio_fs_buffering(enable):
    for name, _ in clusters:
        _set_virtio_fs_buffering(name, enable)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Create AKS fio benchmark clusters')
    parser.add_argument('action', choices=('create',
                                           'delete',
                                           'set-virtio-fs-direct',
                                           'set-vritio-fs-buffered'))
    parser.add_argument('--subscription', '-s', type=str, required=True)
    parser.add_argument('--resource-group', '-rg', type=str, required=True)
    parser.add_argument('--location', '-l', type=str, default='CentralUS')

    args = parser.parse_args()

    if args.action == 'create':
        create_clusters(args)
    elif args.action == 'delete':
        delete_clusters(args)
    elif args.action == 'set-virtio-fs-direct':
        set_virtio_fs_buffering(False)
    elif args.action == 'set-virtio-fs-buffered':
        set_virtio_fs_buffering(True)
    else:
        print("Unknown action %s" % args.action)
        sys.exit(1)
