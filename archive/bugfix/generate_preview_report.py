from __future__ import annotations

import argparse
from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
import pandas as pd

from config.limits import LIMIT_POLICY
from config.product_config import PRODUCT_CATALOG
from core.application import AnalysisApplicationService
from core.parser import get_freq_values
from export.excel_report import ExcelReportBuilder


FIG_WIDTH, PLOT_HEIGHT = 14, 6
FONT_SIZE_TITLE, FONT_SIZE_AXIS = 16, 12
APPLICATION_SERVICE = AnalysisApplicationService(PRODUCT_CATALOG, LIMIT_POLICY)


def create_fr_plot(report, show_normal, highlight_indices, for_excel=False):
    product_spec = report.product_spec
    uploaded_log = report.uploaded_log
    df = uploaded_log.df
    current_test_data = uploaded_log.test_data
    limit_low = uploaded_log.limit_low
    limit_high = uploaded_log.limit_high

    num_draw = 3 if for_excel else len(product_spec.channels)
    fig, axes = plt.subplots(num_draw, 1, figsize=(FIG_WIDTH, PLOT_HEIGHT * num_draw))
    if num_draw == 1:
        axes = [axes]
    if for_excel:
        fig.patch.set_linewidth(0)
    for i in range(num_draw):
        ax = axes[i]
        if i < len(product_spec.channels):
            ch = product_spec.channels[i]
            cols = df.columns[ch.column_range]
            freqs = get_freq_values(cols)
            ylim, color, unit = ((-30, 0), 'green', 'dbV') if ch.mic_type == 'analog' else ((-45, -25), 'blue', 'dbFS')
            ax.set_xscale('log')
            ax.set_xticks([50, 100, 200, 1000, 4000, 10000, 14000])
            ax.get_xaxis().set_major_formatter(ticker.ScalarFormatter())
            ax.minorticks_off()
            if show_normal:
                for n in report.plotting_normal_indices:
                    ax.plot(freqs, pd.to_numeric(current_test_data.loc[n, cols], errors='coerce'), color=color, alpha=0.7, lw=1.2)
            for h in highlight_indices:
                ax.plot(freqs, pd.to_numeric(current_test_data.loc[h, cols], errors='coerce'), color='red', lw=2.5)
            ax.plot(freqs, pd.to_numeric(limit_low[cols], errors='coerce'), 'k--', lw=1.2)
            ax.plot(freqs, pd.to_numeric(limit_high[cols], errors='coerce'), 'k--', lw=1.2)
            ax.set_title(ch.name, fontsize=FONT_SIZE_TITLE, fontweight='bold', pad=15)
            ax.set_ylabel(f'Response ({unit})', fontsize=FONT_SIZE_AXIS)
            ax.set_ylim(ylim)
            ax.grid(True, alpha=0.4)
        else:
            ax.axis('off')
    plt.tight_layout()
    return fig


def plot_bell_curve_set(report, sel_idx, for_excel=False):
    product_spec = report.product_spec
    uploaded_log = report.uploaded_log
    df = uploaded_log.df
    test_data = uploaded_log.test_data
    num_draw = 3 if for_excel else len(product_spec.channels)
    fig, axes = plt.subplots(num_draw, 1, figsize=(FIG_WIDTH, PLOT_HEIGHT * num_draw))
    if num_draw == 1:
        axes = [axes]
    if for_excel:
        fig.patch.set_linewidth(0)
    for i in range(num_draw):
        ax = axes[i]
        if i < len(product_spec.channels):
            ch = product_spec.channels[i]
            col_idx = np.argmin(np.abs(np.array(get_freq_values(df.columns[ch.column_range])) - 1000))
            v_all = pd.to_numeric(test_data[df.columns[ch.column_range][col_idx]], errors='coerce')
            v_clean = v_all.iloc[list(report.stats_indices)].dropna()
            lcl, ucl = LIMIT_POLICY.cpk_limit_for(ch.mic_type)
            if len(v_clean) >= 2:
                mu, std = v_clean.mean(), v_clean.std()
                cpk = min((ucl - mu) / (3 * std), (mu - lcl) / (3 * std)) if std > 0 else 0
                x_r = np.linspace(lcl - 2, ucl + 2, 200)
                p = (1 / (std * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((x_r - mu) / std) ** 2)
                ax.plot(x_r, p, 'k', lw=2.5, alpha=0.7)
                ax.fill_between(x_r, p, color='gray', alpha=0.1)
                ax.axvline(lcl, color='blue', ls='--', lw=1.5)
                ax.axvline(ucl, color='red', ls='--', lw=1.5)
                if sel_idx:
                    sel_v = v_all.iloc[list(sel_idx)].dropna()
                    for v in sel_v:
                        if std > 0:
                            p_v = (1 / (std * np.sqrt(2 * np.pi))) * np.exp(-0.5 * ((v - mu) / std) ** 2)
                            ax.scatter(v, p_v, color='red', s=200, zorder=5, edgecolors='white', linewidth=1.5)
                ax.text(0.95, 0.75, f'Cpk: {round(cpk, 2)}', transform=ax.transAxes, ha='right', va='top', bbox=dict(boxstyle='round', facecolor='white', alpha=0.8), fontsize=FONT_SIZE_AXIS, fontweight='bold')
                ax.set_title(f'{ch.name} - Distribution', fontsize=FONT_SIZE_TITLE, fontweight='bold', pad=15)
                ax.set_xlim(lcl - 2, ucl + 2)
                ax.grid(True, alpha=0.2)
        else:
            ax.axis('off')
    plt.tight_layout()
    return fig


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('csv_path')
    parser.add_argument('--output-dir', default='archive/bugfix/preview')
    parser.add_argument('--model', default=None)
    parser.add_argument('--detail-count', type=int, default=6)
    parser.add_argument('--hide-normal', action='store_true')
    args = parser.parse_args()

    csv_path = Path(args.csv_path)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with csv_path.open('rb') as f:
        df = APPLICATION_SERVICE.read_dataframe(f)

    detection = APPLICATION_SERVICE.detect_product(df)
    model_name = args.model or detection.model_name or PRODUCT_CATALOG.model_names()[0]
    report = APPLICATION_SERVICE.analyze(df, model_name, detection)
    selected_indices = tuple(report.issue_indices[: args.detail_count])
    excel_bytes = ExcelReportBuilder(
        report,
        LIMIT_POLICY,
        not args.hide_normal,
        selected_indices,
        create_fr_plot,
        plot_bell_curve_set,
    ).build()

    out_name = f'{csv_path.stem}_{report.detection.report_basename}.xlsx'
    out_path = output_dir / out_name
    out_path.write_bytes(excel_bytes)

    print(f'csv={csv_path.as_posix()}')
    print(f'model={model_name}')
    print(f'total_qty={report.total_qty}')
    print(f'total_pass={report.total_pass}')
    print(f'total_fail={report.total_fail}')
    print(f'issue_count={len(report.issue_indices)}')
    print(f'selected_detail={len(selected_indices)}')
    print(f'output={out_path.as_posix()}')


if __name__ == '__main__':
    main()
