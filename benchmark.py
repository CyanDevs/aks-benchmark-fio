#!/bin/python3
# Copyright (c) Open Enclave SDK contributors.
# Licensed under the MIT License

import argparse
import os
import pickle
import re
import subprocess
import sys
import traceback
import threading

class Benchmark:
    lock = threading.Lock()

    template = """
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: dbench-%(job)s
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
  name: azure-disk-%(job)s
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
  name: azure-file-%(job)s
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
---
apiVersion: batch/v1
kind: Job
metadata:
  name: fio-test
spec:
  template:
    metadata:
      labels:
        app: fio-test
    spec:
      %(runtime_class)s
      containers:
        - name: fio-test
          image: fangluguopub.azurecr.io/ubuntu-debug
          command: ["/root/docker-entrypoint.sh", "fio”]
          imagePullPolicy: IfNotPresent
          env:
            - name: DBENCH_MOUNTPOINT
              value: /s/mytmpfs
            - name: FIO_SIZE
              value: 10G
            - name: FIO_DIRECT
              value: "1"
            - name: FIO_RUNTIME
              value: 60s
            - name: DBENCH_QUICK
              value: ""
            - name: FIO_OFFSET_INCREMENT
              value: 500Mi
          volumeMounts:
            - mountPath: /s/azure-disk
              name: azure-disk
            - mountPath: /s/azure-file
              name: azure-file
            - mountPath: /s/mnt
              name: host-drive
            - mountPath: /s/mytmpfs
              name: host-mytmpfs
            - mountPath: /s/dbench
              name: dbench
      volumes:
        - name: azure-disk
          persistentVolumeClaim:
            claimName: azure-disk-%(job)s
        - name: azure-file
          persistentVolumeClaim:
            claimName: azure-file-%(job)s
        - name: host-drive
          hostPath:
            path: /mnt
        - name: host-mytmpfs
          hostPath:
            path: /mytmpfs
        - name: dbench
          persistentVolumeClaim:
            claimName: dbench-%(job)s
      restartPolicy: "Never"
  backoffLimit: 0
"""
    def __init__(self, folder, cluster, resource_group, subscription, runtime_class, update_cache):
        self.folder = folder
        self.cluster = cluster
        self.resource_group = resource_group
        self.subscription = subscription
        self.runtime_class = runtime_class
        self.update_cache = update_cache
        self.cache_file = os.path.join(folder, 'cache.pickle')
        self.cache = None
        self.normalized_cache = None

    def gen_jobs(self, options, cmd):
        jobs = []
        def gen(options, cmd):
            if len(options) == 0:
                jobs.append(cmd)
            else:
                opt, options = options[0], options[1:]
                name = opt[0]
                values = opt[1:]

                if len(values) == 1 and isinstance(values[0], tuple):
                    values = values[0]

                if len(values) > 0:
                    cmd += ' --' + name + '='

                    for v in values:
                        gen(options, cmd + str(v))
                else:
                    gen(options, cmd + ' --' + name)

        gen(options, cmd)
        return jobs

    def normalize(self, job):
        return ' '.join(sorted(job.split(' ')))

    def load_cache(self):
        self.cache = {}
        self.normalized_cache = {}
        if os.path.isfile(self.cache_file):
            with open(self.cache_file, 'rb') as f:
                cache = pickle.load(f)
                for job in list(cache.keys()):
                    njob = self.normalize(job)
                    self.normalized_cache[njob] = cache[job]
        print("%s: Loaded cached results." % self.cluster)
        if self.update_cache:
            print("%s: Updating cache with new results." % self.cluster)


    def cache_lookup(self, job):
        if self.update_cache:
            return None

        if job in self.cache:
            return self.cache[job]
        njob = self.normalize(job)
        if njob in self.normalized_cache:
            return self.normalized_cache[njob]

    def cache_store(self, job, result):
        self.cache[job] = result
        njob = self.normalize(job)
        self.normalized_cache[njob] = result
        with open(self.cache_file, 'wb') as f:
            pickle.dump(self.cache, f)


    def log(self, job, logs):
        lines = logs.split('\n')
        key_lines = []
        prefixes = ['read:', 'write:', 'READ:', 'WRITE:']
        for l in lines:
            lt = l.strip()
            for p in prefixes:
                if lt.startswith(p):
                    key_lines.append(l)
                    break

        with self.lock:
            print('')
            print(self.cluster)
            print(job)
            print('\n'.join(key_lines))

    def kubectl_apply(self, job, silent=True):

        result = self.cache_lookup(job)
        if result:
            if not silent:
                self.log(job, result)
            return


        if self.runtime_class:
            runtime_class = 'runtimeClassName: ' + self.runtime_class
        else:
            runtime_class = ''

        jobtext = self.template % {'runtime_class': runtime_class, 'job': job}
        jobfile = os.path.join(self.folder, 'job.yaml')
        with open(jobfile, 'w') as f:
            f.write(jobtext)

        subprocess.run(['kubectl', '--context='+ self.cluster,
                        'delete', '-f', jobfile], capture_output=True)

        res = subprocess.run(['kubectl', '--context='+ self.cluster,
                              'apply', '--overwrite=true', '-f', jobfile], capture_output=True)

        if res.returncode:
            print(res.stdout.decode('utf-8'))
            os._exit(res.returncode)

        try:
            res = subprocess.run(['kubectl', '--context='+ self.cluster,
                                  'wait', '--for=condition=complete',
                                  'jobs.batch/fio-test',
                                  '--timeout=600s'], capture_output=True)

            for i in range(0, 10):
                try:
                    res = subprocess.run(['kubectl', '--context='+ self.cluster,
                                          'get', 'pods'], capture_output=True)
                    pod = res.stdout.decode('utf-8').strip().split('\n')[-1].split()[0]
                    break
                except:
                    print('Failure')
                    print(res.stdout.decode('utf-8'))

            res = subprocess.run(['kubectl', '--context='+ self.cluster, 'logs', pod], capture_output=True)
            logs = res.stdout.decode('utf-8')

            self.cache_store(job, logs)
            if not silent:
                self.log(job, logs)

        except Exception as e:
            print(e)
            print(traceback.format_exc())

        subprocess.run(['kubectl', '--context='+ self.cluster, 'delete', '-f', jobfile], capture_output=True)

    def default_options(self):
        options = [
            ('name', 'test'),
            ('filename', 'test'),
            ('ioengine', 'libaio'),
            ('readwrite', 'randread', 'randwrite', 'randrw'),
            ('direct', '1'),
            ('bs', '4k'),
            ('size', '8G'),
            ('numjobs', '1', '2', '4'),
            ('runtime', 90),
            ('iodepth', 16)
        ]
        return options

    def run(self, options, silent=True):
        if not options:
            options = self.default_options()

        self.load_cache()
        jobs = self.gen_jobs(options, 'fio')
        for j in jobs:
            self.kubectl_apply(j, silent)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='AKS fio benchmark')
    parser.add_argument('--subscription', '-s', type=str, required=True)
    parser.add_argument('--resource-group', '-rg', type=str, required=True)
    parser.add_argument('--cluster', '-c', type=str, required=True)
    parser.add_argument('--runtime-class', '-rc', type=str, default=None)
    parser.add_argument('--update-cache', '-uc', action='store_const', const=True)

    args = parser.parse_args()
    benchmark = Benchmark(os.cwd(), args.cluster, args.resource_group,
                          args.subscription, args.runtime_class, args.update_cache)
