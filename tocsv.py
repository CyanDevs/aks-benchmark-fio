#!/bin/python3
# Copyright (c) Open Enclave SDK contributors.
# Licensed under the MIT License

import os
import math
import pandas as pd
import pathlib
import pickle
import re
import sys

# Load all caches
caches = [ (p.parent, pickle.loads(p.read_bytes()))
           for p in sorted(pathlib.Path('.').rglob('cache.pickle'))]

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
    ctr_runtime = path.parts[-1]
    node = path.parts[-2]
    
    common_fields = { 'ctr-runtime' : ctr_runtime, 'node' : node }
    for job, output in cache.items():
        add_job_to_table(job, output, common_fields, table)

df = pd.DataFrame(table)

pd.set_option('display.max_rows', None)
pd.set_option('display.max_columns', None)
pd.set_option('display.width', 1000)
pd.set_option('display.colheader_justify', 'center')
pd.set_option('display.precision', 3)

df = df.drop_duplicates()
df = df.sort_values(['ctr-runtime', 'node', 'readwrite', 'op', 'iodepth', 'bs', 'numjobs'])
print(df)

df.to_csv('data.csv', index=False)
