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

parser = argparse.ArgumentParser(description='AKS fio benchmark')
parser.add_argument('--subscription', '-s', type=str, required=True)
parser.add_argument('--resource-group', '-rg', type=str, required=True)
parser.add_argument('--cluster', '-c', type=str, required=True)
parser.add_argument('--runtime-class', '-rc', type=str, default='')

args = vars(parser.parse_args())

options = [
    ('name', 'test'),
    ('filename', 'test'),
    ('ioengine', 'libaio'),
    ('readwrite', 'randread', 'randwrite', 'randrw'),
    ('direct', '0', '1'),
#    ('bs', '4k', '2k', '8k', '16k'),
    ('size', '1G', '4G'),
    ('numjobs', '1', '2', '4'),
    ('norandommap',),
    ('runtime', 90),
    ('time_based', 0, 1),
#    ('iodepth', 1, 4, 8, 16, 32)
    ('iodepth', 16),
    ('bs', '2k', '4k', '8k', '16k')
]


def gen_jobs(options, cmd=''):
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

jobs = gen_jobs(options, 'fio')

#
# Get credentials for the cluster
res = subprocess.run(['az', 'aks', 'get-credentials',
                 '--resource-group', args['resource_group'],
                 '--subscription', args['subscription'],
                      '--name', args['cluster']])
if res.returncode:
    sys.exit(res.returncode)

def normalize(job):
    return ' '.join(sorted(job.split(' ')))

cache = {}
CACHE_FILE = "cache.pickle"
if os.path.isfile(CACHE_FILE):
    with open(CACHE_FILE, 'rb') as f:
        cache = pickle.load(f)
        for job in list(cache.keys()):
            njob = normalize(job)
            cache[njob] = cache[job]
        print("\nLoaded cached results.")


def cache_lookup(job):
    if job in cache:
        return cache[job]
    njob = normalize(job)
    if njob in cache:
        return cache[njob]

def cache_store(job, result):
    global cache
    njob = normalize(job)
    cache[job] = result
    cache[njob] = result
    with open(CACHE_FILE, 'wb') as f:
        pickle.dump(cache, f)

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

def kubectl_apply(job):
    print('')
    print(job)

    result = cache_lookup(job)
    if result:
        print(result)
        return

    runtime_class = args['runtime_class']
    if runtime_class:
        runtime_class = 'runtimeClassName: ' + runtime_class
    jobtext = template % (runtime_class, job)
    jobfile = 'job.yaml'
    with open(jobfile, 'w') as f:
        f.write(jobtext)

    res = subprocess.run(['kubectl', '--context='+ args['cluster'],
                          'apply', '--overwrite=true', '-f', jobfile], capture_output=True)
    if res.returncode:
        sys.exit(res.returncode)

    try:
        res = subprocess.run(['kubectl', '--context='+ args['cluster'],
                              'wait', '--for=condition=complete',
                              'jobs.batch/fio-test',
                              '--timeout=400s'], capture_output=True)

        res = subprocess.run(['kubectl', '--context='+ args['cluster'],
                              'get', 'pods'], capture_output=True)
        pod = res.stdout.decode('utf-8').strip().split('\n')[-1].split()[0]

        res = subprocess.run(['kubectl', '--context='+ args['cluster'], 'logs', pod], capture_output=True)
        logs = res.stdout.decode('utf-8')

        reads = re.findall('\s+READ.+', logs)
        result = ''
        if reads:
            result += '   ' + reads[-1].strip()

        writes = re.findall('\s+WRITE.+', logs)
        if writes:
            result += '\n   ' + writes[-1].strip()

        cache_store(job, result)
        print(result)

    except Exception as e:
        print(e)
        print(traceback.format_exc())

    subprocess.run(['kubectl', '--context='+ args['cluster'],'delete', '-f', jobfile], capture_output=True)

for j in jobs:
    kubectl_apply(j)
