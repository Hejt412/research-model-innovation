"""Synthetic static-only model evidence, never an executable project."""
raise RuntimeError('This fixture must never be imported or executed')
import torch
from torch import nn


class Baseline(nn.Module):
    def __init__(self, width=32, classes=4):
        super().__init__()
        self.left = nn.Linear(16, width)
        self.right = nn.Linear(16, width)
        self.head = nn.Linear(width * 2, classes)

    def forward(self, left_input, right_input):
        left = self.left(left_input)
        right = self.right(right_input)
        return self.head(torch.cat((left, right), dim=-1))
