# Classifier model

Place the trained classifier here:

```
model/bracs_v3_model.pkl
```

- **Model**: `bracs_v3_model` — logistic-regression head over 2304-d
  (mean + max + std pooled CONCH v1.5 / TITAN features)
- **CV-AUC**: 0.9727  ·  **Threshold**: 0.30

The backend reads it via the `CLASSIFIER_PATH` env var
(default `./model/bracs_v3_model.pkl`, see `main.py`).

In Docker the `model/` folder is mounted read-only at `/model`
(see `docker-compose.yml`), so `CLASSIFIER_PATH=/model/bracs_v3_model.pkl`.
