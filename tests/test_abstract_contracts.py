from typing import Any, cast

import pytest

from GensokyoAI.backends.base import BaseBackend
from GensokyoAI.background.workers.base import BaseWorker


def test_base_backend_cannot_be_instantiated() -> None:
    backend_class = cast(Any, BaseBackend)
    with pytest.raises(TypeError):
        backend_class()


def test_base_worker_cannot_be_instantiated() -> None:
    worker_class = cast(Any, BaseWorker)
    with pytest.raises(TypeError):
        worker_class()
