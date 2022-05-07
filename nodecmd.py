#!/bin/python3

import argparse
import os
import subprocess

def execute_command(cluster, node, cmd, *args):
    if not node:
        res = subprocess.run(['kubectl', 'get', 'nodes', '--context', cluster],
                         capture_output=True)
        if res.returncode:
            print(res.stdout)
            os._exit(res.returncode)

        output = res.stdout.decode('utf-8')

        # Fetch the first node.
        node = output.split('\n')[1].split()[0]

    res = subprocess.run(['kubectl', 'debug', 'node/' + node,
                          '--context', cluster,
                          '-it', '--image=docker.io/library/alpine',
                          '--', 'chroot', '/host', cmd, *args])

    if not res.returncode:
        res = subprocess.run(['kubectl', 'get', 'pods', '--context', cluster],
                             capture_output=True)
        if not res.returncode:
            lines = res.stdout.decode('utf-8').split('\n')
            for l in lines:
                words = l.split()
                if words and words[0].startswith('node-debugger'):
                    subprocess.run(['kubectl', 'delete', 'pod', words[0],
                                    '--context', cluster]) 

if __name__=="__main__":
    parser = argparse.ArgumentParser(description='Execute command on AKS node')
    parser.add_argument('--cluster', '-c', type=str, required=True)
    parser.add_argument('--node', '-n', type=str)
    parser.add_argument('command', type=str)

    args, unknown = parser.parse_known_args()
    execute_command(args.cluster, args.node, args.command, *unknown)

