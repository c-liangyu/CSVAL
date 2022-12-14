# Copyright (c) OpenMMLab. All rights reserved.
import os.path as osp
import pickle

import numpy as np
import torch.distributed as dist
from mmcv.runner import get_dist_info

from ..builder import DATASOURCES
from ..utils import check_integrity, download_and_extract_archive
from .base import BaseDataSource


@DATASOURCES.register_module()
class CIFAR10(BaseDataSource):
    """`CIFAR10 <https://www.cs.toronto.edu/~kriz/cifar.html>`_ Dataset.

    This implementation is modified from
    https://github.com/pytorch/vision/blob/master/torchvision/datasets/cifar.py
    """  # noqa: E501

    base_folder = 'cifar-10-batches-py'
    url = 'https://www.cs.toronto.edu/~kriz/cifar-10-python.tar.gz'
    filename = 'cifar-10-python.tar.gz'
    tgz_md5 = 'c58f30108f718f92721af3b95e74349a'
    train_list = [
        ['data_batch_1', 'c99cafc152244af753f735de768cd75f'],
        ['data_batch_2', 'd4bba439e000b95fd0a9bffe97cbabec'],
        ['data_batch_3', '54ebc095f3ab1f0389bbae665268c751'],
        ['data_batch_4', '634d18415352ddfa80567beed471001a'],
        ['data_batch_5', '482c414d41f54cd18b22e5b47cb7c3cb'],
    ]

    test_list = [
        ['test_batch', '40351d587109b95175f43aff81a1287e'],
    ]
    meta = {
        'filename': 'batches.meta',
        'key': 'label_names',
        'md5': '5ff9c542aee3614f3951f8cda6e48888',
    }
    label_dict = {
        '0': 'airplane',
        '1': 'automobile',
        '2': 'bird',
        '3': 'cat',
        '4': 'deer',
        '5': 'dog',
        '6': 'frog',
        '7': 'horse',
        '8': 'ship',
        '9': 'truck'
    }

    def load_annotations(self):

        rank, world_size = get_dist_info()

        if rank == 0 and not self._check_integrity():
            download_and_extract_archive(
                self.url,
                self.data_prefix,
                filename=self.filename,
                md5=self.tgz_md5)

        if world_size > 1:
            dist.barrier()
            assert self._check_integrity(), \
                'Shared storage seems unavailable. ' \
                f'Please download the dataset manually through {self.url}.'

        if not self.test_mode:
            downloaded_list = self.train_list
        else:
            downloaded_list = self.test_list

        self.imgs = []
        self.gt_labels = []

        # load the picked numpy arrays
        for file_name, checksum in downloaded_list:
            file_path = osp.join(self.data_prefix, self.base_folder, file_name)
            with open(file_path, 'rb') as f:
                entry = pickle.load(f, encoding='latin1')
                self.imgs.append(entry['data'])
                if 'labels' in entry:
                    self.gt_labels.extend(entry['labels'])
                else:
                    self.gt_labels.extend(entry['fine_labels'])

        self.imgs = np.vstack(self.imgs).reshape(-1, 3, 32, 32)
        self.imgs = self.imgs.transpose((0, 2, 3, 1))  # convert to HWC

        self._load_meta()

        data_infos = []
        for i, (img, gt_label) in enumerate(zip(self.imgs, self.gt_labels)):
            gt_label = np.array(gt_label, dtype=np.int64)
            info = {'img': img, 'gt_label': gt_label, 'idx': i}
            data_infos.append(info)
        return data_infos

    def _load_meta(self):
        path = osp.join(self.data_prefix, self.base_folder,
                        self.meta['filename'])
        if not check_integrity(path, self.meta['md5']):
            raise RuntimeError(
                'Dataset metadata file not found or corrupted.' +
                ' You can use download=True to download it')
        with open(path, 'rb') as infile:
            data = pickle.load(infile, encoding='latin1')
            self.CLASSES = data[self.meta['key']]

    def _check_integrity(self):
        root = self.data_prefix
        for fentry in (self.train_list + self.test_list):
            filename, md5 = fentry[0], fentry[1]
            fpath = osp.join(root, self.base_folder, filename)
            if not check_integrity(fpath, md5):
                return False
        return True


