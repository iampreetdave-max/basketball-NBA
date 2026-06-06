# NBA Predictions

![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?style=flat&logo=python&logoColor=white)

Machine-learning pipeline that predicts NBA game scores, moneyline winners, over/under totals, and spread coverage from pre-match team stats and betting odds.

## Overview

This project produces structured predictions for upcoming NBA games. It merges
pre-match team features with bookmaker odds (DraftKings spreads and totals),
feeds engineered features into trained XGBoost models, and outputs a prediction
table covering moneyline, totals (over/under), and spread markets. A separate
validation stage backfills actual results and computes accuracy and profit/loss.

The output schema mirrors a shared "soccer schema" so predictions across sports
can be stored and validated uniformly.

## Key Features

- **Score prediction** — separate XGBoost models predict home and away points.
- **Derived markets** — moneyline winner, predicted total vs. line (over/under),
  and spread coverage are computed from the predicted scores.
- **Confidence and grading** — a confidence score derived from the predicted
  margin is used to assign letter grades per market (ML, over/under, spread).
- **Odds integration** — merges DraftKings spreads and totals with pre-match
  features via a shared `game_identifier`.
- **Validation pipeline** — backfills actual results and computes accuracy and PnL.
- **Tie handling** — near-tie score predictions get a small randomized adjustment
  favoring the team with better odds.

## How It Works

The pipeline runs as a sequence of scripts:

1. **`Combine.py`** — merges `nba_prematch_features.csv` with
   `upcoming_nba_draftkings_odds.csv` (joined on `game_identifier`) into `Future.csv`.
2. **`predict.py`** — loads the trained models from `model/`, builds defense /
   form / market features, predicts home and away points, derives moneyline,
   over/under, and spread outputs, and writes `NBA_PREDICTIONS_ML.csv`.
3. **`validate.py`** — compares predictions against actual results and reports
   accuracy and profit/loss.

`Odds_Pre_Match.py`, `Pre_Match.py`, and `save.py` support data preparation and
persistence around this core flow.

### Models

Trained model artifacts live in `model/`:

- `hybrid_home_xgb.pkl` — home points model
- `hybrid_away_xgb.pkl` — away points model
- `hybrid_scaler.pkl` — feature scaler

## Tech Stack

- **Language:** Python
- **ML:** XGBoost, scikit-learn
- **Data:** pandas, NumPy
- **Storage / I/O:** CSV files, `psycopg2-binary` (PostgreSQL connectivity)
- **HTTP:** requests

## Getting Started

### Prerequisites

- Python 3.9+
- The trained model files present in `model/`

### Installation

```bash
git clone https://github.com/iampreetdave-max/basketball-NBA.git
cd basketball-NBA
pip install -r requirements.txt
```

### Running the pipeline

```bash
# 1. Merge pre-match features with odds into Future.csv
python Combine.py

# 2. Generate predictions -> NBA_PREDICTIONS_ML.csv
python predict.py

# 3. Validate predictions against actual results
python validate.py
```

`predict.py` reads `Future.csv` and writes `NBA_PREDICTIONS_ML.csv`. Input CSVs
must contain the expected columns (team stats, recent form, and decimal odds);
see `Combine.py` for the full set of merged fields.

## Project Structure

```
basketball-NBA/
├── Combine.py                        # Merge pre-match features + odds -> Future.csv
├── predict.py                        # Load models, predict, write predictions CSV
├── validate.py                       # Validate predictions, compute accuracy/PnL
├── Odds_Pre_Match.py                 # Odds + pre-match data prep
├── Pre_Match.py                      # Pre-match feature preparation
├── save.py                           # Persistence helper
├── model/
│   ├── hybrid_home_xgb.pkl           # Home points model
│   ├── hybrid_away_xgb.pkl           # Away points model
│   └── hybrid_scaler.pkl             # Feature scaler
├── nba_prematch_features.csv         # Sample pre-match features
├── upcoming_nba_draftkings_odds.csv  # Sample odds input
├── requirements.txt
└── LICENSE
```

## Disclaimer

This project is for research and educational purposes. Sports betting carries
financial risk; predictions are not guarantees.

## License

This project is licensed under the terms of the [LICENSE](LICENSE) file in this repository.
