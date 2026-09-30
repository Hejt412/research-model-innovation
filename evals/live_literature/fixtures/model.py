"""Public synthetic, static-only fixture. No real sensor data or trained model.

Read as source text or parse with a static tool. Never import or execute this file.
"""

raise RuntimeError("Static-only synthetic fixture: model execution is not authorized")

from torch import nn
import torch


class TwoSensorBaseline(nn.Module):
    """Two record-local [B, 16] inputs, two [B, 32] features, [B, 4] logits."""

    def __init__(self):
        super().__init__()
        self.sensor_x = nn.Linear(16, 32, bias=True)
        self.sensor_y = nn.Linear(16, 32, bias=True)
        self.head = nn.Linear(64, 4, bias=True)

    def forward(self, x, y):
        a = torch.relu(self.sensor_x(x))
        b = torch.relu(self.sensor_y(y))
        return self.head(torch.cat((a, b), dim=-1))
