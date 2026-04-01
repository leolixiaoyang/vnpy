"""Lingxiao SLV 两层机器学习信号复现。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import polars as pl
from sklearn.linear_model import LogisticRegression, RidgeClassifier  # type: ignore
from sklearn.naive_bayes import GaussianNB  # type: ignore
from sklearn.neural_network import MLPClassifier  # type: ignore
from sklearn.preprocessing import StandardScaler  # type: ignore
from sklearn.svm import SVC  # type: ignore

from vnpy.alpha import AlphaLab
from vnpy.trader.constant import Interval


@dataclass
class PipelineConfig:
    """信号流水线参数。"""

    target_symbol: str
    reference_symbols: dict[str, str]
    start: str
    end: str
    interval: Interval
    primary_lookback: int = 60
    meta_lookback: int = 1000
    retrain_interval: int = 3
    forward_horizon_min: int = 5
    forward_horizon_max: int = 10


def sigmoid(value: np.ndarray) -> np.ndarray:
    """稳定的 sigmoid。"""
    return 1.0 / (1.0 + np.exp(-np.clip(value, -20, 20)))


def rolling_corr(left: np.ndarray, right: np.ndarray, window: int) -> np.ndarray:
    """计算滚动相关系数。"""
    result: np.ndarray = np.full(left.shape, np.nan)

    for index in range(window - 1, len(left)):
        left_window = left[index - window + 1: index + 1]
        right_window = right[index - window + 1: index + 1]

        if np.isnan(left_window).any() or np.isnan(right_window).any():
            continue

        std_left = np.std(left_window)
        std_right = np.std(right_window)
        if std_left == 0 or std_right == 0:
            result[index] = 0.0
            continue

        result[index] = float(np.corrcoef(left_window, right_window)[0, 1])

    return result


class LingxiaoSlvSignalPipeline:
    """根据截图描述复现两层模型信号。"""

    def __init__(self, lab: AlphaLab, config: PipelineConfig) -> None:
        self.lab: AlphaLab = lab
        self.config: PipelineConfig = config

        self.feature_columns: list[str] = []
        self.meta_feature_columns: list[str] = []

    def generate_signal(self) -> pl.DataFrame:
        """生成 0-5 强度信号。"""
        df = self._build_feature_frame()

        dates = df["datetime"].to_list()
        primary_raw = np.full(len(df), np.nan)
        primary_score = np.full(len(df), np.nan)
        meta_raw = np.full(len(df), np.nan)
        final_score = np.full(len(df), np.nan)

        primary_ready = False
        meta_ready = False

        for index in range(len(df)):
            if index < self.config.meta_lookback:
                continue

            if not np.isfinite(df["forward_mean_return"][index]):
                continue

            retrain = (index % self.config.retrain_interval == 0) or not (primary_ready and meta_ready)

            train_start = max(0, index - self.config.meta_lookback)
            primary_train_start = max(0, index - self.config.primary_lookback)

            if retrain:
                primary_bundle = self._fit_primary_models(df.slice(primary_train_start, index - primary_train_start))
                meta_bundle = self._fit_meta_models(df.slice(train_start, index - train_start))
                primary_ready = primary_bundle is not None
                meta_ready = meta_bundle is not None

            if not primary_ready or not meta_ready:
                continue

            row = df.slice(index, 1)
            primary_prediction = self._predict_primary(primary_bundle, row)
            if primary_prediction is None:
                continue

            primary_raw[index] = primary_prediction["raw"]
            primary_score[index] = primary_prediction["score"]

            row = row.with_columns([
                pl.lit(primary_prediction["svm_prob"]).alias("svm_prob"),
                pl.lit(primary_prediction["nb_prob"]).alias("nb_prob"),
                pl.lit(primary_prediction["score"]).alias("primary_score"),
            ])

            meta_prediction = self._predict_meta(meta_bundle, row)
            if meta_prediction is None:
                continue

            meta_raw[index] = meta_prediction["raw"]

            close = float(row["close"][0])
            sma_60 = float(row["sma_gap_60"][0])
            downtrend = close < close / (1.0 + sma_60) if np.isfinite(sma_60) and (1.0 + sma_60) != 0 else False

            if downtrend:
                ensemble_raw = 0.65 * primary_prediction["raw"] + 0.35 * meta_prediction["raw"]
            else:
                ensemble_raw = 0.35 * primary_prediction["raw"] + 0.65 * meta_prediction["raw"]

            final_score[index] = self._raw_to_score(ensemble_raw, meta_bundle["reference_scores"])

        signal_df = df.select(["datetime"]).with_columns([
            pl.lit(self.config.target_symbol).alias("vt_symbol"),
            pl.Series("signal", final_score, dtype=pl.Float64),
            pl.Series("consensus_signal", primary_score, dtype=pl.Float64),
            pl.Series("meta_signal", meta_raw, dtype=pl.Float64),
            pl.Series("forward_mean_return", df["forward_mean_return"].to_numpy(), dtype=pl.Float64),
        ]).drop_nulls()

        return signal_df

    def _build_feature_frame(self) -> pl.DataFrame:
        """构造特征 DataFrame。"""
        symbol_frames: dict[str, pl.DataFrame] = {}

        all_symbols = {"target": self.config.target_symbol}
        all_symbols.update(self.config.reference_symbols)

        for alias, vt_symbol in all_symbols.items():
            symbol_frames[alias] = self._load_symbol_frame(vt_symbol)

        target = symbol_frames["target"]
        merged = target

        for alias, ref_df in symbol_frames.items():
            if alias == "target":
                continue

            merged = merged.join(
                ref_df.select([
                    "datetime",
                    pl.col("close").alias(f"{alias}_close"),
                    pl.col("ret_1").alias(f"{alias}_ret_1"),
                ]),
                on="datetime",
                how="inner",
            )

        close = merged["close"].to_numpy()
        volume = merged["volume"].to_numpy()
        high = merged["high"].to_numpy()
        low = merged["low"].to_numpy()

        qqq_ret = merged["qqq_ret_1"].to_numpy()
        gold_ret = merged["gold_ret_1"].to_numpy()
        dollar_ret = merged["dollar_ret_1"].to_numpy()
        target_ret = merged["ret_1"].to_numpy()

        atr_14 = self._atr(high, low, close, 14)
        rsi_6 = self._rsi(close, 6)
        rsi_14 = self._rsi(close, 14)
        rsi_28 = self._rsi(close, 28)

        future_returns = []
        for horizon in range(self.config.forward_horizon_min, self.config.forward_horizon_max + 1):
            forward_return = np.roll(close, -horizon) / close - 1.0
            forward_return[-horizon:] = np.nan
            future_returns.append(forward_return)

        forward_mean_return = np.nanmean(np.column_stack(future_returns), axis=1)

        dataset = merged.with_columns([
            pl.Series("ret_3", close / np.roll(close, 3) - 1.0, dtype=pl.Float64),
            pl.Series("ret_5", close / np.roll(close, 5) - 1.0, dtype=pl.Float64),
            pl.Series("ret_10", close / np.roll(close, 10) - 1.0, dtype=pl.Float64),
            pl.Series("ret_20", close / np.roll(close, 20) - 1.0, dtype=pl.Float64),
            pl.Series("sma_gap_5", self._sma_gap(close, 5), dtype=pl.Float64),
            pl.Series("sma_gap_10", self._sma_gap(close, 10), dtype=pl.Float64),
            pl.Series("sma_gap_20", self._sma_gap(close, 20), dtype=pl.Float64),
            pl.Series("sma_gap_60", self._sma_gap(close, 60), dtype=pl.Float64),
            pl.Series("vol_ratio_5", volume / self._rolling_mean(volume, 5), dtype=pl.Float64),
            pl.Series("vol_ratio_20", volume / self._rolling_mean(volume, 20), dtype=pl.Float64),
            pl.Series("volatility_10", self._rolling_std(target_ret, 10), dtype=pl.Float64),
            pl.Series("volatility_20", self._rolling_std(target_ret, 20), dtype=pl.Float64),
            pl.Series("atr_ratio_14", atr_14 / close, dtype=pl.Float64),
            pl.Series("rsi_6", rsi_6, dtype=pl.Float64),
            pl.Series("rsi_14", rsi_14, dtype=pl.Float64),
            pl.Series("rsi_28", rsi_28, dtype=pl.Float64),
            pl.Series("corr_qqq_20", rolling_corr(target_ret, qqq_ret, 20), dtype=pl.Float64),
            pl.Series("corr_gold_20", rolling_corr(target_ret, gold_ret, 20), dtype=pl.Float64),
            pl.Series("corr_dollar_20", rolling_corr(target_ret, dollar_ret, 20), dtype=pl.Float64),
            pl.Series("corr_qqq_60", rolling_corr(target_ret, qqq_ret, 60), dtype=pl.Float64),
            pl.Series("corr_gold_60", rolling_corr(target_ret, gold_ret, 60), dtype=pl.Float64),
            pl.Series("corr_dollar_60", rolling_corr(target_ret, dollar_ret, 60), dtype=pl.Float64),
            pl.Series("forward_mean_return", forward_mean_return, dtype=pl.Float64),
        ])

        self.feature_columns = [
            "ret_1",
            "ret_3",
            "ret_5",
            "ret_10",
            "ret_20",
            "sma_gap_5",
            "sma_gap_10",
            "sma_gap_20",
            "sma_gap_60",
            "vol_ratio_5",
            "vol_ratio_20",
            "volatility_10",
            "volatility_20",
            "atr_ratio_14",
            "rsi_6",
            "rsi_14",
            "rsi_28",
            "corr_qqq_20",
            "corr_gold_20",
            "corr_dollar_20",
            "corr_qqq_60",
            "corr_gold_60",
            "corr_dollar_60",
        ]

        return dataset.drop_nulls(subset=self.feature_columns + ["forward_mean_return"])

    def _load_symbol_frame(self, vt_symbol: str) -> pl.DataFrame:
        """从 AlphaLab 加载单个品种。"""
        bars = self.lab.load_bar_data(
            vt_symbol,
            self.config.interval,
            self.config.start,
            self.config.end,
        )

        if not bars:
            raise ValueError(f"找不到 {vt_symbol} 的历史数据，请先写入 {Path(self.lab.lab_path) / 'daily'}")

        rows = []
        for bar in bars:
            rows.append({
                "datetime": bar.datetime.replace(tzinfo=None),
                "open": bar.open_price,
                "high": bar.high_price,
                "low": bar.low_price,
                "close": bar.close_price,
                "volume": bar.volume,
            })

        df = pl.DataFrame(rows).sort("datetime")
        close = df["close"].to_numpy()
        ret_1 = close / np.roll(close, 1) - 1.0
        ret_1[0] = np.nan
        return df.with_columns(pl.Series("ret_1", ret_1, dtype=pl.Float64))

    def _fit_primary_models(self, train_df: pl.DataFrame) -> dict | None:
        """训练一级模型。"""
        train_df = train_df.drop_nulls(subset=self.feature_columns + ["forward_mean_return"])
        if train_df.height < 80:
            return None

        y = (train_df["forward_mean_return"].to_numpy() > 0).astype(int)
        if len(np.unique(y)) < 2:
            return None

        X = train_df.select(self.feature_columns).to_numpy()
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        svm = SVC(C=1.0, gamma="scale", probability=True, class_weight="balanced", random_state=42)
        nb = GaussianNB()

        svm.fit(X_scaled, y)
        nb.fit(X_scaled, y)

        svm_prob = svm.predict_proba(X_scaled)[:, 1]
        nb_prob = nb.predict_proba(X_scaled)[:, 1]
        reference_scores = 0.5 * svm_prob + 0.5 * nb_prob

        return {
            "scaler": scaler,
            "svm": svm,
            "nb": nb,
            "reference_scores": reference_scores,
        }

    def _predict_primary(self, bundle: dict, row: pl.DataFrame) -> dict | None:
        """预测一级信号。"""
        if row.height != 1:
            return None

        X = row.select(self.feature_columns).to_numpy()
        X_scaled = bundle["scaler"].transform(X)

        svm_prob = float(bundle["svm"].predict_proba(X_scaled)[:, 1][0])
        nb_prob = float(bundle["nb"].predict_proba(X_scaled)[:, 1][0])
        raw = 0.5 * svm_prob + 0.5 * nb_prob
        score = self._raw_to_score(raw, bundle["reference_scores"])

        return {
            "svm_prob": svm_prob,
            "nb_prob": nb_prob,
            "raw": raw,
            "score": score,
        }

    def _fit_meta_models(self, train_df: pl.DataFrame) -> dict | None:
        """训练二级模型。"""
        if train_df.height < 250:
            return None

        primary_bundle = self._fit_primary_models(train_df)
        if primary_bundle is None:
            return None

        predictions = []
        for row_index in range(train_df.height):
            row = train_df.slice(row_index, 1)
            primary_prediction = self._predict_primary(primary_bundle, row)
            if primary_prediction is None:
                predictions.append((np.nan, np.nan, np.nan))
            else:
                predictions.append(
                    (
                        primary_prediction["svm_prob"],
                        primary_prediction["nb_prob"],
                        primary_prediction["score"],
                    )
                )

        prediction_array = np.array(predictions)
        meta_df = train_df.with_columns([
            pl.Series("svm_prob", prediction_array[:, 0], dtype=pl.Float64),
            pl.Series("nb_prob", prediction_array[:, 1], dtype=pl.Float64),
            pl.Series("primary_score", prediction_array[:, 2], dtype=pl.Float64),
        ]).with_columns([
            pl.col("primary_score").shift(1).alias("primary_score_lag1"),
            pl.col("primary_score").shift(2).alias("primary_score_lag2"),
            pl.col("primary_score").shift(3).alias("primary_score_lag3"),
        ]).drop_nulls()

        self.meta_feature_columns = [
            "svm_prob",
            "nb_prob",
            "primary_score",
            "primary_score_lag1",
            "primary_score_lag2",
            "primary_score_lag3",
            "ret_1",
            "ret_5",
            "ret_10",
            "sma_gap_20",
            "sma_gap_60",
            "volatility_20",
            "corr_qqq_20",
            "corr_gold_20",
            "corr_dollar_20",
        ]

        y = (meta_df["forward_mean_return"].to_numpy() > 0).astype(int)
        if len(np.unique(y)) < 2:
            return None

        X = meta_df.select(self.meta_feature_columns).to_numpy()
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        weights = self._log_decay_weights(len(meta_df))

        logistic = LogisticRegression(max_iter=2000, class_weight="balanced", random_state=42)
        ridge = RidgeClassifier(alpha=1.0)
        mlp = MLPClassifier(hidden_layer_sizes=(16, 8), max_iter=1000, random_state=42)

        logistic.fit(X_scaled, y, sample_weight=weights)
        ridge.fit(X_scaled, y, sample_weight=weights)
        mlp.fit(X_scaled, y, sample_weight=weights)

        logistic_prob = logistic.predict_proba(X_scaled)[:, 1]
        ridge_prob = sigmoid(ridge.decision_function(X_scaled))
        mlp_prob = mlp.predict_proba(X_scaled)[:, 1]
        reference_scores = (logistic_prob + ridge_prob + mlp_prob) / 3.0

        return {
            "primary_bundle": primary_bundle,
            "meta_scaler": scaler,
            "logistic": logistic,
            "ridge": ridge,
            "mlp": mlp,
            "reference_scores": reference_scores,
        }

    def _predict_meta(self, bundle: dict, row: pl.DataFrame) -> dict | None:
        """预测二级信号。"""
        if row.height != 1:
            return None

        row = row.with_columns([
            pl.col("primary_score").shift(1).fill_null(pl.col("primary_score")).alias("primary_score_lag1"),
            pl.col("primary_score").shift(1).fill_null(pl.col("primary_score")).alias("primary_score_lag2"),
            pl.col("primary_score").shift(1).fill_null(pl.col("primary_score")).alias("primary_score_lag3"),
        ])

        X = row.select(self.meta_feature_columns).to_numpy()
        X_scaled = bundle["meta_scaler"].transform(X)

        logistic_prob = float(bundle["logistic"].predict_proba(X_scaled)[:, 1][0])
        ridge_prob = float(sigmoid(bundle["ridge"].decision_function(X_scaled))[0])
        mlp_prob = float(bundle["mlp"].predict_proba(X_scaled)[:, 1][0])
        raw = (logistic_prob + ridge_prob + mlp_prob) / 3.0

        return {
            "raw": raw,
            "score": self._raw_to_score(raw, bundle["reference_scores"]),
        }

    @staticmethod
    def _raw_to_score(value: float, reference_scores: np.ndarray) -> float:
        """按分位数映射到 0-5。"""
        thresholds = np.quantile(reference_scores, [1 / 6, 2 / 6, 3 / 6, 4 / 6, 5 / 6])
        return float(np.digitize([value], thresholds, right=True)[0])

    @staticmethod
    def _log_decay_weights(size: int) -> np.ndarray:
        """最近样本更高权重。"""
        order = np.arange(1, size + 1, dtype=float)
        weights = np.log1p(order)
        return weights / weights.max()

    @staticmethod
    def _rolling_mean(values: np.ndarray, window: int) -> np.ndarray:
        result = np.full(values.shape, np.nan)
        for index in range(window - 1, len(values)):
            result[index] = float(np.nanmean(values[index - window + 1: index + 1]))
        return result

    @staticmethod
    def _rolling_std(values: np.ndarray, window: int) -> np.ndarray:
        result = np.full(values.shape, np.nan)
        for index in range(window - 1, len(values)):
            result[index] = float(np.nanstd(values[index - window + 1: index + 1]))
        return result

    @staticmethod
    def _sma_gap(values: np.ndarray, window: int) -> np.ndarray:
        sma = LingxiaoSlvSignalPipeline._rolling_mean(values, window)
        return values / sma - 1.0

    @staticmethod
    def _atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, window: int) -> np.ndarray:
        prev_close = np.roll(close, 1)
        prev_close[0] = close[0]
        tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
        return LingxiaoSlvSignalPipeline._rolling_mean(tr, window)

    @staticmethod
    def _rsi(close: np.ndarray, window: int) -> np.ndarray:
        diff = np.diff(close, prepend=close[0])
        gains = np.clip(diff, 0, None)
        losses = np.clip(-diff, 0, None)
        avg_gain = LingxiaoSlvSignalPipeline._rolling_mean(gains, window)
        avg_loss = LingxiaoSlvSignalPipeline._rolling_mean(losses, window)
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))