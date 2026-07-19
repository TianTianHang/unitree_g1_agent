from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .generator_engine import PrimitiveResult


class RobotMDARError(RuntimeError):
    pass


def _textop_model_configs() -> tuple[dict[str, Any], dict[str, Any]]:
    vae = {
        "nfeats": 57,
        "latent_dim": [1, 128],
        "h_dim": 512,
        "ff_size": 1024,
        "num_layers": 9,
        "num_heads": 4,
        "dropout": 0.1,
        "arch": "all_encoder",
        "normalize_before": False,
        "activation": "gelu",
        "position_embedding": "learned",
    }
    denoiser = {
        "h_dim": 512,
        "ff_size": 1024,
        "num_layers": 8,
        "num_heads": 4,
        "dropout": 0.1,
        "activation": "gelu",
        "clip_dim": 512,
        "history_shape": [2, 57],
        "noise_shape": [1, 128],
        "cond_mask_prob": 0.1,
    }
    return vae, denoiser


def _textop_dof_velocity(dof: Any, *, dt: float) -> Any:
    if dof.shape[0] < 3:
        raise RobotMDARError("TextOp primitive 至少需要 3 帧才能计算 DOF velocity")
    velocity = (dof[1:] - dof[:-1]) / dt
    result = dof.new_empty(dof.shape)
    result[:-1] = velocity
    result[-1] = velocity[-2]
    return result


