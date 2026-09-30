"""Synthetic source supplied for static review only."""
raise RuntimeError("Read this fixture as source; do not import or execute it")

import torch
from torch import nn
from torch.nn import functional as F


class ResidualClassifier(nn.Module):
    def __init__(self):
        super().__init__()
        self.encoder = nn.Linear(16, 32, bias=True)
        self.head = nn.Linear(32, 4, bias=True)
        self.down = nn.Linear(32, 2, bias=False)
        self.up = nn.Linear(2, 32, bias=False)
        nn.init.zeros_(self.down.weight)
        nn.init.zeros_(self.up.weight)

    def forward(self, x, enabled=True):
        h = torch.relu(self.encoder(x))
        if enabled:
            h = h + self.up(self.down(h))
        return self.head(h)


def training_loss(model, x, target):
    logits = model(x, enabled=True)
    return F.cross_entropy(logits, target)


def make_optimizer(model):
    return torch.optim.SGD(
        model.parameters(), lr=0.02, momentum=0.0, weight_decay=0.0
    )
