$ErrorActionPreference = "Stop"
python -m unittest discover -s tests -v
python main.py examples/arithmetic.c --show-ir --dump-cfg
python main.py examples/loop.c --dump-cfg
python main.py examples/deopt_demo.sjit --hot-threshold 1
python benchmarks/run_benchmarks.py
