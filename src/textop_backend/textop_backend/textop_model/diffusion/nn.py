import torch


def mean_flat(tensor):
    return tensor.mean(dim=list(range(1, len(tensor.shape))))


def sum_flat(tensor):
    return tensor.sum(dim=list(range(1, len(tensor.shape))))
