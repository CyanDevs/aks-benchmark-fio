#!/bin/python3

# Copyright (c) Open Enclave SDK contributors.
# Licensed under the MIT Licen

import argparse
import os
import pathlib
import pickle
import re

parser = argparse.ArgumentParser(description='AKS fio benchmark query')
parser.add_argument('--readwrite', type=str)
parser.add_argument('--direct', type=str)
parser.add_argument('--size', type=str)
parser.add_argument('--numjobs', type=int)
parser.add_argument('--bs', type=str)
parser.add_argument('--ioengine', type=str)
parser.add_argument('--runtime', type=str)
parser.add_argument('--iodepth', type=str)
parser.add_argument('--time_based', '--time-based', type=str)
parser.add_argument('--norandommap', action='store_const', const=True)
parser.add_argument('--no-norandommap', action='store_const', const=True)

args = vars(parser.parse_args())

caches = [ (p.parent, pickle.loads(p.read_bytes()))
           for p in sorted(pathlib.Path('.').rglob('cache.pickle'))]

for (name, cache) in caches:
    description = pathlib.Path(os.path.join(name, 'description.txt')).read_text()
    matches = list(cache.items())

    # Avoid duplicates
    matches = [ (job, result) for job, result in matches if job.startswith('fio') ]

    for (option, value) in args.items():
        if not value:
            continue

        if type(value) == bool and value:
            if option.startswith('no_'):
                option_str = '--' + option[3:]
                matches = [ (job, result) for job, result in matches if not option_str in job]
            else:
                option_str = '--' + option
                matches = [(job, result) for (job, result) in matches if option_str in job]
        else:
            option_str = ' --%s=%s' % (option, value)
            matches = [ (job, result) for job, result in matches if option_str in job]


    def printable(job):
        if '--norandommap' in job:
            job = job.replace('--norandommap', '') + ' --norandommap'
        return re.sub(' +', ' ', job)

    matches = sorted([(printable(job), result) for job, result in matches])
    print('-' * 170)
    print('%s : %s' % (name, description))
    print('-' * 170)
    for (job, result) in matches:
        print(job.strip())
        print('   %s' % result.strip())
        print('')
    print('-' * 170)
    print("\n\n")
