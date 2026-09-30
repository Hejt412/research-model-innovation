"""Synthetic source supplied for static review only."""
raise RuntimeError("Read this fixture as source; do not import or execute it")

import math
import torch
from torch import nn
from torch.nn import functional as F


class TwoStreamBaseline(nn.Module):
    def __init__(self):
        super().__init__()
        self.left = nn.Linear(16, 32, bias=True)
        self.right = nn.Linear(16, 32, bias=True)
        self.head = nn.Linear(64, 4, bias=True)

    def representations(self, x, y):
        return torch.relu(self.left(x)), torch.relu(self.right(y))

    def forward(self, x, y, enabled=True):
        a, b = self.representations(x, y)
        return self.head(torch.cat((a, b), dim=-1))


class CrossGate(TwoStreamBaseline):
    def __init__(self):
        super().__init__()
        self.down = nn.Linear(32, 2, bias=False)
        self.up = nn.Linear(2, 32, bias=False)
        nn.init.normal_(self.down.weight, mean=0.0, std=1.0 / math.sqrt(32))
        nn.init.zeros_(self.up.weight)

    def forward(self, x, y, enabled=True):
        a, b = self.representations(x, y)
        if enabled:
            delta_a = a * torch.tanh(self.up(self.down(b)))
            delta_b = b * torch.tanh(self.up(self.down(a)))
            a, b = a + delta_a, b + delta_b
        return self.head(torch.cat((a, b), dim=-1))


class CrossValue(TwoStreamBaseline):
    def __init__(self):
        super().__init__()
        self.down = nn.Linear(32, 2, bias=False)
        self.up = nn.Linear(2, 32, bias=False)
        nn.init.normal_(self.down.weight, mean=0.0, std=1.0 / math.sqrt(32))
        nn.init.zeros_(self.up.weight)

    def forward(self, x, y, enabled=True):
        a, b = self.representations(x, y)
        if enabled:
            delta_a = self.up(torch.tanh(self.down(b)))
            delta_b = self.up(torch.tanh(self.down(a)))
            a, b = a + delta_a, b + delta_b
        return self.head(torch.cat((a, b), dim=-1))


class DenseCrossGate(TwoStreamBaseline):
    def __init__(self):
        super().__init__()
        self.gate = nn.Linear(32, 32, bias=True)
        nn.init.zeros_(self.gate.weight)
        nn.init.zeros_(self.gate.bias)

    def forward(self, x, y, enabled=True):
        a, b = self.representations(x, y)
        if enabled:
            delta_a = a * torch.tanh(self.gate(b))
            delta_b = b * torch.tanh(self.gate(a))
            a, b = a + delta_a, b + delta_b
        return self.head(torch.cat((a, b), dim=-1))


def training_loss(model, x, y, target):
    return F.cross_entropy(model(x, y, enabled=True), target)


def make_optimizer(model):
    return torch.optim.SGD(
        model.parameters(), lr=0.02, momentum=0.0, weight_decay=0.0
    )
