# Copyright (c) OpenMMLab. All rights reserved.
import argparse
import math
import os
import os.path as osp

import matplotlib
import matplotlib.pyplot as plt
import mmcv
import numpy as np
import orjson as json
import pandas as pd
import seaborn as sns
from mmcv import Config
from tqdm import tqdm

from mmselfsup.apis import set_random_seed
from mmselfsup.datasets import build_dataset
from mmselfsup.utils import get_root_logger


def parse_args():
    parser = argparse.ArgumentParser(description='visualize cartography')
    parser.add_argument('config', help='train config file path')
    parser.add_argument(
        '--work_dir', type=str, default=None, help='the dir to save results')
    parser.add_argument(
        '--plot_title', default=None, type=str, help='Plot caption')
    parser.add_argument(
        '--split',
        type=str,
        default='training',
        help='Dataset split whose training dynamics to read')
    parser.add_argument(
        '--temperature',
        type=float,
        default='0.01',
        help='Temperature of softmax at calculating cartography')
    parser.add_argument('--seed', type=int, default=0, help='random seed')
    parser.add_argument(
        '--dataset_config',
        default='configs/benchmarks/classification/tsne_imagenet.py',
        help='extract dataset config file path')
    parser.add_argument(
        '--max_num_sample_plot',
        type=int,
        default=25000,
        help='the maximum number of samples to plot.')
    parser.add_argument(
        '--num_epochs',
        type=int,
        help='num of epochs to read from training dynamics.')
    parser.add_argument(
        '--overwrite_train_dy',
        action='store_true',
        help='Whether to overwrite previously computed training dynamics')
    parser.add_argument(
        '--include_ci',
        action='store_true',
        help='Compute the confidence interval for variability.')
    parser.add_argument(
        '--bound',
        type=bool,
        default=False,
        help='Whether to draw the theoretical upper bound')
    args = parser.parse_args()
    return args


def read_training_dynamics(
    args,
    logger,
    work_dir,
    id_field='idx',
    split='training',
    num_epochs=None,
):
    """
    Given path to logged training dynamics, merge stats across epochs.
    Returns:
    - Dict between ID of a train instances and its gold label,
    and the list of prob across epochs.
    """
    train_dynamics = {}

    td_dir = osp.join(work_dir, f'{split}_dynamics',
                      f'{str(args.temperature)}')
    if num_epochs is None:
        num_epochs = len([
            f for f in os.listdir(td_dir)
            if os.path.isfile(os.path.join(td_dir, f))
        ])

    logger.info(f'Reading {num_epochs} files from {td_dir} ...')
    for epoch_num in tqdm(range(num_epochs)):
        epoch_file = os.path.join(td_dir, f'dynamics_epoch_{epoch_num}.jsonl')
        assert os.path.exists(epoch_file)

        with open(epoch_file, 'r') as infile:
            for line in infile:
                record = json.loads(line.strip())
                idx = record[id_field]
                if idx not in train_dynamics:
                    # assert epoch_num == 0
                    train_dynamics[idx] = {'prob': []}
                train_dynamics[idx]['prob'].append(
                    record[f'prob_epoch_{epoch_num}'])

    logger.info(
        f'Read training dynamics for {len(train_dynamics)} {split} instances.')
    return train_dynamics


def compute_train_dy_metrics(logger, training_dynamics, args):
    """
    Given the training dynamics (prob for each training
    instance across epochs), compute metrics
    based on it, for data map coorodinates.
    Computed metrics are: confidence, variability
    the last two being baselines from prior work
    (Example Forgetting: https://arxiv.org/abs/1812.05159 and
    Active Bias: https://arxiv.org/abs/1704.07433 respectively).
    Returns:
    - DataFrame with these metrics.
    - DataFrame with more typical training evaluation metrics,
    such as accuracy / loss.
    """
    confidence_ = {}
    variability_ = {}

    # Functions to be applied to the data.
    def variability_func(conf):
        return np.std(conf)

    # Based on prior work on active bias (https://arxiv.org/abs/1704.07433)
    if args.include_ci:

        def variability_func(conf):  # noqa: F811
            return np.sqrt(
                np.var(conf) + np.var(conf) * np.var(conf) / (len(conf) - 1))

    num_tot_epochs = np.max(
        [len(record['prob']) for record in training_dynamics.values()])
    logger.info(f'Computing training dynamics across {num_tot_epochs} epochs')
    logger.info('Metrics computed: confidence, variability')

    for idx in tqdm(training_dynamics):
        record = training_dynamics[idx]
        # # skip examples that do not have training dynamics for all epochs
        # if len(record['prob']) < num_tot_epochs:
        #     continue
        confidence_[idx] = np.mean(record['prob'])
        variability_[idx] = variability_func(record['prob'])

    column_names = ['idx', 'confidence', 'variability']
    df = pd.DataFrame([[
        idx,
        confidence_[idx],
        variability_[idx],
    ] for i, idx in enumerate(training_dynamics.keys())],
                      columns=column_names)
    return df.sort_values('idx')


