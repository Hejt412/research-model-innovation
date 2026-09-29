"""Do not import or execute. This is an analysis-only fixture."""
raise RuntimeError('TRAINING_ENTRY_MUST_NOT_RUN')

model_class = 'Baseline'
optimizer = 'Adam'
lr = 0.001
loss = 'cross_entropy'
seeds = [11, 22, 33]
