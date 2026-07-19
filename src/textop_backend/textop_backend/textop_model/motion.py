"""Minimal TextOp v3 feature conversion used by local inference."""
from __future__ import annotations

import torch


def quaternion_to_euler_xyz(q: torch.Tensor) -> torch.Tensor:
    x, y, z, w = q.unbind(-1)
    sinr = 2 * (w * x + y * z)
    cosr = 1 - 2 * (x * x + y * y)
    roll = torch.atan2(sinr, cosr)
    sinp = 2 * (w * y - z * x)
    pitch = torch.asin(torch.clamp(sinp, -1.0, 1.0))
    siny = 2 * (w * z + x * y)
    cosy = 1 - 2 * (y * y + z * z)
    yaw = torch.atan2(siny, cosy)
    return torch.stack((roll, pitch, yaw), dim=-1)


def euler_xyz_to_quaternion(e: torch.Tensor) -> torch.Tensor:
    r, p, y = (v * 0.5 for v in e.unbind(-1))
    cr, sr = torch.cos(r), torch.sin(r)
    cp, sp = torch.cos(p), torch.sin(p)
    cy, sy = torch.cos(y), torch.sin(y)
    return torch.stack((sr * cp * cy - cr * sp * sy,
                        cr * sp * cy + sr * cp * sy,
                        cr * cp * sy - sr * sp * cy,
                        cr * cp * cy + sr * sp * sy), dim=-1)


def rotate_z(v: torch.Tensor, yaw: torch.Tensor) -> torch.Tensor:
    c, s = torch.cos(yaw), torch.sin(yaw)
    x, y, z = v.unbind(-1)
    return torch.stack((c * x - s * y, s * x + c * y, z), dim=-1)


def zero_feature(batch: int, history: int, nfeats: int, device: torch.device) -> torch.Tensor:
    out = torch.zeros(batch, history, nfeats, device=device)
    if nfeats >= 7:
        out[..., 5:7] = 1.0
    if nfeats >= 11:
        out[..., 10] = 0.75
    if nfeats >= 34:
        out[..., 11:34] = out.new_tensor([
            -0.1, 0.0, 0.0, 0.3, -0.2,
            0.0, -0.1, 0.0, 0.0, 0.3, -0.2,
            0.0, 0.0, 0.0, 0.0, 0.2, 0.2,
            0.0, 0.9, 0.2, -0.2, 0.0, 0.9,
        ])
    return out


def feature_v3_to_motion(feature: torch.Tensor, absolute_pose: dict[str, torch.Tensor]) -> dict[str, torch.Tensor]:
    if feature.ndim != 3 or feature.shape[-1] < 57:
        raise ValueError("TextOp v3 feature must have shape [B,T,57]")
    b, t, _ = feature.shape
    sin_roll, cos_roll = feature[..., 0], feature[..., 1] + 1
    sin_pitch, cos_pitch = feature[..., 2], feature[..., 3] + 1
    yaw_delta = feature[..., 4]
    contact = feature[..., 5:7]
    delta_local = feature[..., 7:10]
    height = feature[..., 10]
    dof = feature[..., 11:34]
    roll, pitch = torch.atan2(sin_roll, cos_roll), torch.atan2(sin_pitch, cos_pitch)
    ref_yaw = quaternion_to_euler_xyz(absolute_pose["root_rot"])[..., 2]
    yaw = ref_yaw[:, None] + torch.cumsum(
        torch.cat((torch.zeros(b, 1, device=feature.device), yaw_delta[:, :-1]), dim=1), dim=1
    )
    rot = euler_xyz_to_quaternion(torch.stack((roll, pitch, yaw), dim=-1))
    delta_world = rotate_z(delta_local, yaw)
    trans = torch.zeros(b, t, 3, device=feature.device, dtype=feature.dtype)
    trans[:, 0] = absolute_pose["root_trans_offset"]
    if t > 1:
        trans[:, 1:] = absolute_pose["root_trans_offset"][:, None] + torch.cumsum(delta_world[:, :-1], dim=1)
    trans[..., 2] = height
    return {"root_trans_offset": trans, "root_rot": rot, "dof": dof, "contact_mask": contact}


def motion_to_absolute_pose(motion: dict[str, torch.Tensor], idx: int = -1) -> dict[str, torch.Tensor]:
    return {"root_trans_offset": motion["root_trans_offset"][:, idx], "root_rot": motion["root_rot"][:, idx]}
