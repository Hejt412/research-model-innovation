"""Static fixture only; torch is not required for this evaluation."""
from torch import nn
from helper import preprocess


class Baseline(nn.Module):
    def __init__(self):
        super().__init__()
        self.stem = nn.Conv1d(1, 8, 3, padding=1)
        self.head = nn.Linear(8, 3)

    def forward(self, x):
        x = preprocess(x)
        return self.head(self.stem(x).mean(-1))


class Candidate(Baseline):
    def __init__(self):
        super().__init__()
        self.gate = nn.Linear(8, 8)

    def forward(self, x):
        h = self.stem(preprocess(x)).mean(-1)
        return self.head(h * self.gate(h).sigmoid())
