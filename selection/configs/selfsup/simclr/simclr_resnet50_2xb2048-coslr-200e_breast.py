_base_ = [
    '../_base_/datasets/medmnist/breastmnist_simclr.py',
    '../_base_/simclr_runtime.py',
]

# model settings
model = dict(backbone=dict(in_channels=1))
