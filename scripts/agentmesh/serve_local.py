"""MLX entrypoint with parent-death cleanup, including forced runner termination."""

import runpy, sys
from process_guard import watch_parent

watch_parent()
sys.argv = ["mlx_lm", "server", *sys.argv[1:]]
runpy.run_module("mlx_lm", run_name="__main__")
