"""Download the weights and label files for the model check, from each model's official Hugging Face repo.

Safe to rerun: hf_hub_download skips files that are already in the Hugging Face cache.
Only the files the check needs are fetched (safetensors where offered, not the duplicate .bin).

Run: data/model_check/.venv/bin/python -u experiments/model_check/download.py
"""

import time

from huggingface_hub import HfApi, hf_hub_download

# (repo, repo_type, files)
FILES = [
    ("imageomics/bioclip", "model", ["open_clip_config.json", "open_clip_pytorch_model.bin"]),
    ("imageomics/TreeOfLife-10M", "dataset", ["embeddings/txt_emb_species.json", "embeddings/txt_emb_species.npy"]),
    ("facebook/dinov2-large", "model", ["config.json", "preprocessor_config.json", "model.safetensors"]),
    ("timm/eva02_large_patch14_clip_336.merged2b_ft_inat21", "model", ["config.json", "model.safetensors"]),
    ("imageomics/bioclip-2.5-vith14", "model", ["open_clip_config.json", "open_clip_model.safetensors"]),
    (
        "imageomics/TreeOfLife-200M",
        "dataset",
        ["embeddings/txt_emb_bioclip-2.5-vith14.json", "embeddings/txt_emb_bioclip-2.5-vith14.npy"],
    ),
]


def main():
    api = HfApi()
    total = 0
    for repo, rtype, files in FILES:
        info = api.repo_info(repo, repo_type=rtype, files_metadata=True)
        sizes = {s.rfilename: s.size or 0 for s in info.siblings}
        for f in files:
            mb = sizes.get(f, 0) / 1e6
            total += mb
            t0 = time.time()
            print(f"{repo} {f}: {mb:,.0f} MB ...", flush=True)
            path = hf_hub_download(repo, f, repo_type=rtype)
            print(f"  done in {time.time() - t0:.0f}s -> {path}", flush=True)
    print(f"total {total / 1000:.2f} GB", flush=True)


if __name__ == "__main__":
    main()
