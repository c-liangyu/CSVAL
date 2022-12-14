# optimizer
optimizer = dict(
    type='SGD',
    #  lr=0.03, # base lr
    lr=0.48,  # lr at bs of 4096
    weight_decay=1e-4,
    momentum=0.9)
optimizer_config = dict()  # grad_clip, coalesce, bucket_size_mb

# learning policy
lr_config = dict(
    policy='CosineAnnealing',
    min_lr=0.,
    warmup='linear',
    warmup_iters=5,
    warmup_ratio=1e-4,  # cannot be 0
    warmup_by_epoch=True)

# runtime settings
runner = dict(type='EpochBasedRunner', max_epochs=200)
