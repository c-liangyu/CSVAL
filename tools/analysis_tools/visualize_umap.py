# Copyright (c) OpenMMLab. All rights reserved.
import argparse
import os.path as osp

import matplotlib.pyplot as plt
import mmcv
import numpy as np
import torch
import umap
from matplotlib import cm
from mmcv import Config, DictAction
from mmcv.parallel import MMDataParallel, MMDistributedDataParallel
from mmcv.runner import get_dist_info, init_dist, load_checkpoint

from mmselfsup.apis import set_random_seed
from mmselfsup.datasets import build_dataloader, build_dataset
from mmselfsup.models import build_algorithm
from mmselfsup.models.utils import ExtractProcess
from mmselfsup.utils import clustering as _clustering
from mmselfsup.utils import get_root_logger


def parse_args():
    parser = argparse.ArgumentParser(description='UMAP visualization')
    parser.add_argument('config', help='train config file path')
    parser.add_argument('--checkpoint', default=None, help='checkpoint file')
    parser.add_argument(
        '--work_dir', type=str, default=None, help='the dir to save results')
    parser.add_argument(
        '--launcher',
        choices=['none', 'pytorch', 'slurm', 'mpi'],
        default='none',
        help='job launcher')
    parser.add_argument(
        '--dataset_config',
        default='configs/benchmarks/classification/umap_imagenet.py',
        help='extract dataset config file path')
    parser.add_argument(
        '--layer_ind',
        type=str,
        default='0,1,2,3,4',
        help='layer indices, separated by comma, e.g., "0,1,2,3,4"')
    parser.add_argument(
        '--pool_type',
        choices=['specified', 'adaptive'],
        default='specified',
        help='Pooling type in :class:`MultiPooling`')
    parser.add_argument(
        '--max_num_class',
        type=int,
        default=20,
        help='the maximum number of classes to apply UMAP algorithms, now the'
        'function supports maximum 20 classes')
    parser.add_argument(
        '--max_num_sample_plot',
        type=int,
        default=20000,
        help='the maximum number of samples to plot.')
    parser.add_argument('--seed', type=int, default=0, help='random seed')
    parser.add_argument(
        '--deterministic',
        action='store_true',
        help='whether to set deterministic options for CUDNN backend.')
    parser.add_argument(
        '--cfg-options',
        nargs='+',
        action=DictAction,
        help='override some settings in the used config, the key-value pair '
        'in xxx=yyy format will be merged into config file. If the value to '
        'be overwritten is a list, it should be like key="[a,b]" or key=a,b '
        'It also allows nested list/tuple values, e.g. key="[(a,b),(c,d)]" '
        'Note that the quotation marks are necessary and that no white space '
        'is allowed.')

    # clustering settings
    parser.add_argument(
        '-k',
        type=int,
        default=30,
        help='k for k-means clustering, the categories of pseudo labels.')
    args = parser.parse_args()
    return args


