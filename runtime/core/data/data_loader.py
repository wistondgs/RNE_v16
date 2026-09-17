import torch
import numpy as np
from torch.utils.data import DataLoader, TensorDataset, random_split

class AEONDataset(torch.utils.data.Dataset):
    def __init__(self, num_samples=1024, input_dim=16, normalize=True, seed=None):
        if seed is not None:
            torch.manual_seed(seed)
            np.random.seed(seed)
        self.data = torch.randn(num_samples, input_dim)
        self.normalize = normalize
        if self.normalize:
            self.mean = self.data.mean(dim=0, keepdim=True)
            self.std = self.data.std(dim=0, keepdim=True).clamp_min(1e-6)
            self.data = (self.data - self.mean) / self.std
        else:
            self.mean = None
            self.std = None

    def __len__(self):
        return self.data.size(0)

    def __getitem__(self, idx):
        return self.data[idx]

def get_train_val_loaders(batch_size=32, input_dim=16, num_samples=1024, val_split=0.2, shuffle=True, normalize=True, seed=None):
    dataset = AEONDataset(num_samples=num_samples, input_dim=input_dim, normalize=normalize, seed=seed)
    val_size = int(num_samples * val_split)
    train_size = num_samples - val_size
    # Sin `seed or 42`: la semilla 0 es una semilla válida y el `or` la
    # convertía en 42, de modo que una corrida declarada con semilla 0 no era
    # la que decía ser. Reproducibilidad silenciosamente rota.
    split_seed = 42 if seed is None else int(seed)
    train_dataset, val_dataset = random_split(dataset, [train_size, val_size], generator=torch.Generator().manual_seed(split_seed))
    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=shuffle)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False)
    return train_loader, val_loader
