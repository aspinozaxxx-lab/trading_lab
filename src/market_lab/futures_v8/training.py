"""Target transforms i losses dlia fixed robustnogo futures-v8 training plan."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch
from torch.nn import functional as functional

from market_lab.futures_v8.model import V8ModelOutput

V8_TARGET_HORIZON_COMMON_SESSIONS = 5


@dataclass(frozen=True)
class CrossAssetResidualTargets:
    """Hranit IQR-scaled common factor i neutral residual labels dlia train."""

    factor: torch.Tensor
    factor_valid: torch.Tensor
    residual: torch.Tensor
    residual_valid: torch.Tensor


@dataclass(frozen=True)
class V8LossBreakdown:
    """Pokazyvaet vse loss components bez podmeny return direction-logitom."""

    total: torch.Tensor
    factor: torch.Tensor
    residual_nll: torch.Tensor
    direction: torch.Tensor
    crash_router: torch.Tensor
    regime_balance: torch.Tensor
    cost_aware: torch.Tensor


@dataclass(frozen=True)
class CausalPreviousPositions:
    """Hranit predydushchie target-free position tol'ko iz strogo ordered decisions."""

    decision_times: np.ndarray
    values: torch.Tensor


@dataclass(frozen=True)
class FiveSessionTargetBatch:
    """Hranit sealed five-common-session labels tekushchego purged train folda."""

    values: torch.Tensor
    target_mask: torch.Tensor
    label_end_times: np.ndarray
    purged_train_cutoff: np.datetime64
    horizon_common_sessions: int = V8_TARGET_HORIZON_COMMON_SESSIONS

    def validate(self) -> None:
        """Zapreshchaet drugoi horizon i label, dostupnyi ne do train cutoff."""
        _require_target_shapes(self.values, self.target_mask)
        if self.target_mask.dtype != torch.bool:
            raise ValueError("Five-session target_mask dolzhen byt' torch.bool")
        if self.horizon_common_sessions != V8_TARGET_HORIZON_COMMON_SESSIONS:
            raise ValueError("Supervised target dolzhen imet' horizon rovno 5 common sessions")
        label_end = _datetime_array(self.label_end_times, "label_end_times")
        if label_end.shape != tuple(self.target_mask.shape):
            raise ValueError("label_end_times dolzhny sovpadat' s [batch, assets]")
        cutoff = _datetime_scalar(self.purged_train_cutoff, "purged_train_cutoff")
        valid = self.target_mask.detach().cpu().numpy().astype(bool, copy=False)
        if np.isnat(label_end[valid]).any():
            raise ValueError("Valid five-session label ne mozhet imet' NaT end")
        if (label_end[valid] >= cutoff).any():
            raise ValueError("Five-session label end dolzhen byt' strogo do purged cutoff")


@dataclass(frozen=True)
class OrderedDecisionBatch:
    """Dokazyvaet contiguous chronology dlia turnover loss bez shuffled minibatcha."""

    decision_times: np.ndarray
    sequence_numbers: np.ndarray
    initial_position: torch.Tensor | None = None
    starts_flat: bool = False

    def validate(self, expected_count: int, asset_count: int) -> np.ndarray:
        """Trebuet unique time, contiguous dataset sequence i known initial carry."""
        ordered_times = _datetime_array(self.decision_times, "decision_times")
        if ordered_times.ndim != 1 or ordered_times.shape[0] != expected_count:
            raise ValueError("decision_times dolzhny byt' [decisions] i sovpadat' s score")
        if np.isnat(ordered_times).any():
            raise ValueError("decision_times ne dopuskaiut NaT")
        if expected_count > 1 and (
            np.diff(ordered_times) <= np.timedelta64(0, "ns")
        ).any():
            raise ValueError("decision_times dolzhny byt' strogo vozrastaiushchimi")
        sequence = np.asarray(self.sequence_numbers)
        if sequence.ndim != 1 or sequence.shape[0] != expected_count:
            raise ValueError("sequence_numbers dolzhny byt' [decisions]")
        if sequence.dtype.kind not in "iu":
            raise ValueError("sequence_numbers dolzhny byt' celochislennymi")
        if expected_count > 1 and not np.all(np.diff(sequence.astype(np.int64)) == 1):
            raise ValueError("Turnover batch dolzhen byt' contiguous, bez sampled gaps")
        if self.starts_flat and self.initial_position is not None:
            raise ValueError("starts_flat i explicit initial_position vzaimoiskliuchaiushchie")
        if not self.starts_flat and self.initial_position is None:
            raise ValueError("Known initial_position trebuetsia dlia ne-novogo stream")
        if self.initial_position is not None:
            if self.initial_position.shape != (asset_count,):
                raise ValueError("initial_position dolzhen imet' formu [assets]")
            if not torch.isfinite(self.initial_position).all():
                raise ValueError("initial_position dolzhen byt' finite")
        return ordered_times


