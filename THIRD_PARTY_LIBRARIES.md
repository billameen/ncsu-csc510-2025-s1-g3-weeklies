# Third-party libraries

Every package Weeklies installs from [`app/requirements.txt`](app/requirements.txt), with its version, license and a link.
**Update this file whenever `requirements.txt` changes** (see [CONTRIBUTING.md](CONTRIBUTING.md#dependencies)).

Versions are the ones `pip install -r app/requirements.txt` resolved on 2026-10-21 (Python 3.12, Linux and Windows); licenses are from each release's PyPI metadata.
Where `requirements.txt` allows a range, the requirement is shown in brackets.

## Flagged

No package is GPL or AGPL. These need a note:

- **NVIDIA CUDA libraries (`nvidia-*-cu12`), proprietary.** They come with `torch` on Linux only, for GPU support. They are free to use and redistribute under NVIDIA's license, but they are not open source. Weeklies does not ship or change them, and installing the CPU-only build of torch avoids them.
- **`mypy-extensions`, UNKNOWN.** Its PyPI metadata has no license field, but [its repository](https://github.com/python/mypy_extensions/blob/master/LICENSE) is MIT.
- **MPL-2.0 (weak copyleft):** `hypothesis`, `certifi`, `pathspec` and `tqdm`. MPL only applies to changes made to those packages' own files. We use them unmodified, so nothing in Weeklies has to change license.

## Direct dependencies (listed in requirements.txt)

| Package | Version | License | Notes |
|---|---|---|---|
| [accelerate](https://github.com/huggingface/accelerate) | 1.11.0 | Apache-2.0 |  |
| [black](https://github.com/psf/black) | 24.8.0 | MIT |  |
| [click](https://palletsprojects.com/p/click/) | 8.1.7 | BSD-3-Clause |  |
| [Flask](https://github.com/pallets/flask/) | 2.3.3 | BSD |  |
| [hypothesis](https://hypothesis.works) | 6.112.0 | MPL-2.0 | weak copyleft |
| [itsdangerous](https://palletsprojects.com/p/itsdangerous/) | 2.1.2 | BSD-3-Clause |  |
| [Jinja2](https://palletsprojects.com/p/jinja/) | 3.1.2 | BSD-3-Clause |  |
| [Markdown](https://Python-Markdown.github.io/) | 3.11.2 (req >=3.10) | BSD-3-Clause |  |
| [matplotlib](https://matplotlib.org) | 3.9.2 | PSF-based (matplotlib license) |  |
| [openai](https://github.com/openai/openai-python) | 3.36.0 (unpinned) | Apache-2.0 |  |
| [ortools](https://developers.google.com/optimization/) | 9.15.6755 | Apache-2.0 |  |
| [pandas](https://pandas.pydata.org) | 2.3.3 | BSD |  |
| [pdoc](https://pdoc.dev) | 14.4.0 | Unlicense |  |
| [pydantic](https://github.com/pydantic/pydantic) | 2.14.1 (req >=2.7,<3) | MIT |  |
| [pytest](https://docs.pytest.org/en/latest/) | 8.3.3 | MIT |  |
| [pytest-cov](https://github.com/pytest-dev/pytest-cov) | 4.1.0 | MIT |  |
| [python-dotenv](https://github.com/theskumar/python-dotenv) | 1.2.4 (req >=1.2.1) | BSD-3-Clause |  |
| [reportlab](https://www.reportlab.com/) | 4.2.2 | BSD |  |
| [ruff](https://docs.astral.sh/ruff) | 0.6.9 | MIT |  |
| [torch](https://pytorch.org) | 2.9.0 | BSD-3-Clause |  |
| [transformers](https://github.com/huggingface/transformers) | 4.53.3 | Apache-2.0 |  |
| [Werkzeug](https://github.com/pallets/werkzeug/) | 2.3.7 | BSD |  |

## Installed with them (dependencies of the packages above)

| Package | Version | License | Notes |
|---|---|---|---|
| [absl-py](https://github.com/abseil/abseil-py) | 2.5.1 | Apache-2.0 |  |
| [annotated-types](https://github.com/annotated-types/annotated-types) | 0.8.0 | MIT |  |
| [anyio](https://github.com/agronholm/anyio) | 4.15.1 | MIT |  |
| [attrs](https://www.attrs.org/en/stable/changelog.html) | 26.1.0 | MIT |  |
| [blinker](https://github.com/pallets-eco/blinker/) | 1.9.0 | MIT |  |
| [certifi](https://github.com/certifi/python-certifi) | 2026.10.19 | MPL-2.0 | weak copyleft |
| [chardet](https://github.com/chardet/chardet) | 7.7.0 | 0BSD |  |
| [charset-normalizer](https://github.com/jawah/charset_normalizer/blob/master/CHANGELOG.md) | 3.5.2 | MIT |  |
| [colorama](https://github.com/tartley/colorama) | 0.4.6 | BSD | windows only |
| [contourpy](https://github.com/contourpy/contourpy) | 1.4.0 | BSD-3-Clause |  |
| [coverage](https://github.com/coveragepy/coveragepy) | 7.16.2 | Apache-2.0 |  |
| [cycler](https://matplotlib.org/cycler/) | 0.12.1 | BSD |  |
| [filelock](https://github.com/tox-dev/py-filelock) | 4.2.4 | MIT |  |
| [fonttools](http://github.com/fonttools/fonttools) | 4.67.0 | MIT |  |
| [fsspec](https://github.com/fsspec/filesystem_spec) | 2026.9.0 | BSD-3-Clause |  |
| [h11](https://github.com/python-hyper/h11) | 0.16.0 | MIT |  |
| [hf-xet](https://github.com/huggingface/xet-core) | 1.7.0 | Apache-2.0 |  |
| [httpcore2](https://github.com/pydantic/httpx2) | 2.16.0 | BSD-3-Clause |  |
| [httpx2](https://github.com/pydantic/httpx2) | 2.16.0 | BSD-3-Clause |  |
| [huggingface-hub](https://github.com/huggingface/huggingface_hub) | 0.36.2 | Apache-2.0 |  |
| [idna](https://github.com/kjd/idna) | 3.20 | BSD-3-Clause |  |
| [immutabledict](https://github.com/corenting/immutabledict) | 4.3.1 | MIT |  |
| [iniconfig](https://github.com/pytest-dev/iniconfig) | 2.3.1 | MIT |  |
| [jiter](https://github.com/pydantic/jiter/) | 0.17.0 | MIT |  |
| [kiwisolver](https://github.com/nucleic/kiwi) | 1.5.1 | BSD |  |
| [MarkupSafe](https://github.com/pallets/markupsafe/) | 3.0.4 | BSD-3-Clause |  |
| [mpmath](http://mpmath.org/) | 1.3.0 | BSD |  |
| [mypy-extensions](https://github.com/python/mypy_extensions) | 1.1.0 | UNKNOWN on PyPI (MIT in its repo) | see notes |
| [networkx](https://networkx.org/) | 3.7 | BSD-3-Clause |  |
| [numpy](https://numpy.org) | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |  |
| [nvidia-cublas-cu12](https://developer.nvidia.com/cuda-zone) | 12.8.4.1 | NVIDIA proprietary | see notes, linux only |
| [nvidia-cuda-cupti-cu12](https://developer.nvidia.com/cuda-zone) | 12.8.90 | NVIDIA proprietary | see notes, linux only |
| [nvidia-cuda-nvrtc-cu12](https://developer.nvidia.com/cuda-zone) | 12.8.93 | NVIDIA proprietary | see notes, linux only |
| [nvidia-cuda-runtime-cu12](https://developer.nvidia.com/cuda-zone) | 12.8.90 | NVIDIA proprietary | see notes, linux only |
| [nvidia-cudnn-cu12](https://developer.nvidia.com/cuda-zone) | 9.10.2.21 | NVIDIA proprietary | see notes, linux only |
| [nvidia-cufft-cu12](https://developer.nvidia.com/cuda-zone) | 11.3.3.83 | NVIDIA proprietary | see notes, linux only |
| [nvidia-cufile-cu12](https://developer.nvidia.com/cuda-zone) | 1.13.1.3 | NVIDIA proprietary | see notes, linux only |
| [nvidia-curand-cu12](https://developer.nvidia.com/cuda-zone) | 10.3.9.90 | NVIDIA proprietary | see notes, linux only |
| [nvidia-cusolver-cu12](https://developer.nvidia.com/cuda-zone) | 11.7.3.90 | NVIDIA proprietary | see notes, linux only |
| [nvidia-cusparse-cu12](https://developer.nvidia.com/cuda-zone) | 12.5.8.93 | NVIDIA proprietary | see notes, linux only |
| [nvidia-cusparselt-cu12](https://developer.nvidia.com/cusparselt) | 0.7.1 | NVIDIA proprietary | see notes, linux only |
| [nvidia-nccl-cu12](https://developer.nvidia.com/cuda-zone) | 2.27.5 | BSD-3-Clause | linux only |
| [nvidia-nvjitlink-cu12](https://developer.nvidia.com/cuda-zone) | 12.8.93 | NVIDIA proprietary | see notes, linux only |
| [nvidia-nvshmem-cu12](https://developer.nvidia.com/cuda-zone) | 3.3.20 | BSD-3-Clause | linux only |
| [nvidia-nvtx-cu12](https://developer.nvidia.com/cuda-zone) | 12.8.90 | Apache-2.0 | linux only |
| [packaging](https://github.com/pypa/packaging) | 26.3 | Apache-2.0 OR BSD-2-Clause |  |
| [pathspec](https://github.com/cpburnz/python-pathspec) | 1.1.1 | MPL-2.0 | weak copyleft |
| [pillow](https://python-pillow.org) | 13.0.0 | MIT-CMU |  |
| [platformdirs](https://github.com/tox-dev/platformdirs) | 4.13.5 | MIT |  |
| [pluggy](https://github.com/pytest-dev/pluggy) | 1.7.0 | MIT |  |
| [protobuf](https://developers.google.com/protocol-buffers/) | 6.33.6 | BSD-3-Clause |  |
| [psutil](https://github.com/giampaolo/psutil) | 7.2.2 | BSD-3-Clause |  |
| [pydantic_core](https://github.com/pydantic/pydantic) | 2.50.1 | MIT |  |
| [Pygments](https://pygments.org) | 2.21.0 | BSD-2-Clause |  |
| [pyparsing](https://github.com/pyparsing/pyparsing/) | 3.3.3 | MIT |  |
| [python-dateutil](https://github.com/dateutil/dateutil) | 2.9.0.post0 | Apache-2.0 OR BSD-3-Clause |  |
| [pytz](http://pythonhosted.org/pytz) | 2026.5 | MIT |  |
| [PyYAML](https://pyyaml.org/) | 6.0.3 | MIT |  |
| [regex](https://github.com/mrabarnett/mrab-regex) | 2026.9.29 | Apache-2.0 AND CNRI-Python |  |
| [requests](https://github.com/psf/requests) | 2.34.2 | Apache-2.0 |  |
| [safetensors](https://github.com/huggingface/safetensors) | 0.8.0 | Apache-2.0 |  |
| [setuptools](https://github.com/pypa/setuptools) | 84.2.1 | MIT |  |
| [six](https://github.com/benjaminp/six) | 1.17.0 | MIT |  |
| [sniffio](https://github.com/python-trio/sniffio) | 1.3.1 | MIT OR Apache-2.0 |  |
| [sortedcontainers](http://www.grantjenks.com/docs/sortedcontainers/) | 2.4.0 | Apache-2.0 |  |
| [sympy](https://sympy.org) | 1.14.0 | BSD |  |
| [tokenizers](https://github.com/huggingface/tokenizers) | 0.21.4 | Apache-2.0 |  |
| [tqdm](https://tqdm.github.io) | 4.70.1 | MPL-2.0 AND MIT | weak copyleft |
| [triton](https://github.com/triton-lang/triton/) | 3.5.0 | MIT | linux only |
| [truststore](https://github.com/sethmlarson/truststore) | 0.10.5 | MIT |  |
| [typing-extensions](https://github.com/python/typing_extensions) | 4.16.0 | PSF-2.0 |  |
| [typing-inspection](https://github.com/pydantic/typing-inspection) | 0.4.4 | MIT |  |
| [tzdata](https://github.com/python/tzdata) | 2026.5 | Apache-2.0 |  |
| [urllib3](https://github.com/urllib3/urllib3/blob/main/CHANGES.rst) | 2.8.0 | MIT |  |

## Regenerating

In a clean virtual environment:

```bash
pip install -r app/requirements.txt
pip install pip-licenses
pip-licenses --format=markdown --with-urls
```

Copy the new versions and licenses into the tables above. Don't paste the output over this file, or the notes are lost. Then check again for UNKNOWN and copyleft (GPL/AGPL) licenses.
