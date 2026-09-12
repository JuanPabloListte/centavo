"""La API contra el esquema de demostración, con datos sintéticos.

    uvicorn app.demo:app --host 127.0.0.1 --port 8000

Sirve para ver y probar la interfaz sin mostrar datos reales. El esquema se arma
con `python -m tools.demo`. La variable se fija antes de importar la app porque
la conexión lee el esquema al importarse.
"""

import os

os.environ.setdefault("CENTAVO_DB_SCHEMA", "demo")

from .main import app  # noqa: E402,F401
