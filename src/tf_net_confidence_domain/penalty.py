import torch
import numpy as np
from util import get_device

device = get_device()


class ErrorLoss(torch.nn.Module):
    def __init__(self, c):
        super(ErrorLoss, self).__init__()
        self.c = c

    def forward(self, actual_mu, actual_sigma, expected):
        # the error should be extended such that in c% of the cases, it will be contained
        # but no more than that...
        # how do we do that??
        # well we can do it for each individual channel by saying only consider the batches which aren't super far
        # and only have a loss on those
        # or better, we take those that are overextending and those that are underextending and penalize up to the
        # (1-c)% of them

        pos_dif = torch.abs(actual_mu - expected)
        real_dif = torch.abs(actual_sigma) - pos_dif

        p_in = torch.sum(real_dif > 0) / torch.numel(real_dif)

        loss = 0
        if p_in > self.c:
            loss = torch.mean(torch.square(real_dif[real_dif > 0]))  # reduce it
        elif p_in < self.c:
            loss = torch.mean(torch.square(real_dif[real_dif <= 0]))  # increase it

        return loss


class MagnitudeLoss(torch.nn.Module):
    def __init__(self, loss):
        super(MagnitudeLoss, self).__init__()
        self.loss = loss

    def forward(self, w):
        return self.loss(w, w.detach() * 0)


class SmoothnessLoss(torch.nn.Module):
    """From Back to Basics:
    Unsupervised Learning of Optical Flow
    via Brightness Constancy and Motion Smoothness"""

    def __init__(self, loss, delta=1):
        super(SmoothnessLoss, self).__init__()
        self.loss = loss
        self.delta = delta

    def forward(self, w):
        ldudx = self.loss((w[:, 0, 1:, :] - w[:, 0, :-1, :]) /
                          self.delta, w[:, 0, 1:, :].detach() * 0)
        ldudy = self.loss((w[:, 0, :, 1:] - w[:, 0, :, :-1]) /
                          self.delta, w[:, 0, :, 1:].detach() * 0)
        ldvdx = self.loss((w[:, 1, 1:, :] - w[:, 1, :-1, :]) /
                          self.delta, w[:, 1, 1:, :].detach() * 0)
        ldvdy = self.loss((w[:, 1, :, 1:] - w[:, 1, :, :-1]) /
                          self.delta, w[:, 1, :, 1:].detach() * 0)
        return ldudx + ldudy + ldvdx + ldvdy


class WeightedSpatialMSELoss(torch.nn.Module):
    def __init__(self, weights):
        super(WeightedSpatialMSELoss, self).__init__()
        self.loss = torch.nn.MSELoss(reduce=False, size_average=False)
        self.weights = weights
        
    def forward(self, preds, trues):
        print(self.loss(preds,trues).shape, self.weights.shape)
        return self.loss(preds,trues).mean(4).mean(3).mean(2).mean(0) * self.weights

    
class DivergenceLoss(torch.nn.Module):
    def __init__(self, loss, delta=1):
        super(DivergenceLoss, self).__init__()
        self.delta = delta
        self.loss = loss
    
    def forward(self, preds):
        #preds: bs*2*H*W

        u = preds[:,:1]
        v = preds[:,-1:]
        u_x = field_grad(u, 0)
        v_y = field_grad(v, 1)
        div = v_y + u_x
        return self.loss(div, div.detach()*0)
    
class DivergenceLoss2(torch.nn.Module):
    def __init__(self, loss, delta=1):
        super(DivergenceLoss2, self).__init__()
        self.delta = delta
        self.loss = loss
    
    def forward(self, preds, trues):
        #preds: bs*steps*2*H*W
        u = preds[:,:1]
        v = preds[:,-1:]
        u_x = field_grad(u, 0) 
        v_y = field_grad(v, 1)
        div_pred = v_y + u_x

        u = trues[:,:1]
        v = trues[:,-1:]
        u_x = field_grad(u,0)
        v_y = field_grad(v,1)
        div_true = v_y + u_x
        return self.loss(div_pred, div_true)


def vorticity(u,v):
    return field_grad(v, 0) - field_grad(u, 1)


class VorticityLoss(torch.nn.Module):
    def __init__(self, loss):
        super(VorticityLoss, self).__init__()
        self.loss = loss
    
    def forward(self, preds, trues):
        u,v = trues[:,:1], trues[:,-1:]
        u_pred, v_pred = preds[:,:1], preds[:,-1:]
        return self.loss(vorticity(u,v), vorticity(u_pred, v_pred))
    
def field_grad(f, dim):
    # dim = 1: derivative to x direction, dim = 2: derivative to y direction
    dx = 1
    dim += 1
    N = len(f.shape)
    out = torch.zeros(f.shape).to(device)
    slice1 = [slice(None)]*N
    slice2 = [slice(None)]*N
    slice3 = [slice(None)]*N
    slice4 = [slice(None)]*N

    # 2nd order interior
    slice1[-dim] = slice(1, -1)
    slice2[-dim] = slice(None, -2)
    slice3[-dim] = slice(1, -1)
    slice4[-dim] = slice(2, None)
    out[tuple(slice1)] = (f[tuple(slice4)] - f[tuple(slice2)]) / (2*dx)
    
    # 2nd order edges
    slice1[-dim] = 0
    slice2[-dim] = 0
    slice3[-dim] = 1
    slice4[-dim] = 2
    a = -1.5 / dx
    b = 2. / dx
    c = -0.5 / dx
    out[tuple(slice1)] = a * f[tuple(slice2)] + b * f[tuple(slice3)] + c * f[tuple(slice4)]
    slice1[-dim] = -1
    slice2[-dim] = -3
    slice3[-dim] = -2
    slice4[-dim] = -1
    a = 0.5 / dx
    b = -2. / dx
    c = 1.5 / dx

    out[tuple(slice1)] = a * f[tuple(slice2)] + b * f[tuple(slice3)] + c * f[tuple(slice4)]
    return out


def TKE(preds):
    preds = preds.reshape(preds.shape[0], -1, 2, 64, 64)
    mean_flow = torch.mean(preds, dim = 1).unsqueeze(1)
    tur_preds = torch.mean((preds - mean_flow)**2, dim = 1)
    tke = (tur_preds[:,0] + tur_preds[:,1])/2
    return tke


class TKELoss(torch.nn.Module):
    def __init__(self, loss):
        super(TKELoss, self).__init__()
        self.loss = loss
    
    def forward(self, preds, trues):
        return self.loss(TKE(trues), TKE(preds))
    