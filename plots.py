#!/bin/python3
# Copyright (c) Open Enclave SDK contributors.
# Licensed under the MIT License

import pandas as pd
import math
import matplotlib.pyplot as plt
import os
import seaborn as sns
import sys

df = pd.read_csv('data.csv')

pd.set_option('display.max_rows', None)
pd.set_option('display.max_columns', None)
pd.set_option('display.width', 1000)
pd.set_option('display.colheader_justify', 'center')
pd.set_option('display.precision', 3)

# Remove columns that have constant values
def remove_constant_columns(df):
    for c in df.columns.copy():
        col = df[c]
        is_same = col.eq(col[0]).all()
        if is_same:
            df = df.drop(c, axis=1)
    return df

# Trim the table
df = remove_constant_columns(df)
df = df.drop('BW', axis=1)

# Find list of nodes and runtimes. Order so that runc comes before kata.
ctr_runtimes = sorted(df['ctr-runtime'].unique(), reverse=True)
node_types   = sorted(df['node'].unique())
readwrites   = list(df['readwrite'].unique())
ops          = list(df['op'].unique())
metrics      = ['BW (MB/s)', 'IOPS']

palette = 'pastel'
fsize  = (9, 11)
aspect = fsize[0]*1.0/fsize[1]

figures_dir = 'figures'
os.makedirs(figures_dir, exist_ok=True)

ylabels = {
    metrics[0] : 'Bandwidth (MB/s)',
    metrics[1] : 'Number of IOPS per second'
}

metric_names = {
    metrics[0] : 'Bandwidth',
    metrics[1] : 'IOPS/sec'
}

def make_descriptive(readwrite, op):
    if readwrite == 'randrw':
        op_name = 'RandRW ' + ('Read' if op == 'read' else 'Write')
    else:
        op_name = 'RandRead' if readwrite == 'randread' else 'RandWrite'

    return op_name


def gen_cat_plots(df, readwrite, op, metric):
    # Select records with given filters and make a copy.
    df = df[(df['readwrite'] == readwrite) & (df['op'] == op)].copy()

    if len(df) == 0:
        return

    op_name = make_descriptive(readwrite, op)
    title = '%s %s' % (op_name, metric_names[metric])

    hue_cols = ['ctr-runtime']
    hue = hue_cols[0] if len(hue_cols) == 1 else df[hue_cols].apply(tuple, axis=1)
    col = 'numjobs'

    sns.set_theme(style="whitegrid", font_scale=1.5, rc={'figure.figsize':fsize})

    g = sns.catplot(
        showfliers = False, # Outliers will be drawn via strip plot
        palette = palette,
        data = df,
        x = 'node',
        hue = hue,
        y = metric,
        dodge = True,
        whis=[0, 100],
        kind='box',
#        k_depth='full',
        col = 'numjobs',
        aspect = aspect,
        height = fsize[1],
        sharey = True,
        hue_order=ctr_runtimes
    )

    ax = g.map_dataframe(
        sns.swarmplot,
#        jitter = True, # Make it easy to see different points
        size = 4,
        data=df,
        hue=hue,
        x = 'node',
        y = metric,
        dodge = True,
        ec='k',
        hue_order=ctr_runtimes
    )

    ax.set_xticklabels(rotation=45, horizontalalignment='right')
    g.fig.suptitle(title, y=1.05)
    filename = (op_name + metric + 'Cat').replace(' ', '').replace('(MB/s)', '') + '.png'
    g.fig.savefig(os.path.join(figures_dir, filename), bbox_inches='tight')
    plt.close()
    
# Generate box and strip plots
def gen_box_plots(df, readwrite, op, metric):

    # Select records with given filters and make a copy.
    df = df[(df['readwrite'] == readwrite) & (df['op'] == op)].copy()

    if len(df) == 0:
        return

    op_name = make_descriptive(readwrite, op)
    title = '%s %s' % (op_name, metric_names[metric])

    hue_cols = ['ctr-runtime']
    hue = hue_cols[0] if len(hue_cols) == 1 else df[hue_cols].apply(tuple, axis=1)

    sns.set_theme(style="whitegrid", font_scale=1.5, rc={'figure.figsize':fsize})
    ax = sns.boxplot(
        showfliers = False, # Outliers will be drawn via strip plot
        palette = palette,
        data = df,
        x = 'node',
        hue = hue,
        y = metric,
        dodge = True,
        whis=[0, 100],
        hue_order=ctr_runtimes,
    )
    ax.set(
        title  = title,
        xlabel = '',
        ylabel = ylabels[metric]
    )

    # Overlay strip plot
    sns.stripplot(
        jitter = True, # Make it easy to see different points
        size = 6,
        data = df,
        x = 'node',
        hue = hue,
        y = metric,
        dodge = True,
        ec='k',
        hue_order=ctr_runtimes,
        ax=ax,
    )

    # Remove duplicate labels
    handles, labels = ax.get_legend_handles_labels()

    nlegends = 1
    for h in hue_cols:
        nlegends *= len(df[h].unique())

    # When creating the legend, only use the first two elements
    # to effectively remove the last two.
    plt.legend(handles[0:nlegends], labels[0:nlegends], borderaxespad=0.)

    filename = (op_name + metric).replace(' ', '').replace('(MB/s)', '') + '.png'
    ax.get_figure().savefig(os.path.join(figures_dir, filename))
    plt.close()

for readwrite in readwrites:
    for op in ops:
        for metric in metrics:
            gen_box_plots(df, readwrite, op, metric)
            gen_cat_plots(df, readwrite, op, metric)

# def gen_cat_plots(df, readwrite, op, metric):
#     # Select records with given filters and make a copy.
#     df = df[(df['readwrite'] == readwrite) & (df['op'] == op)].copy()

#     if len(df) == 0:
#         return

#     op_name = make_descriptive(readwrite, op)
#     title = '%s %s' % (op_name, metric_names[metric])

#     hue_cols = ['ctr-runtime']
#     hue = hue_cols[0] if len(hue_cols) == 1 else df[hue_cols].apply(tuple, axis=1)
#     col = 'numjobs'

#     sns.set_theme(style="whitegrid", font_scale=1.5, rc={'figure.figsize':fsize})

#     g = sns.catplot(
#         showfliers = False, # Outliers will be drawn via strip plot
#         palette = palette,
#         data = df,
#         x = 'bs',
#         hue = hue,
#         y = metric,
#         dodge = True,
# #        whis=[0, 100],
#         kind='violin',
# #        k_depth='full',
#         col = col,
#         aspect = aspect,
#         height = fsize[1],
#         sharey = True,
#         hue_order=ctr_runtimes
#     )

#     ax = g.map_dataframe(
#         sns.swarmplot,
# #        jitter = True, # Make it easy to see different points
#         size = 4,
#         data=df,
#         hue=hue,
#         x = 'bs',
#         y = metric,
#         dodge = True,
#         ec='k',
#         hue_order=ctr_runtimes
#     )

#     ax.set_xticklabels(rotation=45, horizontalalignment='right')
#     g.fig.suptitle(title, y=1.05)
#     filename = (op_name + metric + 'Cat').replace(' ', '').replace('(MB/s)', '') + '.png'
#     #g.fig.savefig(os.path.join(figures_dir, filename), bbox_inches='tight')
#     plt.show()

# gen_cat_plots(df, 'randread', 'read', metrics[0])
