_base_ = [
    '../_base_/datasets/medmnist/dermamnist_simclr.py',
    '../_base_/medmnist_simclr_runtime.py',
]

# fp16
fp16 = dict(loss_scale='dynamic')