@dataclass(frozen=True)
class FoldLocalSslBoundary:
    """Fiksiruet input/horizon end tekushchego purged fold dlia fresh SSL."""

    input_bar_end_times: np.ndarray
    horizon_end_times: np.ndarray
    purged_train_cutoff: np.datetime64

    def validate_mask(self, target_mask: torch.Tensor) -> None:
        """Ne propuskaet ni input, ni SSL horizon na ili posle purged cutoff."""
        if target_mask.dtype != torch.bool:
            raise ValueError("SSL target_mask dolzhen byt' torch.bool")
        input_end = _datetime_array(self.input_bar_end_times, "input_bar_end_times")
        horizon_end = _datetime_array(self.horizon_end_times, "horizon_end_times")
        expected_input_shape = tuple(target_mask.shape[:-1])
        if input_end.shape != expected_input_shape or horizon_end.shape != tuple(
            target_mask.shape
        ):
            raise ValueError("SSL boundary times imeiut nevernuiu formu")
        cutoff = _datetime_scalar(self.purged_train_cutoff, "purged_train_cutoff")
        valid = target_mask.detach().cpu().numpy().astype(bool, copy=False)
        expanded_input_end = np.broadcast_to(input_end[..., None], horizon_end.shape)
        factual_input = ~np.isnat(input_end)
        if (input_end[factual_input] >= cutoff).any():
            raise ValueError("Kazhdii factual SSL input end dolzhen byt' strogo do cutoff")
        if np.isnat(expanded_input_end[valid]).any() or np.isnat(horizon_end[valid]).any():
            raise ValueError("Valid SSL sample ne mozhet imet' NaT boundary")
        if (expanded_input_end[valid] >= cutoff).any():
            raise ValueError("SSL input bar end dolzhen byt' strogo do purged cutoff")
        if (horizon_end[valid] >= cutoff).any():
            raise ValueError("SSL horizon end dolzhen byt' strogo do purged cutoff")
        if (horizon_end[valid] <= expanded_input_end[valid]).any():
            raise ValueError("SSL horizon end dolzhen byt' posle causal input end")

    def validate_contrastive_mask(self, asset_mask: torch.Tensor) -> None:
        """Proveriaet vse factual input end dlia causal contrastive representation."""
        if asset_mask.ndim != 2 or asset_mask.dtype != torch.bool:
            raise ValueError("Contrastive asset_mask dolzhen byt' bool [batch, assets]")
        input_end = _datetime_array(self.input_bar_end_times, "input_bar_end_times")
        if input_end.shape[:2] != tuple(asset_mask.shape):
            raise ValueError("Contrastive input boundary ne sovpadaet s asset mask")
        cutoff = _datetime_scalar(self.purged_train_cutoff, "purged_train_cutoff")
        active = asset_mask.detach().cpu().numpy().astype(bool, copy=False)
        factual = ~np.isnat(input_end)
        if (active & ~factual.any(axis=-1)).any():
            raise ValueError("Valid contrastive asset trebuet factual input end")
        active_factual = active[..., None] & factual
        if (input_end[active_factual] >= cutoff).any():
            raise ValueError("Contrastive input end dolzhen byt' strogo do purged cutoff")


def _datetime_array(values: np.ndarray, field_name: str) -> np.ndarray:
    """Privodit timestamp-like massiv k datetime64[ns] s ponyatnoi oshibkoi."""
    try:
        return np.asarray(values).astype("datetime64[ns]")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} dolzhen byt' timestamp-like") from exc


def _datetime_scalar(value: np.datetime64, field_name: str) -> np.datetime64:
    """Privodit odin cutoff k finite datetime64[ns]."""
    converted = _datetime_array(np.asarray(value), field_name)
    if converted.ndim != 0 or np.isnat(converted):
        raise ValueError(f"{field_name} dolzhen byt' finite scalar timestamp")
    return converted


def _require_target_shapes(
    targets: torch.Tensor,
    target_mask: torch.Tensor,
) -> None:
    """Proveryaet [batch, assets] labels do cross-sectional arithmetic."""
    if targets.ndim != 2 or target_mask.shape != targets.shape:
        raise ValueError("targets/target_mask dolzhny imet' formu [batch, assets]")


