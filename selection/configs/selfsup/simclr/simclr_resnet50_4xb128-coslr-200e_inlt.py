_base_ = [
    '../_base_/datasets/imagenetlt_simclr.py',
    '../_base_/simclr_runtime.py',
]

model = dict(backbone=dict(with_cp=True))

optimizer = dict(
    type='LARS',
    lr=0.6,  # 0.3*batch_size/256
    weight_decay=1e-6,
    momentum=0.9)

log_config = dict(interval=1)

# fp16
fp16 = dict(loss_scale='dynamic')