class RobotMDARRuntime:
    """项目内 TextOp 推理运行时；类名暂时保留以兼容 generator。"""

    dt = 0.02

    def __init__(self, checkpoint: str | Path, *, vae: str | Path,
                 normalization: str | Path, clip_weights: str | Path,
                 device: str = "cuda:3",
                 guidance_scale: float = 2.5, compile_backend: str = "") -> None:
        try:
            import torch

            from .textop_model.diffusion.gaussian_diffusion import (
                GaussianDiffusion,
                LossType,
                ModelMeanType,
                ModelVarType,
                get_named_beta_schedule,
            )
            from .textop_model.model.mld_denoiser import DenoiserTransformer
            from .textop_model.model.mld_vae import AutoMldVae
            from .textop_model.motion import feature_v3_to_motion, motion_to_absolute_pose, zero_feature
        except ImportError as exc:
            raise RobotMDARError("本地 TextOp 推理依赖不可用") from exc
        self.torch = torch
        self._feature_v3_to_motion = feature_v3_to_motion
        self._motion_to_absolute_pose = motion_to_absolute_pose
        self._zero_feature = zero_feature
        self.device = torch.device(device)
        if self.device.type != "cuda" or self.device.index != 3:
            raise RobotMDARError("TextOp 推理必须使用 cuda:3")
        self.history_len = 2
        self.future_len = 8
        steps = 5
        self.guidance_scale = float(guidance_scale)
        self.mean, self.std = self._load_stats(normalization)
        self.mean = self.mean.to(self.device).reshape(1, 1, -1)
        self.std = self.std.to(self.device).reshape(1, 1, -1).clamp_min(1e-8)
        vae_cfg, den_cfg = _textop_model_configs()
        self.vae = AutoMldVae(**vae_cfg).to(self.device).eval()
        self.denoiser = DenoiserTransformer(**den_cfg).to(self.device).eval()
        self._load_state(self.vae, vae, preferred=("vae", "model"))
        self._load_state(self.denoiser, checkpoint, preferred=("denoiser", "model"))
        if compile_backend:
            self.vae = torch.compile(self.vae, backend=compile_backend)
            self.denoiser = torch.compile(self.denoiser, backend=compile_backend)
        self.diffusion = GaussianDiffusion(
            betas=get_named_beta_schedule("cosine", steps),
            model_mean_type=ModelMeanType.START_X,
            model_var_type=ModelVarType.FIXED_SMALL,
            loss_type=LossType.MSE,
            rescale_timesteps=False,
        )
        self.clip_model = self._load_clip(Path(clip_weights).resolve())

    @staticmethod
    def _load_stats(path: str | Path):
        import torch
        obj = torch.load(Path(path), map_location="cpu")
        if isinstance(obj, tuple | list) and len(obj) == 2:
            return obj[0].float(), obj[1].float()
        if isinstance(obj, dict) and "mean" in obj and "std" in obj:
            return torch.as_tensor(obj["mean"]).float(), torch.as_tensor(obj["std"]).float()
        raise RobotMDARError("meanstd.pkl 必须包含 (mean, std)")

    def _load_state(self, model: Any, path: str | Path, *, preferred: tuple[str, ...]) -> None:
        state = self.torch.load(Path(path), map_location="cpu")
        if isinstance(state, dict):
            for key in (*preferred, "state_dict"):
                if isinstance(state.get(key), dict):
                    state = state[key]
                    break
        if not isinstance(state, dict):
            raise RobotMDARError(f"无法读取模型权重: {path}")
        try:
            model.load_state_dict(state, strict=True)
        except RuntimeError as exc:
            raise RobotMDARError(f"模型权重 ABI 不匹配: {path}") from exc

    @staticmethod
    def _load_clip(clip_weights: Path):
        try:
            import clip
            return clip.load(str(clip_weights), device="cuda:3", jit=False)[0].eval()
        except Exception as exc:
            raise RobotMDARError("CLIP 不可用，无法进行文本编码") from exc

    def _normalize(self, value):
        return (value - self.mean) / self.std

    def _denormalize(self, value):
        return value * self.std + self.mean

    def initial_state(self) -> tuple[Any, Any]:
        history = self._normalize(self._zero_feature(1, self.history_len, 57, self.device))
        pose = {
            "root_trans_offset": self.torch.tensor([[0.0, 0.0, 0.77]], device=self.device),
            "root_rot": self.torch.tensor([[0.0, 0.0, 0.0, 1.0]], device=self.device),
        }
        return history, pose

    def encode_text(self, prompt: str) -> Any:
        import clip
        with self.torch.no_grad():
            return self.clip_model.encode_text(clip.tokenize([prompt]).to(self.device)).float()

    def generate(self, embedding: Any, history: Any, absolute_pose: Any) -> PrimitiveResult:
        torch = self.torch
        with torch.no_grad():
            conditioning = {
                "text_embedding": embedding,
                "history_motion_normalized": history,
                "scale": self.guidance_scale,
            }
            latent: Any = self.diffusion.p_sample_loop(
                _ClassifierFreeDenoiser(self.denoiser),
                (embedding.shape[0], 1, 128), clip_denoised=False,
                model_kwargs={"y": conditioning}, progress=False,
            )
            future = self.vae.decode(latent.permute(1, 0, 2), history, nfuture=self.future_len)
            features = self._denormalize(torch.cat((history, future), dim=1))
            motion = self._feature_v3_to_motion(features, absolute_pose)
            next_pose = self._motion_to_absolute_pose(motion, idx=-2)
            dof = motion["dof"][0]
            velocity = _textop_dof_velocity(dof, dt=self.dt)
            return PrimitiveResult(
                future_motion=future[:, -self.history_len:], absolute_pose=next_pose,
                dof_position=dof.cpu().numpy().astype(np.float32),
                dof_velocity=velocity.cpu().numpy().astype(np.float32),
                anchor_position=motion["root_trans_offset"][0].cpu().numpy().astype(np.float32),
                anchor_orientation_xyzw=motion["root_rot"][0].cpu().numpy().astype(np.float32),
            )


class _ClassifierFreeDenoiser:
    def __init__(self, model: Any) -> None:
        if float(model.cond_mask_prob) <= 0:
            raise RobotMDARError("denoiser 未启用 classifier-free guidance")
        self.model = model

    def parameters(self):
        return self.model.parameters()

    def __call__(self, x, timesteps, y):
        conditional = dict(y)
        conditional["uncond"] = False
        unconditional = dict(y)
        unconditional["uncond"] = True
        unconditioned = self.model(x, timesteps, unconditional)
        conditioned = self.model(x, timesteps, conditional)
        return unconditioned + y["scale"] * (conditioned - unconditioned)