def cross_asset_residual_targets(
    targets: torch.Tensor,
    target_mask: torch.Tensor,
    train_target_iqr: float,
) -> CrossAssetResidualTargets:
    """Udalyaet same-day common move i masshtabiruet labels tol'ko train IQR.

    Factor ostaiotsia dostupnym pri odnom assete; alpha residual ne obuchaetsia bez
    minimum dvukh simultaneously valid assets, potomu chto ego nel'zia opredelit'.
    """
    _require_target_shapes(targets, target_mask)
    if not train_target_iqr > 0.0:
        raise ValueError("train_target_iqr dolzhen byt' > 0")
    valid = target_mask & torch.isfinite(targets)
    scaled = torch.where(valid, targets / train_target_iqr, torch.zeros_like(targets))
    count = valid.sum(dim=1)
    denominator = count.clamp_min(1).to(targets.dtype)
    factor = scaled.sum(dim=1) / denominator
    factor_valid = count > 0
    residual = scaled - factor[:, None]
    residual_valid = valid & (count[:, None] >= 2)
    residual = torch.where(residual_valid, residual, torch.zeros_like(residual))
    factor = torch.where(factor_valid, factor, torch.zeros_like(factor))
    return CrossAssetResidualTargets(
        factor=factor,
        factor_valid=factor_valid,
        residual=residual,
        residual_valid=residual_valid,
    )


def gaussian_location_scale_nll(
    location: torch.Tensor,
    scale: torch.Tensor,
    targets: torch.Tensor,
    target_mask: torch.Tensor,
) -> torch.Tensor:
    """Schitaet heteroscedastic Gaussian NLL tol'ko na valid targets."""
    if location.shape != scale.shape or targets.shape != location.shape:
        raise ValueError("location/scale/targets imeiut nesovmestimye formy")
    if target_mask.shape != targets.shape:
        raise ValueError("target_mask imeet nevernuiu formu")
    if not target_mask.any():
        return location.sum() * 0.0
    selected_scale = scale[target_mask].clamp_min(0.05)
    error = (targets[target_mask] - location[target_mask]) / selected_scale
    return 0.5 * (error.square() + 2.0 * torch.log(selected_scale)).mean()


def auxiliary_residual_direction_loss(
    direction_logits: torch.Tensor,
    residual_targets: torch.Tensor,
    residual_mask: torch.Tensor,
) -> torch.Tensor:
    """Obuchaet otdel'nyi sign logit; on nikogda ne input dlia return loss."""
    if (
        direction_logits.shape != residual_targets.shape
        or residual_mask.shape != residual_targets.shape
    ):
        raise ValueError("Direction logits i residual labels imeiut nevernuiu formu")
    if not residual_mask.any():
        return direction_logits.sum() * 0.0
    signs = (residual_targets[residual_mask] > 0.0).to(direction_logits.dtype)
    return functional.binary_cross_entropy_with_logits(direction_logits[residual_mask], signs)


def regime_balance_loss(regime_probabilities: torch.Tensor) -> torch.Tensor:
    """Sderzhivaet collapse routera v odin expert bez ispol'zovaniia targetov."""
    if regime_probabilities.ndim != 2 or regime_probabilities.shape[1] < 2:
        raise ValueError("regime_probabilities dolzhny byt' [batch, experts]")
    mean_probability = regime_probabilities.mean(dim=0).clamp_min(1e-8)
    uniform = torch.full_like(mean_probability, 1.0 / mean_probability.numel())
    return functional.kl_div(mean_probability.log(), uniform, reduction="sum")


