def preprocess(x):
    return x - x.mean(dim=-1, keepdim=True)
