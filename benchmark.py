#!/bin/python3

# Copyright (c) Open Enclave SDK contributors.
# Licensed under the MIT Licen

import argparse
import os
import pickle
import re
import subprocess
import sys
import traceback


class Benchmark:
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
        image: mocha81/fio-3.16
        command: [
          "sh",
          "-c",
          "nproc; cmd='%s'; echo $cmd; $cmd"
          ]
      restartPolicy: "Never"
  backoffLimit: 0
"""
    def __init__(folder, cluster, resource_group, subscription, runtime_class, update_cache):
        self.folder = folder
        self.cluster = cluster
        self.resource_group = resource_group
        self.subscription = subscription
        self.runtime_class = runtime_class
        self.update_cache = update_cache
        self.cache_file = os.path.join(folder, 'cache.pickle')
        self.cache = None
        self.normalized_cache = None

    def gen_jobs(self, options):
        jobs = []
        def gen(options, cmd):
            if len(options) == 0:
                jobs.append(cmd)
            else:
                opt, options = options[0], options[1:]
                name = opt[0]
                values = opt[1:]
                if name in args and args[name]:
                    values = args[name].split(' ')

                if len(values) == 1 and isinstance(values[0], tuple):
                    values = values[0]

                if len(values) > 0:
                    cmd += ' --' + name + '='

                    for v in values:
                        gen(options, cmd + str(v))
                else:
                    gen(options, cmd)
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
        print("\nLoaded cached results.")

    def cache_lookup(self, job):
        if self.update_cache:
            return None

        if job in cache:
            return cache[job]
        njob = self.normalize(job)
        if njob in self.normalized_cache:
            return self.normalized_cache[njob]

    def cache_store(self, job, result):
        njob = self.normalize(job)
        cache[job] = result
        self.normalized_cache[njob] = result
        with open(self.cache_file, 'wb') as f:
            pickle.dump(cache, f)


    def kubectl_apply(self, job, silent=True):
        if not silent:
            print('')
            print(job)

        result = self.cache_lookup(job)
        if result:
            print(result)
            return


        if self.runtime_class:
            runtime_class = 'runtimeClassName: ' + runtime_class
        else:
            runtime_class = ''

        jobtext = template % (runtime_class, job)
        jobfile = 'job.yaml'
        with open(jobfile, 'w') as f:
            f.write(jobtext)

        res = subprocess.run(['kubectl', '--context='+ self.cluster,
                              'apply', '--overwrite=true', '-f', jobfile], capture_output=True)
        if res.returncode:
            os._exit(res.returncode)

        try:
            res = subprocess.run(['kubectl', '--context='+ self.cluster,
                                  'wait', '--for=condition=complete',
                                  'jobs.batch/fio-test',
                                  '--timeout=400s'], capture_output=True)

            res = subprocess.run(['kubectl', '--context='+ self.cluster,
                                  'get', 'pods'], capture_output=True)
            pod = res.stdout.decode('utf-8').strip().split('\n')[-1].split()[0]

            res = subprocess.run(['kubectl', '--context='+ self.cluster, 'logs', pod], capture_output=True)
            logs = res.stdout.decode('utf-8')

            reads = re.findall('\s+READ.+', logs)
            result = ''
            if reads:
                result += '   ' + reads[-1].strip()

            writes = re.findall('\s+WRITE.+', logs)
            if writes:
                result += '\n   ' + writes[-1].strip()

            self.cache_store(job, result)
            if not silent:
                print(result)

        except Exception as e:
            print(e)
            print(traceback.format_exc())

        subprocess.run(['kubectl', '--context='+ args['cluster'],'delete', '-f', jobfile], capture_output=True)

    def default_options(self):
        options = [
            ('name', 'test'),
            ('filename', 'test'),
            ('ioengine', 'libaio'),
            ('readwrite', 'randread', 'randwrite', 'randrw'),
            ('direct', '1'),
            ('bs', '4k'),
            ('size', '1G'),
            ('numjobs', '1', '2', '4'),
            ('runtime', 90),
            ('iodepth', 16)
        ]
        return options

    def run(self, options, silent=True):
        if not options:
            options = self.default_options()

        res = subprocess.run(['az', 'aks', 'get-credentials', '--overwrite-existing',
                              '--resource-group', self.resource_group,
                              '--subscription', self.subscription,
                              '--name', self.cluster])
        if res.returncode:
            os._exit(res.returncode)

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
