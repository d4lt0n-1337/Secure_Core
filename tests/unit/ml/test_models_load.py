from pathlib import Path

import joblib


def test_all_joblib_models_load():
    models_dir = Path(__file__).resolve().parents[3] / 'models'
    joblibs = sorted(models_dir.glob('*.joblib'))
    assert joblibs, 'No .joblib models found in models/'

    for p in joblibs:
        obj = joblib.load(p)
        assert obj is not None
