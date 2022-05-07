#!/bin/python3

# Copyright (c) Open Enclave SDK contributors.
# Licensed under the MIT Licen

import os
import math
import pandas as pd
import pathlib
import pickle
import re
import sys

# Map folder names to tag and node type
mappings = {
    # Runc
    'containerd-2' : ('runc', 'Standard_D2s_v3'),
    'containerd-4' : ('runc', 'Standard_D4s_v3'),
    'containerd-8' : ('runc', 'Standard_D8s_v3'),
    'runc-2' : ('runc', 'Standard_D2s_v3'),
    'runc-4' : ('runc', 'Standard_D4s_v3'),
    'runc-8' : ('runc', 'Standard_D8s_v3'),

    # Kata qemu
    'kata-2' : ('kata-qemu', 'Standard_D2s_v3'),
    'kata-4' : ('kata-qemu', 'Standard_D4s_v3'),
    'kata-8' : ('kata-qemu', 'Standard_D8s_v3'),
    'kata-qemu-2' : ('kata-qemu', 'Standard_D2s_v3'),
    'kata-qemu-4' : ('kata-qemu', 'Standard_D4s_v3'),
    'kata-qemu-8' : ('kata-qemu', 'Standard_D8s_v3'),

     # Kata clh
    'kata-clh-2' : ('kata-clh', 'Standard_D2s_v3'),
    'kata-clh-4' : ('kata-clh', 'Standard_D4s_v3'),
    'kata-clh-8' : ('kata-clh', 'Standard_D8s_v3'),
}

# Read all results caches
caches = [ (p.parent, pickle.loads(p.read_bytes()))
           for p in sorted(pathlib.Path('.').rglob('cache.pickle'))]

def get_formatted_folder_name(path):
    name = path.parts[-1]
    name = name.replace('aks-benchmark-', '')
    return name

# Ensure that there is a mapping for each folder
for (path, cache) in caches:
    name = get_formatted_folder_name(path)
    if not name in mappings:
        print('Edit script to provide mapping for %s' % name)
        sys.exit(1)

read_re = re.compile(r'read: IOPS=(\d+\.?\d*)(k?), BW=(\d+\.?\d*)(MiB/s|KiB/s|B/s)')
write_re = re.compile(r'write: IOPS=(\d+\.?\d*)(k?), BW=(\d+\.?\d*)(MiB/s|KiB/s|B/s)')

def get_iops_bw(m):
    iops = float(m[0])
    if m[1] == 'k':
        iops *= 1000
    iops = math.ceil(iops)
    bw = float(m[2])
    if m[3] == 'KiB/s':
         bw /= 1024.0
    elif m[3] == 'B/s':
         bw /= (1024.0 * 1024.0)
    bw *= 1.024
    bw_raw = m[2] + m[3]
    return (bw_raw, iops, bw)

def add_job_to_table(job, output, common_fields, table):
    to_remove = ['--', 'fio', 'group_reporting']
    for s in to_remove:
        job = job.replace(s, '')

    row = common_fields.copy()
    for option in job.split():
        parts = option.split('=')
        row[parts[0]] = parts[1] if len(parts) == 2 else 1

    reads = re.findall(read_re, output)
    row['op'] = 'read'
    for idx, read in enumerate(reads):
        row['BW'], row['IOPS'], row['BW (MB/s)'] = get_iops_bw(read)
        if len(reads) > 1:
            row['job'] = idx
        table.append(row.copy())

    writes = re.findall(write_re, output)
    row['op'] = 'write'
    for idx, write in enumerate(writes):
        row['BW'], row['IOPS'], row['BW (MB/s)'] = get_iops_bw(write)
        if len(writes) > 1:
            row['job'] = idx
        table.append(row.copy())


    if not reads and not writes:
        print("Error parsing the following.")
        print(output)
        print('read_re = %s' % read_re)
        print(reads)
        print('write_re = %s' % write_re)
        print(writes)
        sys.exit(1)

table = []
for (path, cache) in caches:
    name = get_formatted_folder_name(path)
    m = mappings[name]

    common_fields = { 'ctr-runtime' : m[0], 'node' : m[1] }
    for job, output in cache.items():
        add_job_to_table(job, output, common_fields, table)

df = pd.DataFrame(table)

pd.set_option('display.max_rows', None)
pd.set_option('display.max_columns', None)
pd.set_option('display.width', 1000)
pd.set_option('display.colheader_justify', 'center')
pd.set_option('display.precision', 3)
print(df)

df.to_csv('data.csv')