@DATASOURCES.register_module()
class CIFAR100(CIFAR10):
    """`CIFAR100 <https://www.cs.toronto.edu/~kriz/cifar.html>`_ Dataset."""

    base_folder = 'cifar-100-python'
    url = 'https://www.cs.toronto.edu/~kriz/cifar-100-python.tar.gz'
    filename = 'cifar-100-python.tar.gz'
    tgz_md5 = 'eb9058c3a382ffc7106e4002c42a8d85'
    train_list = [
        ['train', '16019d7e3df5f24257cddd939b257f8d'],
    ]

    test_list = [
        ['test', 'f0ef6b0ae62326f3e7ffdfab6717acfc'],
    ]
    meta = {
        'filename': 'meta',
        'key': 'fine_label_names',
        'md5': '7973b15100ade9c7d40fb424638fde48',
    }


@DATASOURCES.register_module()
class CIFAR10LT(CIFAR10):
    cls_num = 10

    def load_annotations(self):

        rank, world_size = get_dist_info()

        if rank == 0 and not self._check_integrity():
            download_and_extract_archive(
                self.url,
                self.data_prefix,
                filename=self.filename,
                md5=self.tgz_md5)

        if world_size > 1:
            dist.barrier()
            assert self._check_integrity(), \
                'Shared storage seems unavailable. ' \
                f'Please download the dataset manually through {self.url}.'

        if not self.test_mode:
            downloaded_list = self.train_list
        else:
            downloaded_list = self.test_list

        self.imgs = []
        self.gt_labels = []

        # load the picked numpy arrays
        for file_name, checksum in downloaded_list:
            file_path = osp.join(self.data_prefix, self.base_folder, file_name)
            with open(file_path, 'rb') as f:
                entry = pickle.load(f, encoding='latin1')
                self.imgs.append(entry['data'])
                if 'labels' in entry:
                    self.gt_labels.extend(entry['labels'])
                else:
                    self.gt_labels.extend(entry['fine_labels'])

        self.imgs = np.vstack(self.imgs).reshape(-1, 3, 32, 32)
        self.imgs = self.imgs.transpose((0, 2, 3, 1))  # convert to HWC

        img_num_list = self.get_img_num_per_cls(
            cls_num=10, imb_type='exp', imb_factor=0.01)
        self.gen_imbalanced_data(img_num_list)

        self._load_meta()

        data_infos = []
        for i, (img, gt_label) in enumerate(zip(self.imgs, self.gt_labels)):
            gt_label = np.array(gt_label, dtype=np.int64)
            info = {'img': img, 'gt_label': gt_label, 'idx': i}
            data_infos.append(info)
        return data_infos

    def get_img_num_per_cls(
        self,
        cls_num=10,
        imb_type='exp',
        imb_factor=0.01,
    ):
        img_max = len(self.imgs) / cls_num
        img_num_per_cls = []
        if imb_type == 'exp':
            for cls_idx in range(cls_num):
                num = img_max * (imb_factor**(cls_idx / (cls_num - 1.0)))
                img_num_per_cls.append(int(num))
        elif imb_type == 'step':
            for cls_idx in range(cls_num // 2):
                img_num_per_cls.append(int(img_max))
            for cls_idx in range(cls_num // 2):
                img_num_per_cls.append(int(img_max * imb_factor))
        else:
            img_num_per_cls.extend([int(img_max)] * cls_num)
        return img_num_per_cls

    def gen_imbalanced_data(self, img_num_per_cls):
        new_data = []
        new_targets = []
        targets_np = np.array(self.gt_labels, dtype=np.int64)
        classes = np.unique(targets_np)
        # np.random.shuffle(classes)
        self.num_per_cls_dict = dict()
        total_selec_idx = []
        for the_class, the_img_num in zip(classes, img_num_per_cls):
            self.num_per_cls_dict[the_class] = the_img_num
            idx = np.where(targets_np == the_class)[0]
            np.random.shuffle(idx)
            selec_idx = idx[:the_img_num]
            total_selec_idx.extend(selec_idx)
            new_data.append(self.imgs[selec_idx, ...])
            new_targets.extend([
                the_class,
            ] * the_img_num)
        new_data = np.vstack(new_data)
        self.imgs = new_data
        self.gt_labels = new_targets

    def get_cls_num_list(self):
        cls_num_list = []
        for i in range(self.cls_num):
            cls_num_list.append(self.num_per_cls_dict[i])
        return cls_num_list