def build_crash_labels(
    targets: torch.Tensor,
    target_mask: torch.Tensor,
    train_target_iqr: float,
    threshold_iqr: float = 2.5,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Stroit train-only crisis label iz broad five-session magnitude, ne iz inputa."""
    _require_target_shapes(targets, target_mask)
    if train_target_iqr <= 0.0 or threshold_iqr <= 0.0:
        raise ValueError("IQR i crash threshold dolzhny byt' > 0")
    valid = target_mask & torch.isfinite(targets)
    count = valid.sum(dim=1)
    average_absolute_move = torch.where(valid, targets.abs(), torch.zeros_like(targets)).sum(
        dim=1
    ) / count.clamp_min(1).to(targets.dtype)
    label_valid = count >= 2
    labels = average_absolute_move >= threshold_iqr * train_target_iqr
    return labels.to(targets.dtype), label_valid


def crash_router_loss(
    regime_probabilities: torch.Tensor,
    crash_labels: torch.Tensor,
    crash_label_mask: torch.Tensor,
    crash_expert_index: int = 2,
) -> torch.Tensor:
    """Napravliaet vydelennyi crash expert, ostavliaia residual heads otdelnymi."""
    if regime_probabilities.ndim != 2:
        raise ValueError("regime_probabilities dolzhny byt' [batch, experts]")
    if not 0 <= crash_expert_index < regime_probabilities.shape[1]:
        raise ValueError("crash_expert_index vne routera")
    if (
        crash_labels.shape != regime_probabilities.shape[:1]
        or crash_label_mask.shape != crash_labels.shape
    ):
        raise ValueError("Crash labels/mask imeiut nevernuiu formu")
    if not crash_label_mask.any():
        return regime_probabilities.sum() * 0.0
    probability = regime_probabilities[:, crash_expert_index].clamp(1e-6, 1.0 - 1e-6)
    return functional.binary_cross_entropy(
        probability[crash_label_mask],
        crash_labels[crash_label_mask],
    )


def causal_previous_positions(
    decision_score: torch.Tensor,
    ordered_batch: OrderedDecisionBatch,
) -> CausalPreviousPositions:
    """Stroit prior position iz t-1 score tol'ko dlia explicit contiguous batch.

    Vse subsequent positions postroeny iz ``decision_score`` predydushchego
    decision timestamp i otdeleny ot gradient graph.
    """
    if decision_score.ndim != 2:
        raise ValueError("decision_score dolzhen imet' formu [decisions, assets]")
    if not isinstance(ordered_batch, OrderedDecisionBatch):
        raise TypeError("Turnover trebuet explicit OrderedDecisionBatch contract")
    ordered_times = ordered_batch.validate(
        expected_count=decision_score.shape[0],
        asset_count=decision_score.shape[1],
    )
    if ordered_batch.starts_flat:
        first = torch.zeros(
            decision_score.shape[1],
            dtype=decision_score.dtype,
            device=decision_score.device,
        )
    else:
        assert ordered_batch.initial_position is not None
        first = ordered_batch.initial_position.to(
            dtype=decision_score.dtype,
            device=decision_score.device,
        ).detach()
    bounded_score = decision_score.clamp(-1.0, 1.0)
    prior = torch.cat((first[None], bounded_score[:-1].detach()), dim=0)
    return CausalPreviousPositions(decision_times=ordered_times, values=prior)


def differentiable_cost_aware_residual_utility_loss(
    decision_score: torch.Tensor,
    residual_targets: torch.Tensor,
    residual_mask: torch.Tensor,
    one_way_cost_in_iqr: torch.Tensor,
    ordered_batch: OrderedDecisionBatch,
) -> torch.Tensor:
    """Shtrafuet turnover v IQR units; ne strooit PnL i ne chitaet OOS ledger.

    ``decision_score`` postroen tol'ko iz calibrated residual location i uncertainty.
    Auxiliary direction logits dazhe ne prinimaiutsia etoi funkciei.
    """
    required_shape = decision_score.shape
    if (
        residual_targets.shape != required_shape
        or residual_mask.shape != required_shape
        or one_way_cost_in_iqr.shape != required_shape
    ):
        raise ValueError("Cost-aware tensors dolzhny imet' odnu [batch, assets] formu")
    if one_way_cost_in_iqr.dtype == torch.bool:
        raise ValueError("One-way cost ne mozhet byt' boolean")
    required_cost = one_way_cost_in_iqr[residual_mask]
    if not torch.isfinite(required_cost).all() or (required_cost <= 0.0).any():
        raise ValueError(
            "Kazhdii residual-valid row trebuet finite positive D-known one-way cost"
        )
    previous_position = causal_previous_positions(
        decision_score,
        ordered_batch,
    ).values
    if not residual_mask.any():
        return decision_score.sum() * 0.0
    position = decision_score.clamp(-1.0, 1.0)
    turnover = (position - previous_position).abs()
    utility = position * residual_targets - one_way_cost_in_iqr.clamp_min(0.0) * turnover
    return -utility[residual_mask].mean()


def v8_supervised_loss(
    output: V8ModelOutput,
    target_batch: FiveSessionTargetBatch,
    train_target_iqr: float,
    one_way_cost_in_iqr: torch.Tensor,
    ordered_batch: OrderedDecisionBatch,
    *,
    direction_weight: float = 0.05,
    crash_weight: float = 0.05,
    regime_balance_weight: float = 0.01,
    cost_aware_weight: float = 0.10,
) -> V8LossBreakdown:
    """Sobiraet loss tol'ko iz sealed five-session purged training labels."""
    weights = (direction_weight, crash_weight, regime_balance_weight, cost_aware_weight)
    if not all(weight >= 0.0 for weight in weights):
        raise ValueError("Loss weights ne mogut byt' otricatelnymi")
    target_batch.validate()
    targets = target_batch.values
    target_mask = target_batch.target_mask
    residual_targets = cross_asset_residual_targets(targets, target_mask, train_target_iqr)
    factor = gaussian_location_scale_nll(
        output.factor_location,
        output.factor_scale,
        residual_targets.factor,
        residual_targets.factor_valid,
    )
    residual_nll = gaussian_location_scale_nll(
        output.residual_location,
        output.total_scale,
        residual_targets.residual,
        residual_targets.residual_valid,
    )
    direction = auxiliary_residual_direction_loss(
        output.direction_logit,
        residual_targets.residual,
        residual_targets.residual_valid,
    )
    crash_labels, crash_mask = build_crash_labels(targets, target_mask, train_target_iqr)
    crash = crash_router_loss(output.regime_probabilities, crash_labels, crash_mask)
    balance = regime_balance_loss(output.regime_probabilities)
    cost_aware = differentiable_cost_aware_residual_utility_loss(
        output.decision_score,
        residual_targets.residual,
        residual_targets.residual_valid,
        one_way_cost_in_iqr,
        ordered_batch,
    )
    total = (
        factor
        + residual_nll
        + direction_weight * direction
        + crash_weight * crash
        + regime_balance_weight * balance
        + cost_aware_weight * cost_aware
    )
    return V8LossBreakdown(
        total=total,
        factor=factor,
        residual_nll=residual_nll,
        direction=direction,
        crash_router=crash,
        regime_balance=balance,
        cost_aware=cost_aware,
    )


def causal_patch_contrastive_loss(
    first_view: torch.Tensor,
    second_view: torch.Tensor,
    asset_mask: torch.Tensor,
    fold_boundary: FoldLocalSslBoundary,
    temperature: float = 0.10,
) -> torch.Tensor:
    """Schitaet deterministic two-view InfoNCE po final'nym causal patch embeddings."""
    if first_view.shape != second_view.shape or first_view.ndim != 3:
        raise ValueError("Contrastive views dolzhny imet' [batch, assets, width]")
    if asset_mask.shape != first_view.shape[:2]:
        raise ValueError("asset_mask imeet nevernuiu formu")
    if temperature <= 0.0:
        raise ValueError("temperature dolzhna byt' > 0")
    fold_boundary.validate_contrastive_mask(asset_mask)
    valid = asset_mask.reshape(-1)
    if valid.sum() < 2:
        return first_view.sum() * 0.0
    anchors = functional.normalize(first_view.reshape(-1, first_view.shape[-1])[valid], dim=-1)
    positives = functional.normalize(second_view.reshape(-1, second_view.shape[-1])[valid], dim=-1)
    logits = anchors @ positives.transpose(0, 1) / temperature
    labels = torch.arange(logits.shape[0], device=logits.device)
    return functional.cross_entropy(logits, labels)


def masked_dynamic_ssl_loss(
    forecasts: torch.Tensor,
    targets: torch.Tensor,
    target_mask: torch.Tensor,
    fold_boundary: FoldLocalSslBoundary,
) -> torch.Tensor:
    """Obuchaet fresh-fold SSL tol'ko pri strict pre-cutoff input i horizon end."""
    if forecasts.shape != targets.shape or forecasts.shape[:-1] != target_mask.shape:
        raise ValueError("SSL forecasts/targets/mask imeiut nevernuiu formu")
    if forecasts.shape[-1] != 2:
        raise ValueError("SSL posledniaia os' dolzhna byt' return i scale")
    fold_boundary.validate_mask(target_mask)
    if not target_mask.any():
        return forecasts.sum() * 0.0
    location = forecasts[..., 0]
    scale = functional.softplus(forecasts[..., 1]).clamp_min(0.05)
    nll = gaussian_location_scale_nll(location, scale, targets[..., 0], target_mask)
    volatility = functional.smooth_l1_loss(
        scale[target_mask], targets[..., 1][target_mask]
    )
    return nll + volatility


__all__ = [
    "CrossAssetResidualTargets",
    "CausalPreviousPositions",
    "FiveSessionTargetBatch",
    "FoldLocalSslBoundary",
    "OrderedDecisionBatch",
    "V8_TARGET_HORIZON_COMMON_SESSIONS",
    "V8LossBreakdown",
    "auxiliary_residual_direction_loss",
    "build_crash_labels",
    "causal_previous_positions",
    "causal_patch_contrastive_loss",
    "cross_asset_residual_targets",
    "differentiable_cost_aware_residual_utility_loss",
    "masked_dynamic_ssl_loss",
    "v8_supervised_loss",
]
