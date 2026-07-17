from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .generator_engine import PrimitiveResult


class RobotMDARError(RuntimeError):
    pass


class RobotMDARRuntime:
    """RobotMDAR model adapter with inference orchestration owned by this repository."""

    dt = 0.02

    def __init__(
        self,
        checkpoint: str | Path,
        *,
        vae: str | Path,
        statistics: str | Path,
        normalization: str | Path,
        skeleton_asset_root: str | Path,
        device: str = "cuda",
        guidance_scale: float = 2.5,
        compile_backend: str = "",
    ) -> None:
        try:
            import torch
            from hydra.utils import instantiate
            from omegaconf import OmegaConf
            from robotmdar.dtype import seed
            from robotmdar.dtype.motion import get_zero_abs_pose, get_zero_feature, motion_dict_to_abs_pose
            from robotmdar.model.clip import load_and_freeze_clip
            from robotmdar.train.manager import DARManager
        except ImportError as exc:
            raise RobotMDARError("robotmdar runtime dependencies are not installed") from exc

        self.torch = torch
        self._motion_dict_to_abs_pose = motion_dict_to_abs_pose
        self._get_zero_abs_pose = get_zero_abs_pose
        self._get_zero_feature = get_zero_feature
        checkpoint = Path(checkpoint).resolve()
        vae = Path(vae).resolve()
        statistics = Path(statistics).resolve()
        normalization = Path(normalization).resolve()
        if normalization.name != "meanstd.pkl" or normalization.parent != statistics.parent:
            raise RobotMDARError("normalization must be meanstd.pkl beside action statistics")
        config_path = checkpoint.parent / ".hydra" / "config.yaml"
        if not config_path.is_file():
            config_path = checkpoint.parent / "config.yaml"
        cfg = OmegaConf.load(config_path)
        cfg.device = device
        cfg.ckpt.dar = str(checkpoint)
        cfg.ckpt.vae = str(vae)
        cfg.train.manager.device = device
        cfg.train.manager.save_dir = str(checkpoint.parent)
        cfg.train.manager.platform._target_ = "robotmdar.train.train_platforms.NoPlatform"
        cfg.data.datadir = str(normalization.parent)
        cfg.data.action_statistics_path = str(statistics)
        cfg.data.val.datadir = cfg.data.datadir
        cfg.data.val.action_statistics_path = cfg.data.action_statistics_path
        cfg.data.val.split = "none"
        cfg.data.val.batch_size = 1
        cfg.skeleton.asset.assetRoot = str(Path(skeleton_asset_root).resolve())
        if int(cfg.data.history_len) != 2 or int(cfg.data.future_len) != 8 or int(cfg.diffusion.num_timesteps) != 5:
            raise RobotMDARError("checkpoint is not compatible with TextOp v1")
        seed.set(int(cfg.seed))
        self.device = device
        self.history_len = int(cfg.data.history_len)
        self.future_len = int(cfg.data.future_len)
        self.guidance_scale = float(guidance_scale)
        self.dataset = instantiate(cfg.data.val)
        self.vae = instantiate(cfg.vae).to(device).eval()
        denoiser = instantiate(cfg.denoiser).to(device).eval()
        schedule_sampler = instantiate(cfg.diffusion.schedule_sampler)
        self.diffusion = schedule_sampler.diffusion
        manager: DARManager = instantiate(cfg.train.manager)
        manager.hold_model(self.vae, denoiser, None, self.dataset)
        if compile_backend:
            self.vae = torch.compile(self.vae, backend=compile_backend)
            denoiser = torch.compile(denoiser, backend=compile_backend)
        self.denoiser = _ClassifierFreeDenoiser(denoiser)
        self.clip_model = load_and_freeze_clip("ViT-B/32", device=device)

    def initial_state(self) -> tuple[Any, Any]:
        torch = self.torch
        zero = self._get_zero_feature().reshape(1, 1, -1).repeat(1, self.history_len, 1).to(self.device)
        history = self.dataset.normalize(zero)
        pose = self._get_zero_abs_pose((1,), device=self.device)
        return history, pose

    def encode_text(self, prompt: str) -> Any:
        try:
            import clip
        except ImportError as exc:
            raise RobotMDARError("the CLIP package is not installed") from exc
        with self.torch.no_grad():
            tokens = clip.tokenize([prompt]).to(self.device)
            return self.clip_model.encode_text(tokens).float()

    def generate(self, embedding: Any, history: Any, absolute_pose: Any) -> PrimitiveResult:
        torch = self.torch
        with torch.no_grad():
            latent_shape = (embedding.shape[0], *self.denoiser.noise_shape)
            conditioning = {
                "text_embedding": embedding,
                "history_motion_normalized": history,
                "scale": self.guidance_scale,
            }
            latent = self.diffusion.p_sample_loop(
                self.denoiser,
                latent_shape,
                clip_denoised=False,
                model_kwargs={"y": conditioning},
                skip_timesteps=0,
                init_image=None,
                progress=False,
                dump_steps=None,
                noise=None,
                const_noise=False,
            )
            future = self.vae.decode(latent.permute(1, 0, 2), history, nfuture=self.future_len)
            motion = self.dataset.reconstruct_motion(
                torch.cat([history, future], dim=1), abs_pose=absolute_pose, ret_fk=True, ret_fk_full=False
            )
            next_pose = self._motion_dict_to_abs_pose(motion, idx=-2)
            dof_position = motion.get("dof_pos", motion.get("dof"))
            dof_velocity = motion.get("dof_vel")
            if dof_position is None or dof_velocity is None:
                raise RobotMDARError("reconstructed motion does not contain joint position and velocity")
            return PrimitiveResult(
                future_motion=future[:, -self.history_len :, :],
                absolute_pose=next_pose,
                dof_position=dof_position[0].detach().cpu().numpy().astype(np.float32),
                dof_velocity=dof_velocity[0].detach().cpu().numpy().astype(np.float32),
                anchor_position=motion["root_trans_offset"][0].detach().cpu().numpy().astype(np.float32),
                anchor_orientation_xyzw=motion["root_rot"][0].detach().cpu().numpy().astype(np.float32),
            )


class _ClassifierFreeDenoiser:
    def __init__(self, model: Any) -> None:
        if float(model.cond_mask_prob) <= 0:
            raise RobotMDARError("denoiser was not trained for classifier-free guidance")
        self.model = model

    @property
    def noise_shape(self):
        return self.model.noise_shape

    def parameters(self):
        return self.model.parameters()

    def __call__(self, x, timesteps, y):
        conditional = dict(y)
        conditional["uncond"] = False
        unconditional = dict(y)
        unconditional["uncond"] = True
        conditioned = self.model(x, timesteps, conditional)
        unconditioned = self.model(x, timesteps, unconditional)
        return unconditioned + y["scale"] * (conditioned - unconditioned)
