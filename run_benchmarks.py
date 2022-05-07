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

clusters.set_virtio_fs_buffering(False)

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
    ('iodepth', 32, 8, 4, 2),
]

threads = []
for cluster in clusters.clusters:
    name = cluster[0][:]
    folder = os.path.join('data', name)
    os.makedirs(folder, exist_ok=True)
    runtime_class = 'kata-qemu' if cluster[2] else None
    bench = benchmark.Benchmark(folder, cluster[0], args.resource_group,
                                args.subscription, runtime_class,
                                False)
    t = threading.Thread(target=bench.run, args=(options, False))
    threads.append(t)
    t.start()

for t in threads:
    t.join()

# Delete clusters
if args.manage_clusters:
    clusters.delete_clusters(args)
