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
      %s
      containers:
      - name: fio-test
        image: sagoel/fio:3.16
        command: [
          "sh",
          "-c",
          "nproc; cmd='%s'; echo $cmd; $cmd"
          ]
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

        jobtext = self.template % (runtime_class, job)
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