def plot_data_map(args,
                  logger,
                  dataframe,
                  plot_dir,
                  dataset_name,
                  gt_labels,
                  plot_title=None,
                  show_hist=False,
                  max_num_sample_plot=20000,
                  show_bound=False):
    # Set style.
    sns.set(style='whitegrid', font_scale=4, context='paper')
    plt.rcParams['axes.linewidth'] = 2
    logger.info(f'Plotting figure for {dataset_name} ...')

    dataframe = dataframe.sort_values('idx')
    dataframe['gt_label'] = gt_labels

    np.save(
        os.path.join(plot_dir, 'ambiguous_sorted_idx.npy'),
        dataframe.sort_values('variability', ascending=False)['idx'])
    np.save(
        os.path.join(plot_dir, 'easy_sorted_idx.npy'),
        dataframe.sort_values('confidence', ascending=False)['idx'])
    np.save(
        os.path.join(plot_dir, 'hard_sorted_idx.npy'),
        dataframe.sort_values('variability')['idx'])

    # Subsample data to plot, so the plot is not too busy.
    dataframe = dataframe.sample(
        n=max_num_sample_plot
        if dataframe.shape[0] > max_num_sample_plot else len(dataframe))

    main_metric = 'variability'
    other_metric = 'confidence'

    hue = 'gt_label'
    num_hues = len(dataframe[hue].unique().tolist())
    style = None

    if not show_hist:
        fig, ax0 = plt.subplots(1, 1, figsize=(7.08, 9.9))
    else:
        fig = plt.figure(figsize=(14, 10))
        gs = fig.add_gridspec(3, 2, width_ratios=[5, 1])
        ax0 = fig.add_subplot(gs[:, 0])
    ax0.set_ylim(bottom=0)

    my_pal = [
        '#e60049', '#0bb4ff', '#50e991', '#e6d800', '#9b19f5', '#ffa300',
        '#dc0ab4', '#b3d4ff', '#00bfa0', '#fdcce5', '#1a53ff'
    ]
    pal = sns.color_palette(my_pal, n_colors=num_hues)

    dataframe = dataframe.sort_values('gt_label')
    plot = sns.scatterplot(
        x=main_metric,
        y=other_metric,
        ax=ax0,
        data=dataframe,
        hue=hue,
        palette=pal,
        style=style,
        alpha=0.3,
        s=30)

    locator = matplotlib.ticker.MaxNLocator(
        nbins=5)  # with 3 bins you will have 4 ticks
    ax0.yaxis.set_major_locator(locator)

    # Annotate Regions.
    def bb(c):
        return dict(boxstyle='round,pad=0.3', ec=c, lw=2, fc='white')

    def func_annotate(text, xyc, bbc):
        return ax0.annotate(
            text,
            xy=xyc,
            xycoords='axes fraction',
            fontsize=25,
            color='black',
            va='center',
            ha='center',
            rotation=350,
            bbox=bb(bbc))

    # _ = func_annotate('ambiguous', xyc=(0.9, 0.5), bbc='white')
    # _ = func_annotate('easy-to-contrast', xyc=(0.40, 0.85), bbc='white')
    # _ = func_annotate('hard-to-contrast', xyc=(0.35, 0.25), bbc='white')
    if show_bound:

        def bound(conf):
            return math.sqrt(
                math.floor(5 * conf) / 5.0 +
                (math.floor(5 * conf) - 5 * conf)**2 / 5.0 - conf**2)

        confs = list(np.arange(0, 1, 0.01))
        plt.plot([bound(conf) for conf in confs],
                 confs,
                 linewidth=2.0,
                 label='x=f(y, 5)',
                 color='black')

    if not show_hist:
        # handles, labels = plot.get_legend_handles_labels()
        # alphabetical_order = np.argsort(labels)
        # sorted_handles = np.array(handles)[alphabetical_order]
        # sorted_labels = np.array(labels)[alphabetical_order]
        # plot.legend(sorted_handles, sorted_labels,
        #             fancybox=True, shadow=True,  ncol=1,
        #             loc='upper center',
        #             fontsize=5,
        #             bbox_to_anchor=(0.5, -0.05),
        #             )
        leg = plt.legend()
        leg.remove()
    else:
        handles, labels = plot.get_legend_handles_labels()
        plot.legend(
            reversed(handles),
            reversed(labels),
            title='GT label',
            fancybox=True,
            shadow=True,
            ncol=1)
    plot.set_xlabel('variability')
    plot.set_ylabel('confidence')

    if not plot_title:
        plot_title = f'{dataset_name} Data Map'
    # plot.set_title(plot_title, fontsize=17)

    if show_hist:
        # Make the histograms.
        ax1 = fig.add_subplot(gs[0, 1])
        ax2 = fig.add_subplot(gs[1, 1])
        ax3 = fig.add_subplot(gs[2, 1])

        plott0 = dataframe.hist(column=['confidence'], ax=ax1, color='#622a87')
        plott0[0].set_title('')
        plott0[0].set_xlabel('confidence')
        plott0[0].set_ylabel('density')

        plott1 = dataframe.hist(column=['variability'], ax=ax2, color='teal')
        plott1[0].set_title('')
        plott1[0].set_xlabel('variability')
        plott1[0].set_ylabel('density')

        plot2 = sns.countplot(
            x='correct.', data=dataframe, ax=ax3, color='#86bf91')
        ax3.xaxis.grid(True)  # Show the vertical gridlines

        plot2.set_title('')
        plot2.set_xlabel('correctness')
        plot2.set_ylabel('density')
        plot2.tick_params(axis='x', rotation=60)

    fig.tight_layout(pad=0.1)
    filename = osp.join(
        f'{plot_dir}',
        f'{dataset_name}_{str(args.temperature)}_pseudo_label.png'
    )  # noqa E501
    fig.savefig(filename)
    logger.info(f'Plot saved to {filename}')
    fig.show()


