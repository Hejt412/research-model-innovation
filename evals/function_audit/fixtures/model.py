"""Synthetic static review fixture. Read as text or parse with ast only."""

raise RuntimeError("STATIC FIXTURE: do not import or execute this file")

# nn, tensor, zeros, sigmoid, cat, cross_entropy and AdamW denote conventional
# tensor-library APIs in the supplied design. This file imports no dependencies.


class CrossLinear(nn.Module):
    def __init__(self, dim):
        super().__init__()
        self.a_from_b = nn.Linear(dim, dim, bias=False)
        self.b_from_a = nn.Linear(dim, dim, bias=False)
        nn.init.zeros_(self.a_from_b.weight)
        nn.init.zeros_(self.b_from_a.weight)

    def forward(self, a, b):
        delta_a = self.a_from_b(b)
        delta_b = self.b_from_a(a)
        return a + delta_a, b + delta_b


class CrossValue(nn.Module):
    def __init__(self, dim, rank):
        super().__init__()
        self.down = nn.Linear(dim, rank, bias=False)
        self.up = nn.Linear(rank, dim, bias=False)
        nn.init.xavier_uniform_(self.down.weight)
        nn.init.zeros_(self.up.weight)

    def forward(self, a, b):
        delta_a = self.up(self.down(b).tanh())
        delta_b = self.up(self.down(a).tanh())
        return a + delta_a, b + delta_b


class CrossGate(nn.Module):
    def __init__(self, dim):
        super().__init__()
        self.condition = nn.Linear(dim, dim, bias=False)
        nn.init.xavier_uniform_(self.condition.weight)
        self.alpha = nn.Parameter(tensor(0.0))

    def forward(self, a, b):
        scale_a = 1.0 + self.alpha * sigmoid(self.condition(b))
        scale_b = 1.0 + self.alpha * sigmoid(self.condition(a))
        return a * scale_a, b * scale_b


class TwoBranchClassifier(nn.Module):
    def __init__(self, fusion_name="none", head_kind="affine", freeze_head=False):
        super().__init__()
        self.dim = 4
        self.encoder_a = nn.Sequential(nn.Linear(6, self.dim), nn.Tanh())
        self.encoder_b = nn.Sequential(nn.Linear(6, self.dim), nn.Tanh())
        if fusion_name == "none":
            self.fusion = None
        elif fusion_name == "cross_linear":
            self.fusion = CrossLinear(self.dim)
        elif fusion_name == "cross_value":
            self.fusion = CrossValue(self.dim, rank=2)
        elif fusion_name == "cross_gate":
            self.fusion = CrossGate(self.dim)
        else:
            raise ValueError(fusion_name)

        self.head_kind = head_kind
        self.shared_bias = None
        if head_kind == "affine":
            self.head = nn.Linear(2 * self.dim, 3)
        elif head_kind == "shared_affine":
            self.head = nn.Linear(self.dim, 3, bias=False)
            self.shared_bias = nn.Parameter(zeros(3))
        elif head_kind == "joint_mlp":
            self.head = nn.Sequential(
                nn.Linear(2 * self.dim, 8),
                nn.Tanh(),
                nn.Linear(8, 3),
            )
        else:
            raise ValueError(head_kind)

        if freeze_head:
            for parameter in self.head.parameters():
                parameter.requires_grad_(False)
            if self.shared_bias is not None:
                self.shared_bias.requires_grad_(False)

    def readout(self, a, b):
        if self.head_kind == "shared_affine":
            return self.head(a) + self.head(b) + self.shared_bias
        return self.head(cat((a, b), dim=-1))

    def forward(self, x_a, x_b, enabled=True):
        a = self.encoder_a(x_a)
        b = self.encoder_b(x_b)
        if enabled and self.fusion is not None:
            a, b = self.fusion(a, b)
        return self.readout(a, b)

    def predict_proba(self, x_a, x_b, enabled=True):
        return self.forward(x_a, x_b, enabled=enabled).softmax(dim=-1)


def training_loss(model, x_a, x_b, target):
    logits = model(x_a, x_b, enabled=True)
    return cross_entropy(logits, target)


def make_optimizer(model):
    return AdamW((p for p in model.parameters() if p.requires_grad), lr=1e-3)
