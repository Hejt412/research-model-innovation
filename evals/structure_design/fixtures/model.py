"""Static synthetic input: never import or execute."""
raise RuntimeError("This fixture is read-only, not a runnable model")

from torch import nn
import torch


class TwoStreamBaseline(nn.Module):
    def __init__(self):
        super().__init__()
        self.left = nn.Linear(16, 32, bias=True)
        self.right = nn.Linear(16, 32, bias=True)
        self.head = nn.Linear(64, 4, bias=True)

    def forward(self, x, y):
        a = torch.relu(self.left(x))
        b = torch.relu(self.right(y))
        return self.head(torch.cat((a, b), dim=-1))