def main():
    args = parse_args()

    cfg = Config.fromfile(args.config)
    dataset_cfg = mmcv.Config.fromfile(args.dataset_config)
    dataset = build_dataset(dataset_cfg.data.extract)
    gt_label_digit = dataset.data_source.get_gt_labels()
    if dataset.data_source.__class__.__name__.endswith('MNIST'):  # medmnist
        label_dict = dataset.data_source.info['label']
    else:  # cifar
        label_dict = dataset.data_source.label_dict
    gt_labels = [label_dict[str(digit)] for digit in gt_label_digit]

    if args.work_dir is not None:
        # update configs according to CLI args if args.work_dir is not None
        work_type = args.config.split('/')[1]
        cfg.work_dir = args.work_dir
    elif cfg.get('work_dir', None) is None:
        # use config filename as default work_dir if cfg.work_dir is None
        work_type = args.config.split('/')[1]
        cfg.work_dir = osp.join('./work_dirs', work_type,
                                osp.splitext(osp.basename(args.config))[0],
                                'cartography')
    mmcv.mkdir_or_exist(cfg.work_dir)
    log_file = osp.join(cfg.work_dir, 'extract_and_visualize.log')
    logger = get_root_logger(log_file=log_file, log_level=cfg.log_level)
    # set random seeds
    if args.seed is not None:
        logger.info(f'Set random seed to {args.seed}, ')
        set_random_seed(args.seed)

    # extract metrics
    train_dy_filename = osp.join(
        cfg.work_dir, f'{args.split}_{str(args.temperature)}_td_metrics.jsonl')
    if args.overwrite_train_dy or not os.path.exists(train_dy_filename):
        training_dynamics_work_dir = osp.dirname(cfg.work_dir)
        training_dynamics = read_training_dynamics(
            args=args,
            logger=logger,
            work_dir=training_dynamics_work_dir,
            split=args.split,
            num_epochs=args.num_epochs)
        train_dy_metrics = compute_train_dy_metrics(logger, training_dynamics,
                                                    args)
        train_dy_metrics.to_json(
            train_dy_filename, orient='records', lines=True)
        logger.info(f'Metrics for {args.split} data based on training'
                    f' dynamics written to {train_dy_filename}')
    else:
        logger.info(f'Read metrics for {args.split} data based on training '
                    f'dynamics from {train_dy_filename}')
        train_dy_metrics = pd.read_json(train_dy_filename, lines=True)

    # plot cartography
    plot_data_map(
        args,
        logger,
        train_dy_metrics,
        cfg.work_dir,
        dataset_name=dataset_cfg.name,
        gt_labels=gt_labels,
        max_num_sample_plot=args.max_num_sample_plot,
        plot_title=args.plot_title,
        show_bound=args.bound)


if __name__ == '__main__':
    main()