def main():
    args = parse_args()

    cfg = Config.fromfile(args.config)
    if args.cfg_options is not None:
        cfg.merge_from_dict(args.cfg_options)
    # set cudnn_benchmark
    if cfg.get('cudnn_benchmark', False):
        torch.backends.cudnn.benchmark = True
    # work_dir is determined in this priority: CLI > segment in file > filename
    if args.work_dir is not None:
        # update configs according to CLI args if args.work_dir is not None
        cfg.work_dir = args.work_dir
    elif cfg.get('work_dir', None) is None:
        # use config filename as default work_dir if cfg.work_dir is None
        work_type = args.config.split('/')[1]
        cfg.work_dir = osp.join('./work_dirs', work_type,
                                osp.splitext(osp.basename(args.config))[0])

    # get out_indices from args
    layer_ind = [int(idx) for idx in args.layer_ind.split(',')]
    cfg.model.backbone.out_indices = layer_ind

    # init distributed env first, since logger depends on the dist info.
    if args.launcher == 'none':
        distributed = False
    else:
        distributed = True
        init_dist(args.launcher, **cfg.dist_params)

    # create work_dir and init the logger before other steps
    umap_work_dir = osp.join(cfg.work_dir, '')
    mmcv.mkdir_or_exist(osp.abspath(umap_work_dir))
    log_file = osp.join(umap_work_dir, 'extract.log')
    logger = get_root_logger(log_file=log_file, log_level=cfg.log_level)

    # set random seeds
    if args.seed is not None:
        logger.info(f'Set random seed to {args.seed}, '
                    f'deterministic: {args.deterministic}')
        set_random_seed(args.seed, deterministic=args.deterministic)

    # build the dataloader
    dataset_cfg = mmcv.Config.fromfile(args.dataset_config)
    dataset = build_dataset(dataset_cfg.data.extract)
    gt_labels = dataset.data_source.get_gt_labels()

    # compress dataset, select that the label is less then max_num_class
    tmp_infos = []
    for i in range(len(dataset)):
        if dataset.data_source.data_infos[i]['gt_label'] < args.max_num_class:
            tmp_infos.append(dataset.data_source.data_infos[i])
    dataset.data_source.data_infos = tmp_infos

    logger.info(f'Apply UMAP to visualize {len(dataset)} samples.')

    if 'imgs_per_gpu' in cfg.data:
        logger.warning('"imgs_per_gpu" is deprecated. '
                       'Please use "samples_per_gpu" instead')
        if 'samples_per_gpu' in cfg.data:
            logger.warning(
                f'Got "imgs_per_gpu"={cfg.data.imgs_per_gpu} and '
                f'"samples_per_gpu"={cfg.data.samples_per_gpu}, "imgs_per_gpu"'
                f'={cfg.data.imgs_per_gpu} is used in this experiments')
        else:
            logger.warning(
                'Automatically set "samples_per_gpu"="imgs_per_gpu"='
                f'{cfg.data.imgs_per_gpu} in this experiments')
        cfg.data.samples_per_gpu = cfg.data.imgs_per_gpu
    data_loader = build_dataloader(
        dataset,
        samples_per_gpu=dataset_cfg.data.samples_per_gpu,
        workers_per_gpu=dataset_cfg.data.workers_per_gpu,
        dist=distributed,
        shuffle=False)

    # build the model
    model = build_algorithm(cfg.model)
    model.init_weights()

    # model is determined in this priority: init_cfg > checkpoint > random
    if hasattr(cfg.model.backbone, 'init_cfg'):
        if getattr(cfg.model.backbone.init_cfg, 'type', None) == 'Pretrained':
            logger.info(
                f'Use pretrained model: '
                f'{cfg.model.backbone.init_cfg.checkpoint} to extract features'
            )
    elif args.checkpoint is not None:
        logger.info(f'Use checkpoint: {args.checkpoint} to extract features')
        load_checkpoint(model, args.checkpoint, map_location='cpu')
    else:
        logger.info('No pretrained or checkpoint is given, use random init.')

    if not distributed:
        model = MMDataParallel(model, device_ids=[0])
    else:
        model = MMDistributedDataParallel(
            model.cuda(),
            device_ids=[torch.cuda.current_device()],
            broadcast_buffers=False)

    # build extraction processor and run
    extractor = ExtractProcess(
        pool_type=args.pool_type, backbone='resnet50', layer_indices=layer_ind)
    features = extractor.extract(model, data_loader, distributed=distributed)

    # save features
    mmcv.mkdir_or_exist(f'{umap_work_dir}features/')
    logger.info(f'Save features to {umap_work_dir}features/')
    if distributed:
        rank, _ = get_dist_info()
        if rank == 0:
            for key, val in features.items():
                output_file = \
                    f'{umap_work_dir}features/{dataset_cfg.name}_{key}.npy'
                np.save(output_file, val)
    else:
        for key, val in features.items():
            output_file = \
                f'{umap_work_dir}features/{dataset_cfg.name}_{key}.npy'
            np.save(output_file, val)

    # clustering
    clustering = dict(type='Kmeans', k=args.k, pca_dim=256)
    clustering_algo = _clustering.__dict__[clustering.pop('type')](
        **clustering)
    logger.info('Running clustering......')
    # Features are normalized during clustering
    clustering_algo.cluster(features['feat5'], verbose=True)
    assert isinstance(clustering_algo.labels, np.ndarray)
    clustering_pseudo_labels = clustering_algo.labels.astype(np.int64)
    # save clustering_pseudo_labels
    mmcv.mkdir_or_exist(f'{umap_work_dir}clustering_pseudo_labels/')
    output_file = \
        f'{umap_work_dir}clustering_pseudo_labels/{dataset_cfg.name}.npy'
    np.save(output_file, clustering_pseudo_labels)

    # build UMAP model
    reducer = umap.UMAP()

    # run and get results
    mmcv.mkdir_or_exist(f'{umap_work_dir}saved_pictures/')
    logger.info('Running UMAP......')
    if len(dataset) > args.max_num_sample_plot:
        indices = np.random.permutation(
            len(dataset))[:args.max_num_sample_plot]
    else:
        indices = np.arange(len(dataset))
    for key, val in features.items():
        result = reducer.fit_transform(val)
        res_min, res_max = result.min(0), result.max(0)
        res_norm = (result - res_min) / (res_max - res_min)
        plt.figure(figsize=(10, 10))
        plt.scatter(
            res_norm[indices, 0],
            res_norm[indices, 1],
            alpha=1.0,
            s=15,
            c=gt_labels[indices],
            cmap='tab20')
        plt.savefig(f'{umap_work_dir}saved_pictures/{key}_gt_labels.png')
        plt.figure(figsize=(10, 10))
        plt.scatter(
            res_norm[indices, 0],
            res_norm[indices, 1],
            alpha=1.0,
            s=15,
            c=clustering_pseudo_labels[indices],
            cmap=cm.get_cmap('nipy_spectral', args.k))
        plt.savefig(
            f'{umap_work_dir}saved_pictures/{key}_kmeans_psuedo_labels.png')
    logger.info(f'Saved results to {umap_work_dir}saved_pictures/')


if __name__ == '__main__':
    main()
