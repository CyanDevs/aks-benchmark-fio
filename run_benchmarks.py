#!/bin/python3
# Copyright (c) Open Enclave SDK contributors.
# Licensed under the MIT License

import argparse
import os
import threading

import benchmark
import clusters

parser = argparse.ArgumentParser(description='Run AKS fio unbuffered benchmarks')
parser.add_argument('--subscription', '-s', type=str, required=True)
parser.add_argument('--resource-group', '-rg', type=str, required=True)
parser.add_argument('--location', '-l', type=str, default='CentralUS')
parser.add_argument('--manage-clusters', action='store_const', const=True)

args = parser.parse_args()

# Create containerd and kata clusters
if args.manage_clusters:
    clusters.create_clusters(args)

options = [
    ('name', 'test'),
    ('filename', 'test'),
    ('ioengine', 'libaio'),
    ('readwrite', 'randread', 'randwrite', 'randrw'),
    ('direct', '1'),
    ('ramp_time', 30),
    ('runtime', 30),
    ('time_based', 1),
    ('size', '4g'),
    ('group_reporting',),
    ('bs', '1k', '2k', '4k', '8k', '16k', '32k', '64k', '128k', '256k'),
    ('numjobs', '1', '2', '4'),
]

def run_benchmark(cluster_name, node_type, options):
    folder = os.path.join('data', cluster_name, node_type, 'runc')
    os.makedirs(folder, exist_ok=True)

    runtime_class = ''
    bench = benchmark.Benchmark(folder, cluster_name, args.resource_group,
                                args.subscription, runtime_class,
                                False)
    bench.run(options, False)

    folder = os.path.join('data', cluster_name, node_type, 'kata-qemu')
    os.makedirs(folder, exist_ok=True)
    runtime_class = 'kata-qemu'
    bench = benchmark.Benchmark(folder, cluster_name, args.resource_group,
                                args.subscription, runtime_class,
                                False)
    bench.run(options, False)
    
def run_benchmarks():
    clusters.set_virtio_fs_buffering(False)

    iodepths = [
        ('iodepth', 1, 8, 64),
        ('iodepth', 2, 16, 128),
        ('iodepth', 4, 32, 256),
    ]

    idx = 0
    
    threads = []
    for c in clusters.clusters:
        opts = options.copy()
        opts.append(iodepths[idx])
        t = threading.Thread(target=run_benchmark, args=(*c, opts))
        threads.append(t)

        idx += 1
        if idx >= len(iodepths):
            idx = 0

    for t in threads:
        t.start()
    for t in threads:
        t.join()

run_benchmarks()
    
# Delete clusters
if args.manage_clusters:
    clusters.delete_clusters(args)
